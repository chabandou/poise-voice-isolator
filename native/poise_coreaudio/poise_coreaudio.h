/*
 * Poise's macOS audio path: a global Core Audio process tap feeding poise_core,
 * whose output plays back through the same (private aggregate) device. The
 * counterpart of poise_wasapi.h; see poise_coreaudio.m for the model and the
 * plan's contracts C1-C4.
 *
 * No Objective-C types here: every entry point is callable from ctypes with a
 * stable signature (backends/coreaudio_node.py binds poise_ca_*, and the
 * poise_core_* of native/core/poise_core.h, from the same library).
 */
#ifndef POISE_COREAUDIO_H
#define POISE_COREAUDIO_H

#include <stddef.h>
#include <stdint.h>

#include "poise_core.h"

/* The rate every stream is created at unless the caller asks for another one
 * (plan C2: 48 kHz or refuse - the node refuses rather than running the 48 kHz
 * engine on 44.1 kHz buffers). */
#define POISE_COREAUDIO_RATE 48000u
#define POISE_COREAUDIO_CHANNELS 2u

/* Counters, read with poise_ca_get_stats() in this order. Signed values are
 * stored as two's complement. FRAMES_*, DELAY_CHANGES, RESYNCS, INPUT_GAPS,
 * QUANTUM_MAX and DELAY_SAMPLES are the core's own counters, copied into this
 * snapshot so a caller needs one read. */
enum poise_ca_stat {
	POISE_CA_CALLBACKS,      /* IOProc calls */
	POISE_CA_INPUT_FRAMES,   /* frames the tap delivered */
	POISE_CA_OUTPUT_FRAMES,  /* frames written to the aggregate's output */
	POISE_CA_FRAMES_WET,     /* frames played processed */
	POISE_CA_FRAMES_DRY,     /* audible frames played unprocessed (worker late) */
	POISE_CA_FRAMES_SKIPPED, /* frames the worker never processed */
	POISE_CA_FRAMES_LATE,    /* frames delivered after playing unprocessed */
	POISE_CA_DELAY_CHANGES,  /* delay raised for a larger cycle with sound */
	POISE_CA_RESYNCS,        /* input ran ahead; output jumped to it */
	POISE_CA_INPUT_GAPS,     /* input fell short; gap filled with silence */
	POISE_CA_QUANTUM_MAX,    /* largest cycle seen (frames) */
	POISE_CA_DELAY_SAMPLES,  /* fixed delay the core adds (samples) */
	POISE_CA_DROPPED,        /* frames that never reached the core */
	POISE_CA_OVERLOADS,      /* callbacks whose output could not be filled */
	POISE_CA_QUIET_FRAMES,   /* captured frames below the silence floor (C2b) */
	POISE_CA_SAW_SIGNAL,     /* 1 once captured audio carried sound (C2b) */
	POISE_CA_DRIFT_SAMPLES,  /* tap frames minus output frames (C3, signed) */
	POISE_CA_TIME_DELTA_MIN, /* output minus tap time stamp (C3, signed) */
	POISE_CA_TIME_DELTA_MAX,
	POISE_CA_RT_POLICY,      /* 1 if THREAD_TIME_CONSTRAINT_POLICY took */
	POISE_CA_RESTARTS,       /* aggregate rebuilds after a device change (C4, T5) */
	POISE_CA_TAP_ALIVE,      /* 1 while the tap is alive and delivering (C4, T5) */
	POISE_CA_STAT_COUNT
};

typedef struct poise_ca poise_ca;

/*
 * Create the tap and the private aggregate, create poise_core and start the
 * IOProc. Created running: until a worker calls poise_core_wait_frame() the
 * output is the unprocessed input, delayed like processed audio would be
 * (frames_dry stays 0 until a worker is active).
 *
 * output_device: output device name or UID substring (UTF-8); NULL or "" =
 *              the default output device. Bluetooth/AirPlay are accepted as
 *              far as the HAL accepts them; a refusal is reported by name.
 * frame, engine_latency, quantum, margin, fade, dry_gain: see poise_core.h;
 *              quantum is the expected callback cycle, and a larger one raises
 *              the delay (counted in DELAY_CHANGES).
 * rate:        nominal rate of every stream (0 = POISE_COREAUDIO_RATE). A
 *              device the HAL cannot give that rate is refused with its name
 *              and its real rate (C2).
 * tap_mute:    1 = CATapMutedWhenTapped, which is the shipping behaviour: the
 *              tap silences every app while it is read, so stopping or
 *              destroying the node is what restores the Mac's audio (C1).
 *              0 = leave the app audio unmuted (diagnostics only).
 *
 * Returns NULL with a message in err on failure.
 */
poise_ca *poise_ca_new(const char *output_device, uint32_t frame,
		uint32_t engine_latency, uint32_t quantum, uint32_t margin,
		uint32_t fade, float dry_gain, uint32_t rate, int tap_mute,
		char *err, size_t errlen);

/* Stop the device, destroy the IOProc, the aggregate and the tap (in that
 * order: this is what unmutes the Mac), stop the watchdog and free the core.
 *
 * Call it ONCE per handle (NULL is accepted; a second call with the same
 * pointer is a double free). The inference thread must already have returned
 * from poise_core_wait_frame() -- call poise_core_stop() and join it first:
 * this cannot join a thread it does not own, and on macOS the free path also
 * destroys the Mach semaphore a parked waiter would be sitting on.
 * poise_ca_teardown() is the idempotent one; callers that need "close twice"
 * should NULL their own handle after this, as WasapiNode.close() does. */
void poise_ca_destroy(poise_ca *n);

/* The core, for the inference thread (delay_core.CoreOps binds poise_core_*). */
poise_core *poise_ca_core(poise_ca *n);
uint32_t poise_ca_frame(poise_ca *n);

/* The core's fixed delay (samples, excluding the engine's own delay). */
uint64_t poise_ca_delay_samples(poise_ca *n);
/* The device side: samples between a captured sample entering the aggregate
 * and leaving for the speakers, from the IOProc's own time stamps (about
 * 1147 samples = 23.9 ms on the built-in output). Total added delay is this
 * plus poise_ca_delay_samples() plus the engine's own. 0 until measured. */
uint64_t poise_ca_io_latency_samples(poise_ca *n);

/* 0 while running; 1 with a message in err once the node stopped itself. The
 * 250 ms watchdog (C1) is the only source today: it destroys the tap, which
 * restores the Mac's audio, and reports that here. */
int poise_ca_status(poise_ca *n, char *err, size_t errlen);

/* Snapshot of the counters above: n < POISE_CA_STAT_COUNT is fine. */
void poise_ca_get_stats(poise_ca *n, uint64_t *out, uint32_t n_stats);
uint32_t poise_ca_stat_count(void);

#ifdef POISE_CA_CLI
/* The standalone spike harness (make -C native/poise_coreaudio cli), not part
 * of the library: device listing and one line per output device. */
void poise_ca_list_devices(void);
#endif

#endif /* POISE_COREAUDIO_H */
