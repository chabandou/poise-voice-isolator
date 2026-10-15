/*
 * Fixed-delay exchange between the realtime audio thread (PipeWire's on
 * Linux, poise_wasapi's on Windows) and the Python inference worker.
 *
 * The realtime side writes every captured sample into a history buffer
 * and, in the same cycle, outputs the sample from exactly `delay`
 * samples earlier: processed (wet) when the worker delivered that frame
 * in time, the unprocessed input (dry, aligned to the engine's own
 * delay) when it did not. The delay never changes because of a late
 * worker, so audio cannot drift out of sync; a late frame is a short
 * unprocessed moment instead.
 *
 * Positions are absolute sample counts at 48 kHz. Frame k covers input
 * samples [k*frame, (k+1)*frame). Single realtime thread, single worker
 * thread; no locks.
 */
#ifndef POISE_CORE_H
#define POISE_CORE_H

#include <stdint.h>

/* Input history: 2.7 s at 48 kHz (power of two). */
#define POISE_HIST_SIZE (1u << 17)
/* Processed frames kept; far more than the delay ever spans. */
#define POISE_WET_SLOTS 256u
/* Most planes (channels) a cycle may carry. */
#define POISE_MAX_PLANES 16u

/* Counters, read with poise_core_get_stats() in this order. */
enum poise_stat {
	POISE_STAT_CYCLES,         /* output cycles run */
	POISE_STAT_IN_POS,         /* samples captured */
	POISE_STAT_OUT_POS,        /* samples output */
	POISE_STAT_DELAY,          /* fixed delay in samples (excl. engine) */
	POISE_STAT_QUANTUM,        /* samples in the last cycle */
	POISE_STAT_QUANTUM_MAX,    /* largest cycle seen */
	POISE_STAT_FRAMES_WET,     /* frames played processed */
	POISE_STAT_FRAMES_DRY,     /* audible frames played unprocessed (worker late) */
	POISE_STAT_FRAMES_SKIPPED, /* frames the worker never processed */
	POISE_STAT_FRAMES_LATE,    /* frames delivered after playing unprocessed */
	POISE_STAT_DELAY_CHANGES,  /* delay raised for a larger cycle with sound */
	POISE_STAT_RESYNCS,        /* input ran ahead; output jumped to it */
	POISE_STAT_INPUT_GAPS,     /* input fell short; gap filled with silence */
	POISE_STAT_TRIGGER_FAILS,  /* capture cycles the output could not take */
	POISE_STAT_COUNT
};

typedef struct poise_core poise_core;

/*
 * frame:     engine frame size (samples)
 * dry_delay: the engine's own input-to-output delay (samples), so the
 *            dry fallback lines up with processed audio
 * quantum:   largest cycle (samples) the delay is sized for; larger
 *            cycles raise the delay (counted in DELAY_CHANGES)
 * margin:    extra time the worker gets per frame (samples)
 * fade:      crossfade length between wet and dry (samples)
 * dry_gain:  gain on the dry fallback (matches the wet path's makeup gain)
 */
poise_core *poise_core_new(uint32_t frame, uint32_t dry_delay,
		uint32_t quantum, uint32_t margin, uint32_t fade, float dry_gain);
void poise_core_free(poise_core *c);

/* Realtime thread. Input planes are averaged to mono; output planes all
 * get the same mono signal. poise_core_output() returns 1 when the delay
 * changed in this cycle. */
void poise_core_input(poise_core *c, const float *const *planes,
		uint32_t n_planes, uint32_t n);
int poise_core_output(poise_core *c, float *const *planes,
		uint32_t n_planes, uint32_t n);
void poise_core_count_trigger_fail(poise_core *c);

/* Worker thread. wait_frame copies the next frame to process into dst
 * and returns its index; -1 on timeout (timeout_ms 0 = poll), -2 once
 * stopped. put_frame hands back the processed frame. */
int64_t poise_core_wait_frame(poise_core *c, float *dst, int timeout_ms);
void poise_core_put_frame(poise_core *c, int64_t k, const float *src);

/* Any thread. */
void poise_core_stop(poise_core *c);
void poise_core_get_stats(poise_core *c, uint64_t *out, uint32_t n);
uint64_t poise_core_delay(poise_core *c);
uint32_t poise_core_frame(poise_core *c);
uint32_t poise_core_stat_count(void);

/* Tests: one mono input + output cycle. */
int poise_core_cycle_mono(poise_core *c, const float *in, uint32_t n_in,
		float *out, uint32_t n_out);

#endif
