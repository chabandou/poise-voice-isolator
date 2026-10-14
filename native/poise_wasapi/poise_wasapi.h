/*
 * Poise's Windows audio path: CABLE Output -> poise_core -> speakers.
 * See poise_wasapi.c for the model.
 */
#ifndef POISE_WASAPI_H
#define POISE_WASAPI_H

#include <stddef.h>
#include <stdint.h>

#include "../poise_pw/poise_core.h"

/* Counters, read with poise_wasapi_get_stats() in this order. Signed
 * values are stored as two's complement. */
enum poise_win_stat {
	POISE_WIN_CAPTURE_FRAMES,   /* samples captured */
	POISE_WIN_CAPTURE_PACKETS,  /* capture packets read */
	POISE_WIN_CAPTURE_GLITCHES, /* packets WASAPI marked discontinuous (capture overflow) */
	POISE_WIN_RENDER_FRAMES,    /* samples played */
	POISE_WIN_RENDER_EVENTS,    /* render events served */
	POISE_WIN_RENDER_UNDERRUNS, /* render buffer found empty: the speakers played a gap */
	POISE_WIN_RENDER_LATE,      /* render events more than half a period late */
	POISE_WIN_RENDER_GAP_MAX_US,/* longest time between render events (us) */
	POISE_WIN_WAKE_TIMEOUTS,    /* waits that ended with no event from either device */
	POISE_WIN_FIFO_SAFETY,      /* headroom kept for late packets (samples) */
	POISE_WIN_FIFO_TARGET,      /* fill the rate control holds (samples; adapts) */
	POISE_WIN_FIFO_LEVEL,       /* bridge fill, time average over the last window */
	POISE_WIN_FIFO_HEADROOM,    /* worst headroom of the last 10 s (samples, signed) */
	POISE_WIN_FIFO_STARVED,     /* capture fell short of a render cycle: silence inserted */
	POISE_WIN_FIFO_INSERTED,    /* samples of silence inserted */
	POISE_WIN_FIFO_RESYNCS,     /* capture ran far ahead: excess dropped */
	POISE_WIN_FIFO_DROPPED,     /* samples dropped */
	POISE_WIN_RATE_PPB,         /* resampling rate correction (parts per billion, signed) */
	POISE_WIN_CAPTURE_PERIOD,   /* device periods and buffers (samples at 48 kHz) */
	POISE_WIN_CAPTURE_BUFFER,
	POISE_WIN_RENDER_PERIOD,
	POISE_WIN_RENDER_BUFFER,
	POISE_WIN_RENDER_FILL,      /* audio kept queued for the speakers (samples) */
	POISE_WIN_MMCSS,            /* 1 if the thread got MMCSS "Pro Audio" priority */
	POISE_WIN_FIFO_STALLS,      /* capture stalled (short 50 ms in a row): no headroom bought */
	POISE_WIN_RENDER_QUEUE,     /* written but not yet played by the speakers, by their clock
	                             * (samples; least over the last second) */
	POISE_WIN_CAPTURE_AGE_US,   /* age of capture packets when read, from their time stamps
	                             * (us; least over the last second) */
	POISE_WIN_CAPTURE_RESTARTS, /* capture restarts at the start to get clear of the
	                             * cable's timer (see "capture timing") */
	POISE_WIN_STAT_COUNT
};

/* Bridge counters (poise_bridge_get_stats), a subset of the above. */
enum poise_bridge_stat {
	POISE_BRIDGE_SAFETY,
	POISE_BRIDGE_TARGET,
	POISE_BRIDGE_LEVEL,
	POISE_BRIDGE_HEADROOM,
	POISE_BRIDGE_STARVED,
	POISE_BRIDGE_INSERTED,
	POISE_BRIDGE_RESYNCS,
	POISE_BRIDGE_DROPPED,
	POISE_BRIDGE_RATE_PPB,
	POISE_BRIDGE_STALLS,
	POISE_BRIDGE_STAT_COUNT
};

typedef struct poise_wasapi poise_wasapi;
typedef struct poise_bridge poise_bridge;

/*
 * Open both devices and start the audio thread.
 *
 * capture/render: endpoint friendly names (UTF-8) as PortAudio lists
 *              them, e.g. "CABLE Output (VB-Audio Virtual Cable)";
 *              NULL or "" = the default device.
 * frame, engine_latency, margin, fade, dry_gain: see poise_core.h; the
 *              core's quantum is the render period.
 * fifo_safety: headroom the bridge keeps at worst (samples): the FIFO
 *              holds whatever the capture timing needs plus this.
 * render_fill: audio kept queued in the render buffer (samples);
 *              0 = the whole buffer.
 * Returns NULL with a message in err on failure.
 */
poise_wasapi *poise_wasapi_new(const char *capture, const char *render,
		uint32_t frame, uint32_t engine_latency, uint32_t margin,
		uint32_t fade, float dry_gain, uint32_t fifo_safety,
		uint32_t render_fill, char *err, size_t errlen);
void poise_wasapi_destroy(poise_wasapi *w);
poise_core *poise_wasapi_core(poise_wasapi *w);
/* 0 while running; 1 with a message in err once the audio thread failed. */
int poise_wasapi_status(poise_wasapi *w, char *err, size_t errlen);
void poise_wasapi_get_stats(poise_wasapi *w, uint64_t *out, uint32_t n);
uint32_t poise_wasapi_stat_count(void);
/* Samples between a sample entering the bridge and leaving the speakers'
 * buffer, excluding the core's delay and the engine's (current value:
 * the bridge adapts its level to the capture timing). */
uint32_t poise_wasapi_io_latency(poise_wasapi *w);

/* The clock bridge alone, driven by hand (tests). Times in seconds.
 * start_level: fill when reading starts; safety: see fifo_safety. */
poise_bridge *poise_bridge_new(uint32_t start_level, uint32_t safety);
void poise_bridge_free(poise_bridge *b);
void poise_bridge_push(poise_bridge *b, const float *in, uint32_t n, double now);
void poise_bridge_update(poise_bridge *b, double now);
void poise_bridge_read(poise_bridge *b, float *out, uint32_t n);
void poise_bridge_get_stats(poise_bridge *b, uint64_t *out, uint32_t n);
uint32_t poise_bridge_delay(void);

#endif
