/*
 * Poise's macOS audio path: a global Core Audio process tap feeding poise_core,
 * whose output plays back through the same (private aggregate) device.
 * See poise_coreaudio.m for the model.
 *
 * This is the T3 feasibility spike: it captures, optionally passes through, and
 * counts. The shipping node (T4) grows poise_core into it.
 */
#ifndef POISE_COREAUDIO_H
#define POISE_COREAUDIO_H

#include <stddef.h>
#include <stdint.h>

/* The rate every stream is created at (plan C2: 48 kHz or refuse). */
#define POISE_COREAUDIO_RATE 48000u
#define POISE_COREAUDIO_CHANNELS 2u

/* Counters, read as a snapshot after the session stopped. */
struct poise_mac_counters {
	uint64_t input_frames;  /* frames the tap delivered */
	uint64_t output_frames; /* frames the aggregate asked the IOProc to fill */
	uint64_t callbacks;     /* IOProc calls */
	uint64_t quantum_min;   /* fewest frames in one callback */
	uint64_t quantum_max;   /* most frames in one callback */
	uint64_t dropped_frames;/* frames the capture ring could not hold */
	uint64_t overloads;     /* callbacks where the input buffer was short */
	int rt_policy_set;      /* THREAD_TIME_CONSTRAINT_POLICY took */
};

enum poise_mac_sample_format {
	POISE_MAC_F32, /* 32-bit float WAV (format tag 3) */
	POISE_MAC_S16, /* 16-bit PCM WAV (format tag 1) */
};

struct poise_mac_session_config {
	const char *output_device; /* name or UID substring; NULL = default output */
	const char *out_path;      /* WAV path; NULL = count only */
	unsigned seconds;          /* 0 = run until SIGINT/SIGTERM */
	unsigned rate;             /* requested nominal rate of every stream */
	enum poise_mac_sample_format sample_format;
	int passthrough;           /* copy tap buffers to the output buffers */
	int verbose;
};

struct poise_mac_session;

/* Creates the tap, the private aggregate and the IOProc. On failure returns
 * NULL and fills err. Waits up to 180 s for the TCC grant, printing the
 * "WAITING FOR HUMAN" line, because the prompt needs a person. */
struct poise_mac_session *poise_mac_session_start(
	const struct poise_mac_session_config *cfg, char *err, size_t err_size);

/* Runs for cfg->seconds or until poise_mac_request_stop(). */
void poise_mac_session_run(struct poise_mac_session *s);

/* Stops and destroys: IOProc, aggregate, tap (in that order; see .m). Safe to
 * call twice. */
void poise_mac_session_stop(struct poise_mac_session *s);

void poise_mac_session_counters(const struct poise_mac_session *s,
                                struct poise_mac_counters *out);

/* Format/device report for probe (c): the tap's ASBD, the aggregate's input
 * and output ASBDs as read back, the output device's nominal rate. */
void poise_mac_session_report(const struct poise_mac_session *s);

/* Peak and RMS of the captured audio, and the capture level in the last
 * second, which is how the self-tap (feedback) probe reads. */
void poise_mac_session_levels(const struct poise_mac_session *s,
                              float *peak, float *rms, float *tail_rms);

/* Prints every HAL device with output streams: name, UID, rate, transport. */
void poise_mac_list_devices(void);

/* Asks the session to stop at the next run-loop tick (async-signal-safe). */
void poise_mac_request_stop(void);

#endif /* POISE_COREAUDIO_H */
