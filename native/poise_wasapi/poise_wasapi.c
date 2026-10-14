/*
 * Poise's Windows audio path, the counterpart of poise_pw.c.
 *
 * Apps play into VB-Cable; Poise captures CABLE Output and plays to the
 * speakers. Those are two devices on two clocks, so unlike the PipeWire
 * node there is no shared cycle to run in. One MMCSS thread serves both
 * WASAPI streams (event-driven, shared mode, 48 kHz float; the audio
 * engine converts from whatever the devices run at):
 *
 *   capture event: every packet goes into the bridge FIFO (once the
 *                  capture's timing is chosen at the start; see
 *                  "Capture timing").
 *   render event:  the speakers' free space is filled, in cycles of at
 *                  most one render period: the bridge resamples exactly
 *                  that many samples out of the FIFO, and poise_core
 *                  takes them in and gives the output, as on PipeWire.
 *
 * The bridge keeps just enough input in its FIFO by adjusting the
 * resampling ratio slowly (a PI loop with a time constant of ~5 s, at
 * most 0.5%), so a cable clock that runs faster or slower than the
 * speakers' changes neither the delay nor anything audible, and capture
 * packets that arrive late or bunched up raise the level instead of
 * leaving gaps. A Python thread that stalls changes nothing here either:
 * poise_core plays the frames it missed unprocessed and the delay stays
 * put.
 *
 * The thread never waits on Python; inference runs in a Python thread
 * through poise_core_wait_frame()/poise_core_put_frame().
 */
#define COBJMACROS
#define WIN32_LEAN_AND_MEAN
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0A00
#endif
#include <windows.h>
#include <mmdeviceapi.h>
#include <audioclient.h>
#include <mmreg.h>

#include <math.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "poise_wasapi.h"

#define POISE_RATE 48000u

#ifndef AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM
#define AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM 0x80000000
#endif
#ifndef AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY
#define AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY 0x08000000
#endif
#ifndef SPEAKER_FRONT_LEFT
#define SPEAKER_FRONT_LEFT 0x1
#define SPEAKER_FRONT_RIGHT 0x2
#endif

/* Defined here rather than taken from libuuid, which not every mingw
 * toolchain ships complete. */
static const CLSID CLSID_MMDeviceEnumerator_ = {0xBCDE0395, 0xE52F, 0x467C,
	{0x8E, 0x3D, 0xC4, 0x57, 0x92, 0x91, 0x69, 0x2E}};
static const IID IID_IMMDeviceEnumerator_ = {0xA95664D2, 0x9614, 0x4F35,
	{0xA7, 0x46, 0xDE, 0x8D, 0xB6, 0x36, 0x17, 0xE6}};
static const IID IID_IAudioClient_ = {0x1CB9AD4C, 0xDBFA, 0x4C32,
	{0xB1, 0x78, 0xC2, 0xF5, 0x68, 0xA7, 0x03, 0xB2}};
static const IID IID_IAudioCaptureClient_ = {0xC8ADBD64, 0xE71E, 0x48A0,
	{0xA4, 0xDE, 0x18, 0x5C, 0x39, 0x5C, 0xD3, 0x17}};
static const IID IID_IAudioRenderClient_ = {0xF294ACFC, 0x3146, 0x4483,
	{0xA7, 0xBF, 0xAD, 0xDC, 0xA7, 0xC2, 0x60, 0xE2}};
static const IID IID_IAudioClock_ = {0xCD63314F, 0x3FBA, 0x4A1B,
	{0x81, 0x2C, 0xEF, 0x96, 0x35, 0x87, 0x28, 0xE7}};
static const GUID SUBTYPE_IEEE_FLOAT_ = {0x00000003, 0x0000, 0x0010,
	{0x80, 0x00, 0x00, 0xAA, 0x00, 0x38, 0x9B, 0x71}};
static const PROPERTYKEY PKEY_Device_FriendlyName_ = {{0xA45C254E, 0xDF1C,
	0x4EFD, {0x80, 0x20, 0x67, 0xD1, 0x46, 0xA8, 0x50, 0xE0}}, 14};

/* ==== clock bridge ===================================================== */

/* FIFO: 0.68 s at 48 kHz, stored twice so any run of taps is contiguous. */
#define BRIDGE_SIZE (1u << 15)
#define BRIDGE_MASK (BRIDGE_SIZE - 1u)
/* Windowed-sinc interpolation: 64 taps (lookahead 32 samples, 0.67 ms),
 * 256 phases with linear interpolation between them. */
#define TAPS_HALF 32
#define TAPS (2 * TAPS_HALF)
#define PHASES 256
/* Passband edge as a fraction of Nyquist, and the Kaiser window's beta. */
#define CUTOFF 0.92
#define KAISER_BETA 8.6
/*
 * Rate control holds the FIFO's fill, averaged over time, at a target.
 * The time average does not depend on when packets arrive relative to
 * reads, nor on how they are bunched (an estimate that extrapolated from
 * the last packet read high when VB-Cable delivered in bursts, and the
 * loop drained the FIFO into constant underruns). A target of one read
 * plus the resampler's lookahead plus `safety` covers every read at any
 * phase, with packets up to `safety` late.
 *
 * The target adapts to the capture timing through the headroom: input
 * left beyond what a read needed, worst per window, as it would have
 * been with the fill at target (so it describes the capture timing, not
 * where the fill happens to be). When it runs thin the target rises at
 * once (by at most 10 ms per window), and once a whole HOLD_WINDOWS
 * stretch had headroom to spare it comes back down slowly, never below
 * where it started.
 *
 * A capture stall is not lateness that headroom could cover: reads come
 * up short one after another until the shortfall passes STALL_SAMPLES.
 * Such a window buys no headroom, and a rise made when the stall began
 * (it looked like a late packet then) is taken back, so a stall costs
 * the silence it leaves and nothing else: no delay added, nothing to
 * release. (Raising by 10 ms per window, a 150 ms stall across a window
 * boundary cost 20 ms for ~50 s, and stalls every half minute would
 * ratchet the delay up.) Stall windows still count in the hold, so the
 * target does not come down right after one.
 *
 * PI loop, critically damped: time constant 4 s while locking on, then
 * 10 s; at most 0.5%. Tracking a 2000 ppm clock difference costs a few
 * ms of fill while locking on.
 */
#define WINDOW_SEC 0.5
#define HOLD_WINDOWS 20
#define LOCK_SEC 15.0
#define KP 0.2
#define LOCK_KP 0.5
#define MAX_CORRECTION 0.005
/* Largest fill error the loop acts on (s): one rough window cannot swing
 * the rate far. */
#define MAX_ERROR_SEC 0.005
/* Target changes (samples): largest rise per window, release per window,
 * and the spare headroom kept before releasing. */
#define MAX_RISE (POISE_RATE / 100)
#define RELEASE_STEP (POISE_RATE / 4000)
#define RELEASE_SPARE (POISE_RATE / 500)
/* Fill above target dropped at once rather than resampled away (e.g. the
 * backlog of a capture stall), in samples. */
#define RESYNC_SAMPLES (POISE_RATE / 25)
/* Shortfall in a row (samples) beyond which capture stalled rather than
 * ran late: more than packets 15 ms late in a rough stretch ever add up
 * to, less than a dropout anyone would call a hiccup. */
#define STALL_SAMPLES (POISE_RATE / 20)
/* Capture runs this long before reading starts (s): its first packets
 * tend to come bunched up, and the read position is set from them. */
#define START_SETTLE_SEC 0.05

struct poise_bridge {
	float buf[2 * BRIDGE_SIZE];
	int64_t wpos;          /* samples written */
	int64_t ipos;          /* read position: integer part ... */
	double frac;           /* ... and fraction */
	double ratio;          /* input samples per output sample */
	uint32_t start_level;  /* fill when reading starts; lowest target */
	uint32_t safety;       /* headroom kept for late packets */
	double target;         /* time-averaged fill the rate control holds */
	int started;
	double t_first;        /* time of the first capture packet */
	double t_start;        /* time reading started */
	double t_window;       /* start of the current window */
	double t_last;         /* last time the fill was integrated */
	double win_area;       /* fill integrated over this window */
	int64_t win_min;       /* worst headroom in this window */
	uint32_t win_reads;
	uint32_t last_read;    /* samples the last read produced */
	double hold[HOLD_WINDOWS];  /* headroom of recent windows, at target */
	uint32_t n_hold, hold_pos;
	uint32_t episode;      /* runs of short reads so far */
	int64_t ep_short;      /* shortfall of the current run (0: none) */
	int win_stall;         /* a run in this window passed STALL_SAMPLES */
	uint32_t rise_episode; /* run in progress at the last rise (0: none) */
	double rise;           /* what that rise added */
	double iterm;          /* integral part of the rate correction */
	uint64_t stats[POISE_BRIDGE_STAT_COUNT];
};

static float g_taps[PHASES + 1][TAPS];
static INIT_ONCE g_taps_once = INIT_ONCE_STATIC_INIT;

static double bessel_i0(double x)
{
	double sum = 1.0, term = 1.0;
	int k;

	for (k = 1; k < 50; k++) {
		term *= (x / (2.0 * k)) * (x / (2.0 * k));
		sum += term;
		if (term < sum * 1e-12)
			break;
	}
	return sum;
}

/* Tap j of phase p weighs input sample (i - TAPS_HALF + 1 + j) for an
 * output at position i + p / PHASES. Each phase sums to 1. */
static BOOL CALLBACK init_taps(PINIT_ONCE once, void *param, void **ctx)
{
	const double pi = 3.14159265358979323846;
	double i0b = bessel_i0(KAISER_BETA);
	int p, j;

	for (p = 0; p <= PHASES; p++) {
		double sum = 0.0, h[TAPS];

		for (j = 0; j < TAPS; j++) {
			double t = (double)(j - TAPS_HALF + 1) - (double)p / PHASES;
			double u = t / TAPS_HALF;
			double x = CUTOFF * t;
			double sinc = fabs(x) < 1e-9 ? 1.0 : sin(pi * x) / (pi * x);
			double win = fabs(u) >= 1.0 ? 0.0 :
				bessel_i0(KAISER_BETA * sqrt(1.0 - u * u)) / i0b;
			h[j] = CUTOFF * sinc * win;
			sum += h[j];
		}
		for (j = 0; j < TAPS; j++)
			g_taps[p][j] = (float)(h[j] / sum);
	}
	return TRUE;
}

poise_bridge *poise_bridge_new(uint32_t start_level, uint32_t safety)
{
	poise_bridge *b;

	if (start_level < TAPS || start_level > BRIDGE_SIZE / 4 ||
	    safety > BRIDGE_SIZE / 4)
		return NULL;
	InitOnceExecuteOnce(&g_taps_once, init_taps, NULL, NULL);
	b = calloc(1, sizeof(*b));
	if (b == NULL)
		return NULL;
	b->ratio = 1.0;
	b->start_level = start_level;
	b->safety = safety;
	b->target = start_level;
	b->win_min = INT64_MAX;
	b->stats[POISE_BRIDGE_SAFETY] = safety;
	b->stats[POISE_BRIDGE_TARGET] = start_level;
	b->stats[POISE_BRIDGE_LEVEL] = start_level;
	b->stats[POISE_BRIDGE_HEADROOM] = safety;
	return b;
}

void poise_bridge_free(poise_bridge *b)
{
	free(b);
}

uint32_t poise_bridge_delay(void)
{
	return TAPS_HALF;
}

static void bridge_write(poise_bridge *b, float v)
{
	uint32_t i = (uint32_t)b->wpos & BRIDGE_MASK;

	b->buf[i] = v;
	b->buf[i + BRIDGE_SIZE] = v;
	b->wpos++;
}

/* Input still unread: from the read position to the last sample written. */
static int64_t bridge_fill(poise_bridge *b)
{
	return b->wpos - b->ipos;
}

/* Add the fill since the last push or update to the window's integral. */
static void integrate(poise_bridge *b, double now)
{
	if (b->started && now > b->t_last)
		b->win_area += ((double)bridge_fill(b) - b->frac) * (now - b->t_last);
	if (now > b->t_last)
		b->t_last = now;
}

void poise_bridge_push(poise_bridge *b, const float *in, uint32_t n, double now)
{
	uint32_t i;

	integrate(b, now);
	if (b->wpos == 0)
		b->t_first = now;
	for (i = 0; i < n; i++)
		bridge_write(b, in ? in[i] : 0.0f);
	/* Nobody reads (render stalled): keep the newest audio. */
	if (bridge_fill(b) > (int64_t)(BRIDGE_SIZE - 2 * TAPS)) {
		int64_t drop = bridge_fill(b) - b->start_level;
		b->ipos += drop;
		b->stats[POISE_BRIDGE_RESYNCS]++;
		b->stats[POISE_BRIDGE_DROPPED] += (uint64_t)drop;
	}
}

static double clamp(double v, double lim)
{
	return v > lim ? lim : (v < -lim ? -lim : v);
}

/* End of a window: adapt the target to the headroom seen, drop a backlog
 * nobody needs, and steer the rate toward the target. */
static void end_window(poise_bridge *b, double now)
{
	double dt = now - b->t_window, mean, err, corr, kp, room, held, fill;
	uint32_t i;

	if (dt <= 0.0 || b->win_reads == 0) {
		b->t_window = now;
		return;
	}
	mean = b->win_area / dt;
	room = (double)b->win_min - (mean - b->target);
	b->t_window = now;
	b->win_area = 0.0;
	b->win_min = INT64_MAX;
	b->win_reads = 0;
	b->hold[b->hold_pos] = room;
	b->hold_pos = (b->hold_pos + 1) % HOLD_WINDOWS;
	if (b->n_hold < HOLD_WINDOWS)
		b->n_hold++;
	held = room;
	for (i = 0; i < b->n_hold; i++)
		if (b->hold[i] < held)
			held = b->hold[i];

	if (b->win_stall) {
		/* A stall: nothing headroom would have covered. */
		b->win_stall = 0;
	} else if (room < b->safety / 2.0) {
		double rise = b->safety - room;

		if (rise > MAX_RISE)
			rise = MAX_RISE;
		b->target += rise;
		/* Short reads still going on: this may be a stall beginning. */
		b->rise = rise;
		b->rise_episode = b->ep_short > 0 ? b->episode : 0;
	} else if (b->n_hold == HOLD_WINDOWS &&
		   held > b->safety + RELEASE_SPARE) {
		double spare = held - (b->safety + RELEASE_SPARE);
		b->target -= spare < RELEASE_STEP ? spare : RELEASE_STEP;
		if (b->target < b->start_level)
			b->target = b->start_level;
	}
	if (b->target > BRIDGE_SIZE / 4)
		b->target = BRIDGE_SIZE / 4;

	/* A backlog far above target (capture caught up after a stall):
	 * drop it now, down to the target. Windows end just before a read,
	 * where the fill is half a read above its time average. */
	fill = (double)bridge_fill(b) - b->frac;
	if (mean > b->target + RESYNC_SAMPLES &&
	    fill > b->target + b->last_read / 2.0) {
		int64_t drop = (int64_t)(fill - b->target - b->last_read / 2.0);
		b->ipos += drop;
		mean = b->target;
		b->stats[POISE_BRIDGE_RESYNCS]++;
		b->stats[POISE_BRIDGE_DROPPED] += (uint64_t)drop;
	}

	if (dt > 1.0)
		dt = 1.0;
	kp = now - b->t_start < LOCK_SEC ? LOCK_KP : KP;
	err = clamp((mean - b->target) / POISE_RATE, MAX_ERROR_SEC);
	/* Kept as a rate, so changing gains does not jump. */
	b->iterm = clamp(b->iterm + kp * kp / 4.0 * err * dt, MAX_CORRECTION);
	corr = clamp(kp * err + b->iterm, MAX_CORRECTION);
	b->ratio = 1.0 + corr;
	b->stats[POISE_BRIDGE_TARGET] = (uint64_t)b->target;
	b->stats[POISE_BRIDGE_LEVEL] = (uint64_t)(mean > 0.0 ? mean : 0.0);
	b->stats[POISE_BRIDGE_HEADROOM] = (uint64_t)(int64_t)llround(held);
	b->stats[POISE_BRIDGE_RATE_PPB] = (uint64_t)(int64_t)llround(corr * 1e9);
}

void poise_bridge_update(poise_bridge *b, double now)
{
	if (!b->started) {
		/* Wait for the first packet, then start reading with the fill at
		 * the target plus half a read: the time average then starts out
		 * near the target whatever the packet/read phase. */
		int64_t read_size = (int64_t)b->start_level - (int64_t)b->safety -
			TAPS_HALF - 1;

		if (b->wpos == 0 || now - b->t_first < START_SETTLE_SEC)
			return;
		b->ipos = b->wpos - (int64_t)b->start_level -
			(read_size > 0 ? read_size / 2 : 0);
		b->frac = 0.0;
		b->t_start = b->t_window = b->t_last = now;
		b->started = 1;
		return;
	}
	integrate(b, now);
	if (now - b->t_window >= WINDOW_SEC)
		end_window(b, now);
}

void poise_bridge_read(poise_bridge *b, float *out, uint32_t n)
{
	int64_t need;
	uint32_t i;

	if (!b->started) {
		memset(out, 0, n * sizeof(float));
		return;
	}
	need = b->ipos + (int64_t)ceil(b->frac + n * b->ratio) + TAPS_HALF + 1;
	b->win_reads++;
	b->last_read = n;
	if (b->wpos - need < b->win_min)
		b->win_min = b->wpos - need;
	if (need > b->wpos) {
		/* Capture fell short: what is missing is silence, so the output
		 * keeps time. The late audio then lands behind it, raising the
		 * fill by the shortfall; the target rises with it, unless the
		 * shortfall keeps growing into a stall. */
		int64_t short_by = need - b->wpos;
		while (b->wpos < need)
			bridge_write(b, 0.0f);
		b->stats[POISE_BRIDGE_STARVED]++;
		b->stats[POISE_BRIDGE_INSERTED] += (uint64_t)short_by;
		if (b->ep_short == 0)
			b->episode++;
		if (b->ep_short <= STALL_SAMPLES &&
		    b->ep_short + short_by > STALL_SAMPLES) {
			b->stats[POISE_BRIDGE_STALLS]++;
			if (b->rise_episode == b->episode) {
				b->target -= b->rise;
				if (b->target < b->start_level)
					b->target = b->start_level;
				b->rise_episode = 0;
			}
		}
		b->ep_short += short_by;
		if (b->ep_short > STALL_SAMPLES)
			b->win_stall = 1;
	} else {
		b->ep_short = 0;
	}
	for (i = 0; i < n; i++) {
		double ph = b->frac * PHASES;
		int p = (int)ph;
		float w = (float)(ph - p);
		const float *src = &b->buf[(uint32_t)(b->ipos - TAPS_HALF + 1) & BRIDGE_MASK];
		const float *c0 = g_taps[p], *c1 = g_taps[p + 1];
		float a0 = 0.0f, a1 = 0.0f;
		int j;
		double step;

		for (j = 0; j < TAPS; j++) {
			a0 += c0[j] * src[j];
			a1 += c1[j] * src[j];
		}
		out[i] = a0 + w * (a1 - a0);
		b->frac += b->ratio;
		step = floor(b->frac);
		b->ipos += (int64_t)step;
		b->frac -= step;
	}
}

void poise_bridge_get_stats(poise_bridge *b, uint64_t *out, uint32_t n)
{
	uint32_t i;

	for (i = 0; i < n && i < POISE_BRIDGE_STAT_COUNT; i++)
		out[i] = b->stats[i];
}

/* ==== WASAPI =========================================================== */

/*
 * Capture timing. In shared mode the audio engine hands over CABLE
 * Output's packets at a fixed point of VB-Cable's own 10 ms cycle, the
 * same for the whole session and set when the stream starts: packets
 * arrive 10.5 to 19.5 ms after their time stamps. At either end the two
 * race: some packets miss a pass and come two at once 20 ms apart, and
 * the FIFO then holds ~8 ms more all session (7 of 8 starts with a
 * player running). Just past the lower end nothing races and packets
 * are freshest. A fresh start lands at an end more often than not;
 * stopping and starting the stream again lands somewhere else.
 *
 * So before the bridge takes any audio, each try reads STEER_PACKETS
 * packets (after STEER_SKIP) and the capture restarts until they are
 * STEER_LO..STEER_HI older than one period, none of them paired. After
 * STEER_TRIES_NEAR tries anywhere clear of the edge will do (up to
 * STEER_RELAXED_HI), and after STEER_TRIES the timing stays as it is
 * (the bridge copes with pairs, at the cost above). ~0.13 s per try
 * (the age of 10 packets is within ~0.3 ms of 20's, and a restart does
 * not bunch the first ones); each restart moves the timing ~0.3-0.8 ms
 * later, so a start at an end takes a few. Measured on VB-Cable
 * (measurements/windows-latency.md, section 10).
 */
#define STEER_PACKETS 10
#define STEER_SKIP 3
#define STEER_LO 0.0025
#define STEER_HI 0.0055
#define STEER_RELAXED_HI 0.008
#define STEER_TRIES_NEAR 6
#define STEER_TRIES 12
/* Packets this close together came in the same pass (s). */
#define STEER_PAIR_GAP 0.003

typedef HANDLE (WINAPI *av_set_fn)(LPCWSTR, LPDWORD);
typedef BOOL (WINAPI *av_revert_fn)(HANDLE);

struct stream {
	IAudioClient *client;
	IAudioCaptureClient *capture;
	IAudioRenderClient *render;
	IAudioClock *clock;   /* render only; NULL if unavailable */
	UINT64 clock_freq;
	HANDLE event;
	UINT32 period;   /* samples at 48 kHz */
	UINT32 buffer;   /* samples */
};

struct poise_wasapi {
	char capture_name[512];
	char render_name[512];
	uint32_t frame, engine_latency, margin, fade, fifo_safety, render_fill;
	float dry_gain;

	HANDLE thread;
	HANDLE ready;      /* set once the devices are open (or failed to) */
	HANDLE stop;
	poise_core *core;
	poise_bridge *bridge;
	struct stream cap, ren;
	uint32_t quantum;
	float *mono_in, *mono_out, *cap_mono;
	uint32_t cap_mono_size;
	int first_packet;
	LARGE_INTEGER qpc_freq;
	int64_t last_render_qpc;
	uint64_t written;         /* samples handed to the speakers */
	double t_diag;            /* start of the diagnostics second */
	int64_t queue_min;        /* least render queue this second (samples) */
	int64_t age_min;          /* least capture packet age this second (us) */

	/* Choosing the capture timing (see above); packets go to the
	 * bridge once steering is 0. */
	int steering;
	uint32_t steer_tries;
	uint32_t steer_seen;      /* packets read this try */
	uint32_t steer_n;         /* ... of which measured */
	uint32_t steer_pairs;
	double steer_last;        /* arrival of the previous packet (s) */
	double steer_age[STEER_PACKETS];

	_Atomic uint64_t stats[POISE_WIN_STAT_COUNT];
	_Atomic int failed;
	char error[512];
};

static inline void wstat_set(poise_wasapi *w, enum poise_win_stat s, uint64_t v)
{
	atomic_store_explicit(&w->stats[s], v, memory_order_relaxed);
}

static inline void wstat_add(poise_wasapi *w, enum poise_win_stat s, uint64_t v)
{
	atomic_fetch_add_explicit(&w->stats[s], v, memory_order_relaxed);
}

static double qpc_seconds(poise_wasapi *w, int64_t *raw)
{
	LARGE_INTEGER now;

	QueryPerformanceCounter(&now);
	if (raw != NULL)
		*raw = now.QuadPart;
	return (double)now.QuadPart / (double)w->qpc_freq.QuadPart;
}

static const char *hr_name(HRESULT hr)
{
	switch ((unsigned long)hr) {
	case 0x88890004: return "the device was removed or its format changed";
	case 0x88890008: return "format not supported";
	case 0x8889000A: return "device in use (exclusive mode)";
	case 0x88890001: return "audio client not initialized";
	case 0x8889001E: return "audio service not running";
	case 0x80070005: return "access denied";
	case 0x80070490: return "device not found";
	default: return "error";
	}
}

/* Audio thread only; the flag is set after the message is written. */
static void fail(poise_wasapi *w, const char *what, HRESULT hr)
{
	if (atomic_load(&w->failed))
		return;
	snprintf(w->error, sizeof(w->error), "%s: %s (0x%08lx)", what,
			hr_name(hr), (unsigned long)hr);
	atomic_store(&w->failed, 1);
}

static void fail_msg(poise_wasapi *w, const char *msg)
{
	if (atomic_load(&w->failed))
		return;
	snprintf(w->error, sizeof(w->error), "%s", msg);
	atomic_store(&w->failed, 1);
}

static int name_matches(const wchar_t *have, const wchar_t *want, int prefix)
{
	size_t lw = wcslen(want), lh = wcslen(have);

	if (!prefix)
		return wcscmp(have, want) == 0;
	/* PortAudio may cut long names short; either side can be the cut one. */
	if (lw < 8 || lh < 8)
		return 0;
	return wcsncmp(have, want, lw < lh ? lw : lh) == 0;
}

/* Active endpoint whose friendly name is `name` (exact, else prefix);
 * NULL/"" = the default device. */
static HRESULT find_device(IMMDeviceEnumerator *en, EDataFlow flow,
		const char *name, IMMDevice **out)
{
	IMMDeviceCollection *coll = NULL;
	wchar_t want[512];
	UINT count = 0, i;
	HRESULT hr;
	int pass;

	*out = NULL;
	if (name == NULL || name[0] == '\0')
		return IMMDeviceEnumerator_GetDefaultAudioEndpoint(en, flow, eConsole, out);
	if (!MultiByteToWideChar(CP_UTF8, 0, name, -1, want, 512))
		return E_INVALIDARG;
	hr = IMMDeviceEnumerator_EnumAudioEndpoints(en, flow, DEVICE_STATE_ACTIVE, &coll);
	if (FAILED(hr))
		return hr;
	IMMDeviceCollection_GetCount(coll, &count);
	for (pass = 0; pass < 2 && *out == NULL; pass++) {
		for (i = 0; i < count && *out == NULL; i++) {
			IMMDevice *dev = NULL;
			IPropertyStore *props = NULL;
			PROPVARIANT pv;

			if (FAILED(IMMDeviceCollection_Item(coll, i, &dev)))
				continue;
			PropVariantInit(&pv);
			if (SUCCEEDED(IMMDevice_OpenPropertyStore(dev, STGM_READ, &props)) &&
			    SUCCEEDED(IPropertyStore_GetValue(props, &PKEY_Device_FriendlyName_, &pv)) &&
			    pv.vt == VT_LPWSTR && name_matches(pv.pwszVal, want, pass)) {
				*out = dev;
				dev = NULL;
			}
			PropVariantClear(&pv);
			if (props)
				IPropertyStore_Release(props);
			if (dev)
				IMMDevice_Release(dev);
		}
	}
	IMMDeviceCollection_Release(coll);
	return *out ? S_OK : HRESULT_FROM_WIN32(ERROR_NOT_FOUND);
}

static UINT32 hns_to_samples(REFERENCE_TIME t)
{
	return (UINT32)((t * (REFERENCE_TIME)POISE_RATE + 5000000) / 10000000);
}

/* Shared-mode, event-driven, 48 kHz float stereo (the engine converts). */
static HRESULT open_stream(poise_wasapi *w, IMMDeviceEnumerator *en,
		EDataFlow flow, const char *name, REFERENCE_TIME buffer,
		struct stream *s, const char **what)
{
	WAVEFORMATEXTENSIBLE wfx;
	REFERENCE_TIME def_period = 0, min_period = 0;
	IMMDevice *dev = NULL;
	HRESULT hr;

	*what = flow == eCapture ? "capture device" : "output device";
	hr = find_device(en, flow, name, &dev);
	if (FAILED(hr))
		return hr;
	hr = IMMDevice_Activate(dev, &IID_IAudioClient_, CLSCTX_ALL, NULL,
			(void **)&s->client);
	IMMDevice_Release(dev);
	if (FAILED(hr))
		return hr;

	memset(&wfx, 0, sizeof(wfx));
	wfx.Format.wFormatTag = WAVE_FORMAT_EXTENSIBLE;
	wfx.Format.nChannels = 2;
	wfx.Format.nSamplesPerSec = POISE_RATE;
	wfx.Format.wBitsPerSample = 32;
	wfx.Format.nBlockAlign = 8;
	wfx.Format.nAvgBytesPerSec = POISE_RATE * 8;
	wfx.Format.cbSize = sizeof(wfx) - sizeof(WAVEFORMATEX);
	wfx.Samples.wValidBitsPerSample = 32;
	wfx.dwChannelMask = SPEAKER_FRONT_LEFT | SPEAKER_FRONT_RIGHT;
	wfx.SubFormat = SUBTYPE_IEEE_FLOAT_;

	IAudioClient_GetDevicePeriod(s->client, &def_period, &min_period);
	hr = IAudioClient_Initialize(s->client, AUDCLNT_SHAREMODE_SHARED,
			AUDCLNT_STREAMFLAGS_EVENTCALLBACK |
			AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM |
			AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY,
			buffer, 0, (WAVEFORMATEX *)&wfx, NULL);
	if (FAILED(hr))
		return hr;
	s->period = hns_to_samples(def_period ? def_period : 100000);
	hr = IAudioClient_GetBufferSize(s->client, &s->buffer);
	if (FAILED(hr))
		return hr;
	s->event = CreateEventW(NULL, FALSE, FALSE, NULL);
	if (s->event == NULL)
		return HRESULT_FROM_WIN32(GetLastError());
	hr = IAudioClient_SetEventHandle(s->client, s->event);
	if (FAILED(hr))
		return hr;
	if (flow == eCapture)
		return IAudioClient_GetService(s->client, &IID_IAudioCaptureClient_,
				(void **)&s->capture);
	/* The device clock shows what the speakers still have to play,
	 * beyond our buffer (diagnostics only). */
	if (SUCCEEDED(IAudioClient_GetService(s->client, &IID_IAudioClock_,
			(void **)&s->clock)) &&
	    (FAILED(IAudioClock_GetFrequency(s->clock, &s->clock_freq)) ||
	     s->clock_freq == 0)) {
		IAudioClock_Release(s->clock);
		s->clock = NULL;
	}
	return IAudioClient_GetService(s->client, &IID_IAudioRenderClient_,
			(void **)&s->render);
}

static void close_stream(struct stream *s)
{
	if (s->client)
		IAudioClient_Stop(s->client);
	if (s->capture)
		IAudioCaptureClient_Release(s->capture);
	if (s->render)
		IAudioRenderClient_Release(s->render);
	if (s->clock)
		IAudioClock_Release(s->clock);
	if (s->client)
		IAudioClient_Release(s->client);
	if (s->event)
		CloseHandle(s->event);
	memset(s, 0, sizeof(*s));
}

static int cmp_double(const void *a, const void *b)
{
	double x = *(const double *)a, y = *(const double *)b;

	return x < y ? -1 : x > y;
}

/* A packet read while choosing the capture timing (time stamp in 100 ns
 * QPC units). */
static void steer_note(poise_wasapi *w, double now, UINT64 stamp)
{
	if (w->steer_seen++ >= STEER_SKIP) {
		if (now - w->steer_last < STEER_PAIR_GAP)
			w->steer_pairs++;
		w->steer_age[w->steer_n++] = now - (double)stamp * 1e-7;
	}
	w->steer_last = now;
}

/* A try is complete: keep this timing, or start the capture again. */
static HRESULT steer(poise_wasapi *w)
{
	double period = (double)w->cap.period / POISE_RATE;
	double hi = w->steer_tries < STEER_TRIES_NEAR ? STEER_HI : STEER_RELAXED_HI;
	double late;
	HRESULT hr;

	qsort(w->steer_age, w->steer_n, sizeof(double), cmp_double);
	late = w->steer_age[w->steer_n / 2] - period;
	/* Packets younger than a period come from a device that keeps the
	 * time itself (a microphone: ~0.2 ms, the same after any restart):
	 * nothing races, nothing to steer. */
	if ((w->steer_pairs == 0 && late < 0.0) ||
	    (w->steer_pairs == 0 && late >= STEER_LO && late <= hi) ||
	    w->steer_tries >= STEER_TRIES) {
		w->steering = 0;
		return S_OK;
	}
	hr = IAudioClient_Stop(w->cap.client);
	if (SUCCEEDED(hr))
		hr = IAudioClient_Reset(w->cap.client);
	if (SUCCEEDED(hr))
		hr = IAudioClient_Start(w->cap.client);
	if (FAILED(hr))
		return hr;
	w->steer_tries++;
	w->steer_seen = w->steer_n = w->steer_pairs = 0;
	w->first_packet = 1;
	wstat_add(w, POISE_WIN_CAPTURE_RESTARTS, 1);
	return S_OK;
}

static HRESULT drain_capture(poise_wasapi *w)
{
	for (;;) {
		BYTE *data;
		UINT32 frames, next = 0, i, done;
		DWORD flags;
		UINT64 stamp = 0;
		HRESULT hr;
		double now;

		hr = IAudioCaptureClient_GetNextPacketSize(w->cap.capture, &next);
		if (FAILED(hr))
			return hr;
		if (next == 0)
			return S_OK;
		hr = IAudioCaptureClient_GetBuffer(w->cap.capture, &data, &frames,
				&flags, NULL, &stamp);
		if (FAILED(hr))
			return hr;
		if (hr == AUDCLNT_S_BUFFER_EMPTY)
			return S_OK;
		now = qpc_seconds(w, NULL);
		if (stamp) {
			int64_t age = (int64_t)(now * 1e6) - (int64_t)(stamp / 10);
			if (age < w->age_min)
				w->age_min = age;
		}
		/* The first packet always carries the flag. */
		if ((flags & AUDCLNT_BUFFERFLAGS_DATA_DISCONTINUITY) && !w->first_packet)
			wstat_add(w, POISE_WIN_CAPTURE_GLITCHES, 1);
		w->first_packet = 0;
		if (w->steering && stamp == 0)
			w->steering = 0;   /* no time stamps: nothing to steer by */
		if (w->steering)
			steer_note(w, now, stamp);
		for (done = 0; !w->steering && done < frames; ) {
			UINT32 n = frames - done;
			const float *src = (const float *)data + 2 * done;

			if (n > w->cap_mono_size)
				n = w->cap_mono_size;
			if (flags & AUDCLNT_BUFFERFLAGS_SILENT) {
				memset(w->cap_mono, 0, n * sizeof(float));
			} else {
				for (i = 0; i < n; i++)
					w->cap_mono[i] = 0.5f * (src[2 * i] + src[2 * i + 1]);
			}
			poise_bridge_push(w->bridge, w->cap_mono, n, now);
			done += n;
		}
		hr = IAudioCaptureClient_ReleaseBuffer(w->cap.capture, frames);
		if (FAILED(hr))
			return hr;
		wstat_add(w, POISE_WIN_CAPTURE_FRAMES, frames);
		wstat_add(w, POISE_WIN_CAPTURE_PACKETS, 1);
		if (w->steering && w->steer_n == STEER_PACKETS) {
			hr = steer(w);
			if (FAILED(hr))
				return hr;
			if (w->steering)
				return S_OK;   /* started again: nothing left to read */
		}
	}
}

static void publish_bridge_stats(poise_wasapi *w)
{
	uint64_t b[POISE_BRIDGE_STAT_COUNT];

	poise_bridge_get_stats(w->bridge, b, POISE_BRIDGE_STAT_COUNT);
	wstat_set(w, POISE_WIN_FIFO_SAFETY, b[POISE_BRIDGE_SAFETY]);
	wstat_set(w, POISE_WIN_FIFO_TARGET, b[POISE_BRIDGE_TARGET]);
	wstat_set(w, POISE_WIN_FIFO_LEVEL, b[POISE_BRIDGE_LEVEL]);
	wstat_set(w, POISE_WIN_FIFO_HEADROOM, b[POISE_BRIDGE_HEADROOM]);
	wstat_set(w, POISE_WIN_FIFO_STARVED, b[POISE_BRIDGE_STARVED]);
	wstat_set(w, POISE_WIN_FIFO_INSERTED, b[POISE_BRIDGE_INSERTED]);
	wstat_set(w, POISE_WIN_FIFO_RESYNCS, b[POISE_BRIDGE_RESYNCS]);
	wstat_set(w, POISE_WIN_FIFO_DROPPED, b[POISE_BRIDGE_DROPPED]);
	wstat_set(w, POISE_WIN_RATE_PPB, b[POISE_BRIDGE_RATE_PPB]);
	wstat_set(w, POISE_WIN_FIFO_STALLS, b[POISE_BRIDGE_STALLS]);
}

/* Where the delay outside our buffers sits, once a second: what the
 * speakers have yet to play (written minus their clock's position, at
 * this moment) and how old capture packets are when read. */
static void diagnose(poise_wasapi *w, double now)
{
	UINT64 pos, qpc;

	if (w->ren.clock &&
	    SUCCEEDED(IAudioClock_GetPosition(w->ren.clock, &pos, &qpc))) {
		double played = (double)pos * POISE_RATE / (double)w->ren.clock_freq +
			(now - (double)qpc * 1e-7) * POISE_RATE;
		int64_t queue = (int64_t)w->written - (int64_t)llround(played);

		if (queue < w->queue_min)
			w->queue_min = queue;
	}
	if (now - w->t_diag < 1.0)
		return;
	if (w->queue_min != INT64_MAX)
		wstat_set(w, POISE_WIN_RENDER_QUEUE, (uint64_t)w->queue_min);
	if (w->age_min != INT64_MAX)
		wstat_set(w, POISE_WIN_CAPTURE_AGE_US, (uint64_t)w->age_min);
	w->queue_min = w->age_min = INT64_MAX;
	w->t_diag = now;
}

/* Top the speakers' buffer up to render_fill, in cycles of at most one
 * period (the core's quantum). */
static HRESULT render_cycle(poise_wasapi *w, int primed)
{
	UINT32 padding = 0, avail, done = 0, i;
	BYTE *data;
	float *out;
	HRESULT hr;
	int64_t raw;
	double now = qpc_seconds(w, &raw);

	hr = IAudioClient_GetCurrentPadding(w->ren.client, &padding);
	if (FAILED(hr))
		return hr;
	if (primed)
		diagnose(w, now);
	if (primed) {
		uint64_t gap_us = 0;

		if (w->last_render_qpc) {
			gap_us = (uint64_t)((raw - w->last_render_qpc) * 1000000 /
					w->qpc_freq.QuadPart);
			if (gap_us > atomic_load_explicit(&w->stats[POISE_WIN_RENDER_GAP_MAX_US],
					memory_order_relaxed))
				wstat_set(w, POISE_WIN_RENDER_GAP_MAX_US, gap_us);
			if (gap_us * POISE_RATE > (uint64_t)w->ren.period * 1500000u)
				wstat_add(w, POISE_WIN_RENDER_LATE, 1);
		}
		w->last_render_qpc = raw;
		if (padding == 0)
			wstat_add(w, POISE_WIN_RENDER_UNDERRUNS, 1);
		wstat_add(w, POISE_WIN_RENDER_EVENTS, 1);
	}
	if (padding >= w->render_fill)
		return S_OK;
	avail = w->render_fill - padding;
	hr = IAudioRenderClient_GetBuffer(w->ren.render, avail, &data);
	if (FAILED(hr))
		return hr;
	out = (float *)data;
	poise_bridge_update(w->bridge, now);
	while (done < avail) {
		UINT32 n = avail - done;

		if (n > w->quantum)
			n = w->quantum;
		poise_bridge_read(w->bridge, w->mono_in, n);
		poise_core_cycle_mono(w->core, w->mono_in, n, w->mono_out, n);
		for (i = 0; i < n; i++) {
			out[2 * (done + i)] = w->mono_out[i];
			out[2 * (done + i) + 1] = w->mono_out[i];
		}
		done += n;
	}
	hr = IAudioRenderClient_ReleaseBuffer(w->ren.render, avail, 0);
	if (FAILED(hr))
		return hr;
	wstat_add(w, POISE_WIN_RENDER_FRAMES, avail);
	w->written += avail;
	publish_bridge_stats(w);
	return S_OK;
}

static void set_ready(poise_wasapi *w)
{
	SetEvent(w->ready);
}

static DWORD WINAPI audio_thread(void *arg)
{
	poise_wasapi *w = arg;
	IMMDeviceEnumerator *en = NULL;
	HANDLE avrt_mod = NULL, mmcss = NULL;
	av_set_fn av_set = NULL;
	av_revert_fn av_revert = NULL;
	const char *what = "audio";
	HRESULT hr;
	DWORD task = 0;
	int com = 0;

	hr = CoInitializeEx(NULL, COINIT_MULTITHREADED);
	if (FAILED(hr)) {
		fail(w, "COM", hr);
		set_ready(w);
		return 0;
	}
	com = 1;
	hr = CoCreateInstance(&CLSID_MMDeviceEnumerator_, NULL, CLSCTX_ALL,
			&IID_IMMDeviceEnumerator_, (void **)&en);
	if (FAILED(hr)) {
		fail(w, "device enumerator", hr);
		goto out;
	}
	/* Capture: a deep buffer costs no latency (it is drained at every
	 * event) and rides out a late wake-up without losing audio. */
	hr = open_stream(w, en, eCapture, w->capture_name, 2000000, &w->cap, &what);
	if (SUCCEEDED(hr))
		hr = open_stream(w, en, eRender, w->render_name, 0, &w->ren, &what);
	IMMDeviceEnumerator_Release(en);
	if (FAILED(hr)) {
		fail(w, what, hr);
		goto out;
	}

	w->quantum = w->ren.period;
	if (w->render_fill == 0 || w->render_fill > w->ren.buffer)
		w->render_fill = w->ren.buffer;
	if (w->render_fill < w->ren.period)
		w->render_fill = w->ren.period < w->ren.buffer ? w->ren.period : w->ren.buffer;
	w->cap_mono_size = w->cap.buffer > 0 ? w->cap.buffer : 4096;
	w->cap_mono = calloc(w->cap_mono_size, sizeof(float));
	w->mono_in = calloc(w->quantum, sizeof(float));
	w->mono_out = calloc(w->quantum, sizeof(float));
	w->core = poise_core_new(w->frame, w->engine_latency, w->quantum,
			w->margin, w->fade, w->dry_gain);
	/* Fill target to start from: one cycle, the resampler's lookahead
	 * and the safety (see the rate control). */
	w->bridge = poise_bridge_new(w->quantum + TAPS_HALF + 1 + w->fifo_safety,
			w->fifo_safety);
	if (!w->cap_mono || !w->mono_in || !w->mono_out || !w->core || !w->bridge) {
		fail_msg(w, "out of memory or invalid frame/fade/safety");
		goto out;
	}
	wstat_set(w, POISE_WIN_CAPTURE_PERIOD, w->cap.period);
	wstat_set(w, POISE_WIN_CAPTURE_BUFFER, w->cap.buffer);
	wstat_set(w, POISE_WIN_RENDER_PERIOD, w->ren.period);
	wstat_set(w, POISE_WIN_RENDER_BUFFER, w->ren.buffer);
	wstat_set(w, POISE_WIN_RENDER_FILL, w->render_fill);
	publish_bridge_stats(w);

	avrt_mod = LoadLibraryW(L"avrt.dll");
	if (avrt_mod) {
		av_set = (av_set_fn)(void *)GetProcAddress(avrt_mod,
				"AvSetMmThreadCharacteristicsW");
		av_revert = (av_revert_fn)(void *)GetProcAddress(avrt_mod,
				"AvRevertMmThreadCharacteristics");
	}
	if (av_set)
		mmcss = av_set(L"Pro Audio", &task);
	if (mmcss)
		wstat_set(w, POISE_WIN_MMCSS, 1);
	else
		SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_TIME_CRITICAL);

	/* Silence queued before the start: the first events then ask for one
	 * period, like every later one. */
	w->first_packet = 1;
	w->steering = 1;
	hr = render_cycle(w, 0);
	if (SUCCEEDED(hr))
		hr = IAudioClient_Start(w->cap.client);
	if (SUCCEEDED(hr))
		hr = IAudioClient_Start(w->ren.client);
	if (FAILED(hr)) {
		fail(w, "start", hr);
		goto out;
	}
	set_ready(w);

	for (;;) {
		HANDLE waits[3] = { w->stop, w->cap.event, w->ren.event };
		DWORD r = WaitForMultipleObjects(3, waits, FALSE, 200);
		int render;

		if (r == WAIT_OBJECT_0)
			break;
		if (r == WAIT_TIMEOUT)
			wstat_add(w, POISE_WIN_WAKE_TIMEOUTS, 1);
		render = r == WAIT_OBJECT_0 + 2 || r == WAIT_TIMEOUT ||
			WaitForSingleObject(w->ren.event, 0) == WAIT_OBJECT_0;
		hr = drain_capture(w);
		if (FAILED(hr)) {
			fail(w, "capture", hr);
			break;
		}
		if (render) {
			hr = render_cycle(w, 1);
			if (FAILED(hr)) {
				fail(w, "output", hr);
				break;
			}
		}
	}

out:
	if (mmcss && av_revert)
		av_revert(mmcss);
	if (avrt_mod)
		FreeLibrary(avrt_mod);
	close_stream(&w->cap);
	close_stream(&w->ren);
	if (com)
		CoUninitialize();
	if (w->core)
		poise_core_stop(w->core);
	set_ready(w);
	return 0;
}

poise_wasapi *poise_wasapi_new(const char *capture, const char *render,
		uint32_t frame, uint32_t engine_latency, uint32_t margin,
		uint32_t fade, float dry_gain, uint32_t fifo_safety,
		uint32_t render_fill, char *err, size_t errlen)
{
	poise_wasapi *w = calloc(1, sizeof(*w));

	if (w == NULL) {
		snprintf(err, errlen, "out of memory");
		return NULL;
	}
	snprintf(w->capture_name, sizeof(w->capture_name), "%s", capture ? capture : "");
	snprintf(w->render_name, sizeof(w->render_name), "%s", render ? render : "");
	w->frame = frame;
	w->engine_latency = engine_latency;
	w->margin = margin;
	w->fade = fade;
	w->dry_gain = dry_gain;
	w->fifo_safety = fifo_safety;
	w->render_fill = render_fill;
	w->queue_min = w->age_min = INT64_MAX;
	QueryPerformanceFrequency(&w->qpc_freq);
	w->ready = CreateEventW(NULL, TRUE, FALSE, NULL);
	w->stop = CreateEventW(NULL, TRUE, FALSE, NULL);
	if (w->ready == NULL || w->stop == NULL) {
		snprintf(err, errlen, "cannot create events");
		poise_wasapi_destroy(w);
		return NULL;
	}
	w->thread = CreateThread(NULL, 0, audio_thread, w, 0, NULL);
	if (w->thread == NULL) {
		snprintf(err, errlen, "cannot start the audio thread");
		poise_wasapi_destroy(w);
		return NULL;
	}
	if (WaitForSingleObject(w->ready, 10000) != WAIT_OBJECT_0) {
		snprintf(err, errlen, "audio devices did not open within 10 s");
		poise_wasapi_destroy(w);
		return NULL;
	}
	if (atomic_load(&w->failed)) {
		snprintf(err, errlen, "%s", w->error);
		poise_wasapi_destroy(w);
		return NULL;
	}
	return w;
}

void poise_wasapi_destroy(poise_wasapi *w)
{
	if (w == NULL)
		return;
	if (w->core)
		poise_core_stop(w->core);
	if (w->thread) {
		SetEvent(w->stop);
		WaitForSingleObject(w->thread, INFINITE);
		CloseHandle(w->thread);
	}
	if (w->ready)
		CloseHandle(w->ready);
	if (w->stop)
		CloseHandle(w->stop);
	poise_core_free(w->core);
	poise_bridge_free(w->bridge);
	free(w->cap_mono);
	free(w->mono_in);
	free(w->mono_out);
	free(w);
}

poise_core *poise_wasapi_core(poise_wasapi *w)
{
	return w->core;
}

int poise_wasapi_status(poise_wasapi *w, char *err, size_t errlen)
{
	if (!atomic_load(&w->failed))
		return 0;
	snprintf(err, errlen, "%s", w->error);
	return 1;
}

void poise_wasapi_get_stats(poise_wasapi *w, uint64_t *out, uint32_t n)
{
	uint32_t i;

	for (i = 0; i < n && i < POISE_WIN_STAT_COUNT; i++)
		out[i] = atomic_load_explicit(&w->stats[i], memory_order_relaxed);
}

uint32_t poise_wasapi_stat_count(void)
{
	return POISE_WIN_STAT_COUNT;
}

uint32_t poise_wasapi_io_latency(poise_wasapi *w)
{
	return (uint32_t)(atomic_load_explicit(&w->stats[POISE_WIN_FIFO_LEVEL],
			memory_order_relaxed) + w->render_fill);
}
