/*
 * Fixed-delay exchange between the realtime thread and the worker.
 * See poise_core.h for the model.
 */
#include "poise_core.h"

#include <errno.h>
#include <semaphore.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define HIST_MASK (POISE_HIST_SIZE - 1u)
/* Input and output counts may differ by a few samples per cycle when the
 * graph runs at another rate (adapter resampling); beyond this the
 * difference is a real gap or burst and is corrected. */
#define LEAD_TOLERANCE 64
/* Late frames still processed after a hiccup, so the engine's streaming
 * state stays continuous; beyond this the worker jumps ahead. */
#define SKIP_SLACK 4
/* Keep the worker this far from the history's overwrite edge. */
#define HIST_GUARD 4096
/* Peak below which audio counts as silence (about -100 dBFS). */
#define SILENCE 1e-5f

struct poise_core {
	uint32_t frame;
	uint32_t dry_delay;
	uint32_t quantum;
	uint32_t margin;
	uint32_t fade;
	float dry_gain;

	_Atomic uint64_t in_pos;   /* samples in hist (realtime writes) */
	_Atomic uint64_t out_pos;  /* samples output (realtime writes) */
	_Atomic uint64_t delay;    /* fixed delay (realtime writes) */
	_Atomic int stopping;
	_Atomic int worker_active; /* set by the first wait; before it, dry
	                            * output is expected and not counted */

	/* Realtime thread only: wet/dry mode of the frame being output. */
	int64_t mode_frame;
	int64_t planned_dry;   /* frame committed to dry during a fade-out */
	int64_t checked_frame; /* frame whose successor was checked */
	int cur_wet;
	int fade_in;
	int fade_out;
	int cycle_audible;     /* this cycle's input carried sound */

	/* Worker thread only. */
	int64_t worker_next;

	sem_t sem;
	int sem_ok;
	_Atomic uint64_t stats[POISE_STAT_COUNT];
	_Atomic uint64_t wet_id[POISE_WET_SLOTS]; /* frame index + 1, 0 = empty */
	/* Output's decision per frame: (index + 1) * 2 + wet, 0 = undecided. */
	_Atomic uint64_t decided[POISE_WET_SLOTS];
	float *wet;                               /* POISE_WET_SLOTS * frame */
	float hist[POISE_HIST_SIZE];
};

static inline void stat_add(poise_core *c, enum poise_stat s, uint64_t v)
{
	atomic_fetch_add_explicit(&c->stats[s], v, memory_order_relaxed);
}

static inline void stat_set(poise_core *c, enum poise_stat s, uint64_t v)
{
	atomic_store_explicit(&c->stats[s], v, memory_order_relaxed);
}

static inline int64_t floor_div(int64_t a, int64_t b)
{
	int64_t q = a / b;
	if ((a % b) != 0 && ((a < 0) != (b < 0)))
		q--;
	return q;
}

static void reset_mode(poise_core *c)
{
	c->mode_frame = INT64_MIN;
	c->planned_dry = INT64_MIN;
	c->checked_frame = INT64_MIN;
	c->cur_wet = 0;
	c->fade_in = 0;
	c->fade_out = 0;
}

poise_core *poise_core_new(uint32_t frame, uint32_t dry_delay,
		uint32_t quantum, uint32_t margin, uint32_t fade, float dry_gain)
{
	poise_core *c;

	if (frame == 0 || frame > 8192 || fade * 2 > frame)
		return NULL;
	c = calloc(1, sizeof(*c));
	if (c == NULL)
		return NULL;
	c->wet = calloc((size_t)POISE_WET_SLOTS * frame, sizeof(float));
	if (c->wet == NULL) {
		free(c);
		return NULL;
	}
	if (sem_init(&c->sem, 0, 0) == 0)
		c->sem_ok = 1;
	c->frame = frame;
	c->dry_delay = dry_delay;
	c->quantum = quantum;
	c->margin = margin;
	c->fade = fade;
	c->dry_gain = dry_gain;
	atomic_init(&c->delay, (uint64_t)frame + quantum + fade + margin);
	stat_set(c, POISE_STAT_DELAY, atomic_load(&c->delay));
	reset_mode(c);
	return c;
}

void poise_core_free(poise_core *c)
{
	if (c == NULL)
		return;
	if (c->sem_ok)
		sem_destroy(&c->sem);
	free(c->wet);
	free(c);
}

/* Make samples up to new_pos visible to the worker; wake it when a frame
 * completed. sem_post is lock-free (a futex wake only with waiters). */
static void publish(poise_core *c, uint64_t old_pos, uint64_t new_pos)
{
	atomic_store_explicit(&c->in_pos, new_pos, memory_order_release);
	stat_set(c, POISE_STAT_IN_POS, new_pos);
	if (c->sem_ok && new_pos / c->frame > old_pos / c->frame)
		sem_post(&c->sem);
}

void poise_core_input(poise_core *c, const float *const *planes,
		uint32_t n_planes, uint32_t n)
{
	uint64_t ip = atomic_load_explicit(&c->in_pos, memory_order_relaxed);
	float scale;
	uint32_t i, ch;

	if (n_planes == 0 || n == 0)
		return;
	if (n_planes > POISE_MAX_PLANES)
		n_planes = POISE_MAX_PLANES;
	scale = 1.0f / (float)n_planes;
	for (i = 0; i < n; i++) {
		float s = 0.0f;
		for (ch = 0; ch < n_planes; ch++)
			s += planes[ch][i];
		s *= scale;
		c->hist[(ip + i) & HIST_MASK] = s;
		if (s > SILENCE || s < -SILENCE)
			c->cycle_audible = 1;
	}
	publish(c, ip, ip + n);
}

static inline int wet_ready(poise_core *c, int64_t k)
{
	return atomic_load_explicit(&c->wet_id[(uint64_t)k % POISE_WET_SLOTS],
			memory_order_acquire) == (uint64_t)k + 1;
}

/* Unprocessed input for output position s: delayed by the engine's own
 * delay so it lines up with processed audio. */
static inline float dry_at(poise_core *c, int64_t s, uint64_t ip)
{
	int64_t q = s - (int64_t)c->dry_delay;
	float v;

	if (q < 0 || (uint64_t)q >= ip || ip - (uint64_t)q > POISE_HIST_SIZE)
		return 0.0f;
	v = c->hist[(uint64_t)q & HIST_MASK] * c->dry_gain;
	return v > 1.0f ? 1.0f : (v < -1.0f ? -1.0f : v);
}

static inline void record_decision(poise_core *c, int64_t k, int wet)
{
	atomic_store_explicit(&c->decided[(uint64_t)k % POISE_WET_SLOTS],
			((uint64_t)k + 1) * 2 + (wet ? 1 : 0), memory_order_release);
}

/* Whether the unprocessed audio for frame k has any sound in it. */
static int dry_frame_audible(poise_core *c, int64_t k, uint64_t ip)
{
	int64_t q = k * (int64_t)c->frame - (int64_t)c->dry_delay;
	uint32_t i;

	for (i = 0; i < c->frame; i++, q++) {
		float v;
		if (q < 0 || (uint64_t)q >= ip)
			continue;
		v = c->hist[(uint64_t)q & HIST_MASK];
		if (v > SILENCE || v < -SILENCE)
			return 1;
	}
	return 0;
}

/* Output for source position s (input timeline). Wet/dry is decided per
 * frame; a switch crossfades over `fade` samples: wet->dry at the end of
 * the last wet frame (decided `fade` samples early), dry->wet at the
 * start of the first wet frame. */
static float out_sample(poise_core *c, int64_t s, uint64_t ip)
{
	const int64_t F = c->frame;
	int64_t k;
	uint32_t o;
	float y, r;

	if (s < 0)
		return 0.0f;
	k = s / F;
	o = (uint32_t)(s - k * F);

	if (k != c->mode_frame) {
		int prev_wet = c->mode_frame == k - 1 && c->cur_wet && !c->fade_out;
		int wet = c->planned_dry == k ? 0 : wet_ready(c, k);

		c->fade_in = wet && !prev_wet;
		c->fade_out = 0;
		c->cur_wet = wet;
		c->mode_frame = k;
		record_decision(c, k, wet);
		/* Unprocessed silence is not worth counting. */
		if (wet)
			stat_add(c, POISE_STAT_FRAMES_WET, 1);
		else if (atomic_load_explicit(&c->worker_active, memory_order_relaxed) &&
			 dry_frame_audible(c, k, ip))
			stat_add(c, POISE_STAT_FRAMES_DRY, 1);
	}
	if (c->cur_wet && !c->fade_out && o + c->fade >= (uint32_t)F &&
	    c->checked_frame != k) {
		c->checked_frame = k;
		if (!wet_ready(c, k + 1)) {
			c->fade_out = 1;
			c->planned_dry = k + 1;
			record_decision(c, k + 1, 0);
		}
	}
	if (!c->cur_wet)
		return dry_at(c, s, ip);

	y = c->wet[((uint64_t)k % POISE_WET_SLOTS) * (uint64_t)F + o];
	if (c->fade_in && o < c->fade) {
		r = (float)(o + 1) / (float)(c->fade + 1);
		y = r * y + (1.0f - r) * dry_at(c, s, ip);
	}
	if (c->fade_out && o + c->fade >= (uint32_t)F) {
		r = (float)(o + c->fade - (uint32_t)F + 1) / (float)(c->fade + 1);
		y = (1.0f - r) * y + r * dry_at(c, s, ip);
	}
	return y;
}

int poise_core_output(poise_core *c, float *const *planes,
		uint32_t n_planes, uint32_t n)
{
	uint64_t ip = atomic_load_explicit(&c->in_pos, memory_order_relaxed);
	uint64_t op = atomic_load_explicit(&c->out_pos, memory_order_relaxed);
	uint64_t d = atomic_load_explicit(&c->delay, memory_order_relaxed);
	uint64_t need;
	int changed = 0, audible;
	uint32_t i, ch;

	if (n == 0)
		return 0;
	if (n_planes > POISE_MAX_PLANES)
		n_planes = POISE_MAX_PLANES;
	stat_set(c, POISE_STAT_QUANTUM, n);
	if (n > atomic_load_explicit(&c->stats[POISE_STAT_QUANTUM_MAX],
			memory_order_relaxed))
		stat_set(c, POISE_STAT_QUANTUM_MAX, n);

	/* Input fell short of this cycle: the missing input is silence, so
	 * the delay between input and output stays exactly the same. */
	if (ip + LEAD_TOLERANCE < op + n) {
		uint64_t end = op + n, p;
		for (p = ip; p < end; p++)
			c->hist[p & HIST_MASK] = 0.0f;
		publish(c, ip, end);
		stat_add(c, POISE_STAT_INPUT_GAPS, 1);
		ip = end;
	}
	/* Input ran ahead (a burst): jump the output to it instead of
	 * letting the extra input become extra delay. */
	if (ip > op + n + LEAD_TOLERANCE) {
		op = ip - n;
		stat_add(c, POISE_STAT_RESYNCS, 1);
		reset_mode(c);
	}
	/* A cycle longer than the delay was sized for leaves the worker no
	 * time at all: raise the delay once to fit it. Only while sound
	 * flows: with no app on the sink, PipeWire ignores our node.latency
	 * and runs its default cycle, and unprocessed silence costs nothing. */
	need = (uint64_t)c->frame + n + c->fade + c->margin;
	audible = c->cycle_audible;
	c->cycle_audible = 0;
	if (need > d && audible) {
		d = need;
		atomic_store_explicit(&c->delay, d, memory_order_relaxed);
		stat_set(c, POISE_STAT_DELAY, d);
		stat_add(c, POISE_STAT_DELAY_CHANGES, 1);
		reset_mode(c);
		changed = 1;
	}

	for (i = 0; i < n; i++) {
		float y = out_sample(c, (int64_t)(op + i) - (int64_t)d, ip);
		for (ch = 0; ch < n_planes; ch++)
			planes[ch][i] = y;
	}
	atomic_store_explicit(&c->out_pos, op + n, memory_order_release);
	stat_set(c, POISE_STAT_OUT_POS, op + n);
	stat_add(c, POISE_STAT_CYCLES, 1);
	return changed;
}

void poise_core_count_trigger_fail(poise_core *c)
{
	stat_add(c, POISE_STAT_TRIGGER_FAILS, 1);
}

/* Last frame the output has already decided on (wet or dry): frame k is
 * decided once the output reaches `fade` samples before its start. */
static int64_t committed_frame(poise_core *c)
{
	int64_t op = (int64_t)atomic_load_explicit(&c->out_pos, memory_order_acquire);
	int64_t d = (int64_t)atomic_load_explicit(&c->delay, memory_order_relaxed);
	return floor_div(op - d + (int64_t)c->fade, (int64_t)c->frame);
}

int64_t poise_core_wait_frame(poise_core *c, float *dst, int timeout_ms)
{
	const int64_t F = c->frame;
	struct timespec deadline;

	clock_gettime(CLOCK_REALTIME, &deadline);
	if (timeout_ms > 0) {
		deadline.tv_sec += timeout_ms / 1000;
		deadline.tv_nsec += (long)(timeout_ms % 1000) * 1000000L;
		if (deadline.tv_nsec >= 1000000000L) {
			deadline.tv_sec++;
			deadline.tv_nsec -= 1000000000L;
		}
	}
	for (;;) {
		uint64_t ip;
		int64_t next, first_open, oldest, limit, i;

		if (atomic_load_explicit(&c->stopping, memory_order_acquire))
			return -2;
		ip = atomic_load_explicit(&c->in_pos, memory_order_acquire);
		next = c->worker_next;

		/* Frames the output already decided on are wasted work; after
		 * more than a short hiccup, jump to the first open one. The
		 * first call starts there without counting a skip. */
		first_open = committed_frame(c) + 1;
		if (!atomic_load_explicit(&c->worker_active, memory_order_relaxed)) {
			atomic_store_explicit(&c->worker_active, 1, memory_order_relaxed);
			if (next < first_open)
				next = first_open;
		}
		if (next < first_open - SKIP_SLACK) {
			stat_add(c, POISE_STAT_FRAMES_SKIPPED, (uint64_t)(first_open - next));
			next = first_open;
		}
		/* Never read where the history is about to be overwritten. */
		limit = (int64_t)ip - (int64_t)(POISE_HIST_SIZE - HIST_GUARD);
		oldest = limit > 0 ? (limit + F - 1) / F : 0;
		if (next < oldest) {
			stat_add(c, POISE_STAT_FRAMES_SKIPPED, (uint64_t)(oldest - next));
			next = oldest;
		}
		if (next < 0)
			next = 0;

		if (next < (int64_t)(ip / (uint64_t)F)) {
			uint64_t start = (uint64_t)next * (uint64_t)F;
			for (i = 0; i < F; i++)
				dst[i] = c->hist[(start + (uint64_t)i) & HIST_MASK];
			c->worker_next = next + 1;
			return next;
		}
		c->worker_next = next;
		if (timeout_ms <= 0 || !c->sem_ok)
			return -1;
		while (sem_timedwait(&c->sem, &deadline) != 0) {
			if (errno != EINTR)
				return atomic_load(&c->stopping) ? -2 : -1;
		}
	}
}

void poise_core_put_frame(poise_core *c, int64_t k, const float *src)
{
	uint64_t slot;

	if (k < 0)
		return;
	slot = (uint64_t)k % POISE_WET_SLOTS;
	/* Late: the output already played (or committed to) it unprocessed. */
	if (atomic_load_explicit(&c->decided[slot], memory_order_acquire) ==
	    ((uint64_t)k + 1) * 2)
		stat_add(c, POISE_STAT_FRAMES_LATE, 1);
	memcpy(&c->wet[slot * c->frame], src, (size_t)c->frame * sizeof(float));
	atomic_store_explicit(&c->wet_id[slot], (uint64_t)k + 1, memory_order_release);
}

void poise_core_stop(poise_core *c)
{
	atomic_store_explicit(&c->stopping, 1, memory_order_release);
	if (c->sem_ok)
		sem_post(&c->sem);
}

void poise_core_get_stats(poise_core *c, uint64_t *out, uint32_t n)
{
	uint32_t i;

	for (i = 0; i < n && i < POISE_STAT_COUNT; i++)
		out[i] = atomic_load_explicit(&c->stats[i], memory_order_relaxed);
}

uint64_t poise_core_delay(poise_core *c)
{
	return atomic_load_explicit(&c->delay, memory_order_relaxed);
}

uint32_t poise_core_frame(poise_core *c)
{
	return c->frame;
}

uint32_t poise_core_stat_count(void)
{
	return POISE_STAT_COUNT;
}

int poise_core_cycle_mono(poise_core *c, const float *in, uint32_t n_in,
		float *out, uint32_t n_out)
{
	const float *ip[1] = { in };
	float *op[1] = { out };

	if (in != NULL)
		poise_core_input(c, ip, 1, n_in);
	return poise_core_output(c, op, 1, n_out);
}
