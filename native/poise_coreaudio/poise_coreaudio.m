/*
 * Poise's macOS audio path, the counterpart of poise_wasapi.c and poise_pw.c.
 *
 * Windows gets a virtual cable, Linux a PipeWire loopback; macOS has neither,
 * so this uses the Core Audio process-tap API (macOS 14.2+):
 *
 *   every app's audio -> global CATap, muteBehavior = MutedWhenTapped
 *                            |  one tap stream, mixdown to stereo
 *                 private aggregate: tap = input, real output device = output
 *                            |  and clock master; explicit 48 kHz Float32
 *                            |  stream format on both sides
 *                     one IOProc (THREAD_TIME_CONSTRAINT_POLICY)
 *                            |
 *                 poise_core (native/core/): capture in, delayed output out
 *                            |
 *              Python inference thread (node_loop -> DF3 / GTCRN)
 *
 * Why the format is set, not negotiated: Core Audio has no AUTOCONVERTPCM
 * (poise_wasapi.c asks WASAPI for it); the aggregate's stream format is what
 * the IOProc sees, and the HAL resamples the physical device to it. So the
 * node always runs at one rate, and a device that will not take that format is
 * refused rather than run at another rate (the format contract). The HAL hands back
 * interleaved buffers even when asked for non-interleaved, so the IOProc
 * discovers the layout from the buffer list (measurements/mac-tap-spike.md (c)).
 *
 * Why the tap must not outlive the process: with MutedWhenTapped, the tap
 * silences every app's audio while it is being read. It is destroyed on the
 * normal path (poise_ca_destroy), by the 250 ms watchdog (the mute contract) and from atexit.
 *
 * The mute is released by AudioDeviceStop(): MutedWhenTapped mutes only while
 * the tap is read, so the order here is stop the device, destroy the IOProc,
 * the aggregate, then the tap. Destroying the tap first would leave a live
 * aggregate pointing at a dead object (the HAL refuses), and the aggregate
 * cannot be destroyed while its device runs, so this is the only order that
 * always ends with no tap and no silence.
 *
 * What the node does not do: it runs no inference. The IOProc pushes capture
 * into the core and plays back what the core gives it, so a frame the worker
 * has not delivered in time plays unprocessed (dry) at the same delay instead
 * of arriving late (see poise_core.h).
 */
#import <Foundation/Foundation.h>

#import <CoreAudio/CoreAudio.h>
#import <CoreAudio/AudioHardwareTapping.h>
#import <CoreAudio/CATapDescription.h>
#import <AudioToolbox/AudioToolbox.h>

#include <errno.h>
#include <math.h>
#include <mach/mach.h>
#include <mach/mach_time.h>
#include <mach/thread_policy.h>
#include <pthread.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#include "poise_coreaudio.h"

#define TAP_NAME "Poise Tap"
#define AGGREGATE_NAME "Poise Tap"
#define SCRATCH_FRAMES 8192u     /* largest cycle handled in one go */
#define TCC_WAIT_SECONDS 180u    /* the grant prompt needs a person */
#define TCC_RETRY_MS 3000u
#define WATCHDOG_MS 250u         /* no callback this long = stop, which unmutes the Mac */
#define WATCHDOG_TICK_MS 50u
#define STARTUP_CALLBACK_MS 3000u
/* Peak below which captured audio counts as silence (about -100 dBFS), the
 * same floor poise_core.c uses. */
#define SILENCE 1e-5f

struct poise_ca_counters {
	_Atomic uint64_t callbacks;
	_Atomic uint64_t input_frames;
	_Atomic uint64_t output_frames;
	_Atomic uint64_t quantum_min;
	_Atomic uint64_t dropped;
	_Atomic uint64_t overloads;
	_Atomic uint64_t quiet_frames;
	_Atomic int saw_signal;
	_Atomic int rt_policy_set;
	/* Clocks: the tap's time stamp is in the tap's clock domain, the output's
	 * in the output device's clock domain. */
	_Atomic int64_t first_in_time;
	_Atomic int64_t last_in_time;
	_Atomic int64_t first_out_time;
	_Atomic int64_t last_out_time;
	_Atomic int64_t delta_min;
	_Atomic int64_t delta_max;
	_Atomic int has_time;
};

struct poise_ca {
	AudioObjectID tap_id;
	AudioObjectID aggregate_id;
	AudioObjectID output_device;
	AudioDeviceIOProcID proc_id;
	AudioStreamBasicDescription requested;
	AudioStreamBasicDescription tap_format;
	AudioStreamBasicDescription input_format;
	AudioStreamBasicDescription output_format;
	AudioStreamBasicDescription device_format;
	double device_nominal_rate;
	UInt32 drift_compensation;
	char clock_uid[256];
	char device_name[256];
	uint32_t rate;
	int tap_mute;

	poise_core *core;
	float *scratch; /* mono, SCRATCH_FRAMES */

	struct poise_ca_counters c;

	/* Mute contract: teardown is serialised with the watchdog and poise_ca_destroy. The
	 * realtime callback never takes this lock. */
	pthread_mutex_t lock;
	int stopped;
	char err[512];
	_Atomic int failed;
	_Atomic uint64_t last_callback_ms;
	pthread_t monitor;
	_Atomic int monitor_stop;
	int monitor_started;

	/* RT policy, read back once on the IOProc thread. */
	int policy_verified;
	uint32_t policy_period;
	uint32_t policy_computation;
	uint32_t policy_constraint;
	uint32_t policy_preemptible;
	uint32_t time_flags_in;
	uint32_t time_flags_out;
};

/* ---------------------------------------------------------------- helpers */

static uint64_t monotonic_ms_(void)
{
	struct timespec t;

	clock_gettime(CLOCK_MONOTONIC, &t);
	return (uint64_t)t.tv_sec * 1000ull + (uint64_t)t.tv_nsec / 1000000ull;
}

static const char *fourcc(OSStatus st, char buf[8])
{
	uint32_t v = (uint32_t)st;
	for (int i = 0; i < 4; i++) {
		unsigned char c = (unsigned char)((v >> (24 - 8 * i)) & 0xff);
		buf[i] = (c >= 32 && c < 127) ? (char)c : '?';
	}
	buf[4] = 0;
	return buf;
}

static void report_status(const char *what, OSStatus st)
{
	char code[8];
	fprintf(stderr, "poise: %s: OSStatus %d '%s'\n", what, (int)st, fourcc(st, code));
}

static int cfstring_copy(CFStringRef s, char *buf, size_t n)
{
	if (!n)
		return 0;
	buf[0] = 0;
	if (!s)
		return 0;
	return CFStringGetCString(s, buf, (CFIndex)n, kCFStringEncodingUTF8) ? 1 : 0;
}

static OSStatus hal_get(AudioObjectID obj, AudioObjectPropertySelector sel,
                        AudioObjectPropertyScope scope, void *data, UInt32 *size)
{
	AudioObjectPropertyAddress a = { sel, scope, kAudioObjectPropertyElementMain };
	return AudioObjectGetPropertyData(obj, &a, 0, NULL, size, data);
}

static UInt32 hal_data_size(AudioObjectID obj, AudioObjectPropertySelector sel,
                            AudioObjectPropertyScope scope)
{
	AudioObjectPropertyAddress a = { sel, scope, kAudioObjectPropertyElementMain };
	UInt32 size = 0;
	if (AudioObjectGetPropertyDataSize(obj, &a, 0, NULL, &size) != noErr)
		return 0;
	return size;
}

static OSStatus hal_set(AudioObjectID obj, AudioObjectPropertySelector sel,
                        AudioObjectPropertyScope scope, const void *data, UInt32 size)
{
	AudioObjectPropertyAddress a = { sel, scope, kAudioObjectPropertyElementMain };
	return AudioObjectSetPropertyData(obj, &a, 0, NULL, size, data);
}

static int hal_get_string(AudioObjectID obj, AudioObjectPropertySelector sel,
                          AudioObjectPropertyScope scope, char *buf, size_t n)
{
	CFStringRef s = NULL;
	UInt32 size = sizeof(s);
	if (hal_get(obj, sel, scope, &s, &size) != noErr) {
		if (n)
			buf[0] = 0;
		return 0;
	}
	int ok = cfstring_copy(s, buf, n);
	if (s)
		CFRelease(s);
	return ok;
}

static AudioObjectID default_output_device(void)
{
	AudioObjectID dev = 0;
	UInt32 size = sizeof(dev);
	if (hal_get(kAudioObjectSystemObject, kAudioHardwarePropertyDefaultOutputDevice,
	            kAudioObjectPropertyScopeGlobal, &dev, &size) != noErr)
		return 0;
	return dev;
}

static AudioObjectID *hal_device_list(UInt32 *count)
{
	UInt32 size = hal_data_size(kAudioObjectSystemObject, kAudioHardwarePropertyDevices,
	                           kAudioObjectPropertyScopeGlobal);
	if (!size) {
		*count = 0;
		return NULL;
	}
	AudioObjectID *devs = calloc(1, size);
	if (!devs) {
		*count = 0;
		return NULL;
	}
	if (hal_get(kAudioObjectSystemObject, kAudioHardwarePropertyDevices,
	            kAudioObjectPropertyScopeGlobal, devs, &size) != noErr) {
		free(devs);
		*count = 0;
		return NULL;
	}
	*count = size / sizeof(AudioObjectID);
	return devs;
}

static int device_has_output(const AudioObjectID dev)
{
	return hal_data_size(dev, kAudioDevicePropertyStreams, kAudioObjectPropertyScopeOutput) > 0;
}

static AudioObjectID find_output_device(const char *want)
{
	if (!want || !*want)
		return default_output_device();
	AudioObjectID *devs = NULL;
	UInt32 count = 0;
	devs = hal_device_list(&count);
	AudioObjectID found = 0;
	for (UInt32 i = 0; i < count && !found; i++) {
		if (!device_has_output(devs[i]))
			continue;
		char name[256] = "";
		char uid[256] = "";
		hal_get_string(devs[i], kAudioObjectPropertyName, kAudioObjectPropertyScopeGlobal, name, sizeof(name));
		hal_get_string(devs[i], kAudioDevicePropertyDeviceUID, kAudioObjectPropertyScopeGlobal, uid, sizeof(uid));
		if (strcasestr(name, want) || strcasestr(uid, want))
			found = devs[i];
	}
	free(devs);
	return found;
}

static AudioStreamBasicDescription make_format(unsigned rate)
{
	AudioStreamBasicDescription f;
	memset(&f, 0, sizeof(f));
	f.mSampleRate = rate;
	f.mFormatID = kAudioFormatLinearPCM;
	f.mFormatFlags = kAudioFormatFlagIsFloat | kAudioFormatFlagIsPacked |
	                 kAudioFormatFlagIsNonInterleaved;
	f.mFramesPerPacket = 1;
	f.mChannelsPerFrame = POISE_COREAUDIO_CHANNELS;
	f.mBitsPerChannel = 32;
	f.mBytesPerFrame = 4;  /* per buffer: non-interleaved */
	f.mBytesPerPacket = 4;
	return f;
}

static int is_non_interleaved(const AudioStreamBasicDescription *f)
{
	return (f->mFormatFlags & kAudioFormatFlagIsNonInterleaved) != 0;
}

/* What the node needs to run: the requested rate, 32-bit float, and the channel
 * count. Interleaving is *not* required: on macOS 27 the HAL hands back an
 * interleaved Float32 stream for both the tap and the aggregate even when the
 * non-interleaved flag is set on the request, and the IOProc discovers the
 * layout from the buffer list anyway (see measurements/mac-tap-spike.md (c)). */
static int format_acceptable(const AudioStreamBasicDescription *got,
                             const AudioStreamBasicDescription *want)
{
	if (fabs(got->mSampleRate - want->mSampleRate) >= 0.5)
		return 0;
	if (got->mFormatID != kAudioFormatLinearPCM)
		return 0;
	if (!(got->mFormatFlags & kAudioFormatFlagIsFloat))
		return 0;
	if (got->mBitsPerChannel != 32)
		return 0;
	if (got->mChannelsPerFrame != want->mChannelsPerFrame)
		return 0;
	UInt32 bytes_per_frame = 4 * got->mChannelsPerFrame;
	if (is_non_interleaved(got) && got->mBytesPerFrame != 4)
		return 0;
	if (!is_non_interleaved(got) && got->mBytesPerFrame != bytes_per_frame)
		return 0;
	return 1;
}

static void format_name(const AudioStreamBasicDescription *f, char *buf, size_t n)
{
	CFStringRef name = NULL;
	UInt32 size = sizeof(name);
	if (AudioFormatGetProperty(kAudioFormatProperty_FormatName, sizeof(*f), f, &size, &name) == noErr &&
	    name) {
		cfstring_copy(name, buf, n);
		CFRelease(name);
		return;
	}
	snprintf(buf, n, "unknown");
}

static void print_asbd(const char *what, const AudioStreamBasicDescription *f)
{
	char name[128];
	format_name(f, name, sizeof(name));
	printf("poise: %s: %.0f Hz, %u ch, %s (%s), flags 0x%x, %u bytes/frame\n",
	       what, f->mSampleRate, (unsigned)f->mChannelsPerFrame,
	       (f->mFormatFlags & kAudioFormatFlagIsFloat) ? "Float32" : "not-float",
	       name, (unsigned)f->mFormatFlags, (unsigned)f->mBytesPerFrame);
}

/* ---------------------------------------------------------- buffer layouts */

static uint32_t abl_frames(const AudioBufferList *abl)
{
	uint32_t frames = 0;
	if (!abl)
		return 0;
	for (UInt32 i = 0; i < abl->mNumberBuffers; i++) {
		uint32_t ch = abl->mBuffers[i].mNumberChannels;
		if (!ch)
			continue;
		uint32_t f = (uint32_t)(abl->mBuffers[i].mDataByteSize / (ch * sizeof(float)));
		if (f > frames)
			frames = f;
	}
	return frames;
}

/* Truncate a chunk to what every buffer of the list can actually hold: the HAL
 * hands out buffers shorter than the cycle around device start/stop, and
 * writing past mDataByteSize would corrupt the callback's stack (the format contract). */
static uint32_t abl_clamp(const AudioBufferList *abl, uint32_t frames, uint64_t offset)
{
	if (!abl || abl->mNumberBuffers == 0)
		return 0;
	for (UInt32 i = 0; i < abl->mNumberBuffers; i++) {
		uint32_t ch = abl->mBuffers[i].mNumberChannels
		                  ? abl->mBuffers[i].mNumberChannels : 1;
		uint64_t cap = (uint64_t)abl->mBuffers[i].mDataByteSize / (sizeof(float) * ch);
		if ((uint64_t)offset >= cap)
			return 0;
		if ((uint64_t)offset + frames > cap)
			frames = (uint32_t)(cap - (uint64_t)offset);
	}
	return frames;
}

/* A chunk of any of the layouts the HAL gives us (interleaved stereo, two mono
 * buffers, one mono buffer) averaged to mono. Returns the frames read, 0 for a
 * layout or a size that cannot be read. */
static uint32_t abl_read_mono(const AudioBufferList *abl, float *dst,
                              uint32_t frames, uint64_t offset)
{
	uint32_t total_ch = 0;

	frames = abl_clamp(abl, frames, offset);
	if (!frames)
		return 0;
	memset(dst, 0, (size_t)frames * sizeof(float));
	for (UInt32 b = 0; b < abl->mNumberBuffers; b++) {
		uint32_t ch = abl->mBuffers[b].mNumberChannels
		                  ? abl->mBuffers[b].mNumberChannels : 1;
		const float *src = (const float *)abl->mBuffers[b].mData;
		if (!src)
			return 0;
		src += offset * ch;
		for (uint32_t i = 0; i < frames; i++) {
			for (uint32_t k = 0; k < ch; k++)
				dst[i] += src[i * ch + k];
		}
		total_ch += ch;
	}
	if (!total_ch)
		return 0;
	if (total_ch > 1) {
		float scale = 1.0f / (float)total_ch;
		for (uint32_t i = 0; i < frames; i++)
			dst[i] *= scale;
	}
	return frames;
}

/* The same mono signal into every channel of every buffer. Returns the frames
 * written, 0 if the layout cannot be written. */
static uint32_t abl_write_mono(AudioBufferList *abl, const float *src,
                               uint32_t frames, uint64_t offset)
{
	frames = abl_clamp(abl, frames, offset);
	if (!frames)
		return 0;
	for (UInt32 b = 0; b < abl->mNumberBuffers; b++) {
		uint32_t ch = abl->mBuffers[b].mNumberChannels
		                  ? abl->mBuffers[b].mNumberChannels : 1;
		float *dst = (float *)abl->mBuffers[b].mData;
		if (!dst)
			return 0;
		dst += offset * ch;
		for (uint32_t i = 0; i < frames; i++) {
			for (uint32_t k = 0; k < ch; k++)
				dst[i * ch + k] = src[i];
		}
	}
	return frames;
}

/* ---------------------------------------------------------------- IOProc */

/* The analogue of the Windows MMCSS "Pro Audio" path: ask for a time-constraint
 * thread sized to one callback. Set once, from the first callback, because
 * Core Audio has no thread-start hook. */
static void set_realtime_policy(struct poise_ca *n, uint32_t frames)
{
	double rate = n->rate;
	if (!frames || rate <= 0)
		return;
	mach_timebase_info_data_t tb;
	mach_timebase_info(&tb);
	double period_ns = (double)frames / rate * 1e9;
	double ticks = period_ns * (double)tb.denom / (double)tb.numer;
	thread_time_constraint_policy_data_t p;
	p.period = (uint32_t)ticks;
	p.computation = (uint32_t)(ticks / 2);
	p.constraint = (uint32_t)ticks;
	p.preemptible = 0;
	kern_return_t kr = thread_policy_set(mach_thread_self(), THREAD_TIME_CONSTRAINT_POLICY,
	                                     (thread_policy_t)&p,
	                                     THREAD_TIME_CONSTRAINT_POLICY_COUNT);
	if (kr == KERN_SUCCESS)
		atomic_store(&n->c.rt_policy_set, 1);
	/* No printf here: this runs on the audio callback, and a failed policy
	 * shows up as rt_policy 0 in the stats (the CLI prints it). */
}

/* Capture health: a denied System Audio Recording grant arrives as zeros, never as an
 * error, so capture health is measured energy, not a return code. */
static void meter_capture(struct poise_ca *n, const float *mono, uint32_t frames)
{
	uint32_t quiet = 0;
	int loud = 0;

	for (uint32_t i = 0; i < frames; i++) {
		float x = mono[i];
		if (x > SILENCE || x < -SILENCE)
			loud = 1;
		else
			quiet++;
	}
	if (loud)
		atomic_store(&n->c.saw_signal, 1);
	if (quiet)
		atomic_fetch_add(&n->c.quiet_frames, quiet);
}

static OSStatus ioproc(AudioObjectID dev, const AudioTimeStamp *now,
                       const AudioBufferList *inInputData, const AudioTimeStamp *inInputTime,
                       AudioBufferList *outOutputData, const AudioTimeStamp *inOutputTime,
                       void *ctx)
{
	struct poise_ca *n = ctx;
	(void)dev;
	(void)now;

	uint32_t in_frames = abl_frames(inInputData);
	uint32_t out_frames = abl_frames(outOutputData);

	uint64_t call = atomic_fetch_add(&n->c.callbacks, 1);
	atomic_store(&n->last_callback_ms, monotonic_ms_());
	if (call == 0 && in_frames)
		set_realtime_policy(n, in_frames);
	if (call == 1) {
		/* Read the policy back once, to prove it took rather than trusting the
		 * return value. */
		thread_time_constraint_policy_data_t got;
		mach_msg_type_number_t count = THREAD_TIME_CONSTRAINT_POLICY_COUNT;
		boolean_t get_default = 0;
		kern_return_t kr = thread_policy_get(mach_thread_self(), THREAD_TIME_CONSTRAINT_POLICY,
		                                     (thread_policy_t)&got, &count, &get_default);
		if (kr == KERN_SUCCESS) {
			n->policy_period = got.period;
			n->policy_computation = got.computation;
			n->policy_constraint = got.constraint;
			n->policy_preemptible = got.preemptible;
			n->policy_verified = 1;
		}
	}
	if (in_frames) {
		uint64_t min = atomic_load(&n->c.quantum_min);
		if (!min || in_frames < min)
			atomic_store(&n->c.quantum_min, in_frames);
	}

	/* Clock domains: the tap's time stamp is the tap's clock, the output's
	 * is the output device's. Their difference is the playout leg's latency. */
	if (inInputTime && inOutputTime) {
		int64_t in_t = (int64_t)llround(inInputTime->mSampleTime);
		int64_t out_t = (int64_t)llround(inOutputTime->mSampleTime);
		if (!atomic_load(&n->c.has_time)) {
			n->time_flags_in = inInputTime->mFlags;
			n->time_flags_out = inOutputTime->mFlags;
			atomic_store(&n->c.first_in_time, in_t);
			atomic_store(&n->c.first_out_time, out_t);
			atomic_store(&n->c.delta_min, out_t - in_t);
			atomic_store(&n->c.delta_max, out_t - in_t);
			atomic_store(&n->c.has_time, 1);
		}
		atomic_store(&n->c.last_in_time, in_t);
		atomic_store(&n->c.last_out_time, out_t);
		if (out_t - in_t < atomic_load(&n->c.delta_min))
			atomic_store(&n->c.delta_min, out_t - in_t);
		if (out_t - in_t > atomic_load(&n->c.delta_max))
			atomic_store(&n->c.delta_max, out_t - in_t);
	}

	/* (a) the tap's buffers -> (b) the core's input history. */
	for (uint32_t done = 0; done < in_frames;) {
		uint32_t chunk = in_frames - done;
		uint32_t got;

		if (chunk > SCRATCH_FRAMES)
			chunk = SCRATCH_FRAMES;
		got = abl_read_mono(inInputData, n->scratch, chunk, done);
		if (!got) {
			atomic_fetch_add(&n->c.dropped, chunk);
			break;
		}
		meter_capture(n, n->scratch, got);
		poise_core_input(n->core, (const float *const[]){ n->scratch }, 1, got);
		atomic_fetch_add(&n->c.input_frames, got);
		done += got;
		if (got < chunk) {
			atomic_fetch_add(&n->c.dropped, chunk - got);
			break;
		}
	}

	/* (c) the core's delayed output -> the aggregate's output buffers. The
	 * output buffer can be SHORTER than what the tap delivered (a device
	 * start/stop transition, or an output quantum smaller than the tap's), so
	 * what does not fit is counted rather than written. */
	for (uint32_t done = 0; done < out_frames;) {
		uint32_t chunk = out_frames - done;
		uint32_t wrote;

		if (chunk > SCRATCH_FRAMES)
			chunk = SCRATCH_FRAMES;
		/* Clamp to what the HAL's buffer can actually take BEFORE asking the
		 * core for it: poise_core_output() commits the frame (advances out_pos
		 * and records the wet/dry decision), so pulling a chunk we then fail
		 * to write would drop those samples from the output timeline AND
		 * shorten the fixed delay by chunk - wrote. */
		chunk = (uint32_t)abl_clamp(outOutputData, chunk, done);
		if (!chunk) {
			atomic_fetch_add(&n->c.overloads, 1);
			break;
		}
		poise_core_output(n->core, (float *const[]){ n->scratch }, 1, chunk);
		wrote = abl_write_mono(outOutputData, n->scratch, chunk, done);
		if (wrote < chunk) {
			atomic_fetch_add(&n->c.overloads, 1);
			atomic_fetch_add(&n->c.output_frames, wrote);
			break;
		}
		atomic_fetch_add(&n->c.output_frames, wrote);
		done += wrote;
	}
	return noErr;
}

/* --------------------------------------------------------------- the tap */

static OSStatus create_tap(struct poise_ca *n, AudioObjectID *tap)
{
	/* Poise's own process is excluded so the node never re-captures its own
	 * output: the aggregate writes the same audio it reads, so including self
	 * would close a loop (measurements/mac-tap-spike.md (e)). */
	AudioObjectID self = 0;
	pid_t pid = getpid();
	UInt32 size = sizeof(self);
	AudioObjectPropertyAddress a = { kAudioHardwarePropertyTranslatePIDToProcessObject,
	                                 kAudioObjectPropertyScopeGlobal,
	                                 kAudioObjectPropertyElementMain };
	OSStatus st = AudioObjectGetPropertyData(kAudioObjectSystemObject, &a, sizeof(pid), &pid,
	                                         &size, &self);
	if (st != noErr || !self)
		fprintf(stderr, "poise: cannot translate own pid to a process object (st=%d); "
		                "the tap will include Poise's own output\n", (int)st);

	NSArray<NSNumber *> *exclude = self ? @[ @(self) ] : @[];
	CATapDescription *desc = [[CATapDescription alloc] initStereoGlobalTapButExcludeProcesses:exclude];
	desc.name = @TAP_NAME;
	desc.muteBehavior = n->tap_mute ? CATapMutedWhenTapped : CATapUnmuted;
	desc.privateTap = NO;
	desc.mixdown = YES;
	desc.mono = NO;
	desc.exclusive = YES;
	st = AudioHardwareCreateProcessTap(desc, tap);
	if (st != noErr)
		report_status("AudioHardwareCreateProcessTap", st);
	return st;
}

static void tap_uid(AudioObjectID tap, char *buf, size_t n)
{
	hal_get_string(tap, kAudioTapPropertyUID, kAudioObjectPropertyScopeGlobal, buf, n);
}

/* ------------------------------------------------------------- aggregate */

static OSStatus set_stream_formats(struct poise_ca *n, AudioObjectPropertyScope scope,
                                   AudioStreamBasicDescription *readback, const char *what)
{
	UInt32 size = hal_data_size(n->aggregate_id, kAudioDevicePropertyStreams, scope);
	if (!size) {
		report_status(what, kAudioHardwareBadObjectError);
		return kAudioHardwareBadObjectError;
	}
	AudioStreamID *streams = calloc(1, size);
	if (!streams)
		return kAudioHardwareUnspecifiedError;
	if (hal_get(n->aggregate_id, kAudioDevicePropertyStreams, scope, streams, &size) != noErr) {
		free(streams);
		return kAudioHardwareUnspecifiedError;
	}
	UInt32 count = size / sizeof(AudioStreamID);
	OSStatus result = noErr;
	OSStatus st;
	for (UInt32 i = 0; i < count; i++) {
		st = hal_set(streams[i], kAudioStreamPropertyVirtualFormat, kAudioObjectPropertyScopeGlobal,
		             &n->requested, sizeof(n->requested));
		if (st != noErr) {
			char line[128];
			snprintf(line, sizeof(line), "%s stream %u: set virtual format", what, (unsigned)i);
			report_status(line, st);
			if (result == noErr)
				result = st;
		}
	}
	if (count) {
		UInt32 sz = sizeof(*readback);
		if (hal_get(streams[0], kAudioStreamPropertyVirtualFormat, kAudioObjectPropertyScopeGlobal,
		            readback, &sz) != noErr)
			memset(readback, 0, sizeof(*readback));
	}
	free(streams);
	return result;
}

static OSStatus create_aggregate(struct poise_ca *n, const char *tapuid)
{
	char outuid[256] = "";
	hal_get_string(n->output_device, kAudioDevicePropertyDeviceUID, kAudioObjectPropertyScopeGlobal,
	               outuid, sizeof(outuid));
	if (!outuid[0]) {
		fprintf(stderr, "poise: output device has no UID\n");
		return kAudioHardwareBadObjectError;
	}

	NSString *aggUID = [NSString stringWithFormat:@"dev.poise.node.%@", [[NSUUID UUID] UUIDString]];
	NSDictionary *subDevice = @{ @kAudioSubDeviceUIDKey : @(outuid) };
	NSDictionary *tapEntry = @{
		@kAudioSubTapUIDKey : @(tapuid),
		/* The tap's clock and the output device's clock are not the same clock,
		 * so the HAL must resample one of them. */
		@kAudioSubTapDriftCompensationKey : @(1),
		@kAudioSubTapDriftCompensationQualityKey : @(kAudioAggregateDriftCompensationHighQuality),
	};
	NSDictionary *desc = @{
		@kAudioAggregateDeviceUIDKey : aggUID,
		@kAudioAggregateDeviceNameKey : @AGGREGATE_NAME,
		@kAudioAggregateDeviceIsPrivateKey : @YES,
		@kAudioAggregateDeviceIsStackedKey : @NO,
		@kAudioAggregateDeviceSubDeviceListKey : @[ subDevice ],
		@kAudioAggregateDeviceMainSubDeviceKey : @(outuid),
		@kAudioAggregateDeviceClockDeviceKey : @(outuid),
		@kAudioAggregateDeviceTapListKey : @[ tapEntry ],
		@kAudioAggregateDeviceTapAutoStartKey : @YES,
	};
	OSStatus st = AudioHardwareCreateAggregateDevice((__bridge CFDictionaryRef)desc,
	                                                 &n->aggregate_id);
	if (st != noErr) {
		report_status("AudioHardwareCreateAggregateDevice", st);
		/* The clock-device key is the one the API is least forgiving about; retry
		 * without it, since the main sub-device is already the clock master. */
		NSMutableDictionary *retry = [desc mutableCopy];
		[retry removeObjectForKey:@kAudioAggregateDeviceClockDeviceKey];
		st = AudioHardwareCreateAggregateDevice((__bridge CFDictionaryRef)retry,
		                                        &n->aggregate_id);
		if (st != noErr) {
			report_status("AudioHardwareCreateAggregateDevice (no clock key)", st);
			return st;
		}
		fprintf(stderr, "poise: aggregate accepted only without the explicit clock device\n");
	}
	return noErr;
}

static void read_back_aggregate(struct poise_ca *n)
{
	/* Clock master, as the HAL sees it. */
	CFStringRef clock = NULL;
	UInt32 size = sizeof(clock);
	AudioObjectPropertyAddress a = { kAudioAggregateDevicePropertyClockDevice,
	                                 kAudioObjectPropertyScopeGlobal,
	                                 kAudioObjectPropertyElementMain };
	if (AudioObjectGetPropertyData(n->aggregate_id, &a, 0, NULL, &size, &clock) == noErr && clock) {
		cfstring_copy(clock, n->clock_uid, sizeof(n->clock_uid));
		CFRelease(clock);
	}

	/* Per-sub-tap drift compensation, as read back. Not readable from a
	 * client process on macOS 27; the value stays 0 then. */
	AudioObjectID *subtaps = NULL;
	size = 0;
	a.mSelector = kAudioAggregateDevicePropertySubTapList;
	if (AudioObjectGetPropertyDataSize(n->aggregate_id, &a, 0, NULL, &size) == noErr && size) {
		subtaps = calloc(1, size);
		if (subtaps &&
		    AudioObjectGetPropertyData(n->aggregate_id, &a, 0, NULL, &size, subtaps) == noErr) {
			UInt32 count = size / sizeof(AudioObjectID);
			for (UInt32 i = 0; i < count; i++) {
				UInt32 value = 0;
				UInt32 vsize = sizeof(value);
				AudioObjectPropertyAddress d = { kAudioSubTapPropertyDriftCompensation,
				                                 kAudioObjectPropertyScopeGlobal,
				                                 kAudioObjectPropertyElementMain };
				if (AudioObjectGetPropertyData(subtaps[i], &d, 0, NULL, &vsize, &value) == noErr)
					n->drift_compensation = value;
			}
		}
		free(subtaps);
	}
}

/* ------------------------------------------- teardown: destroying the tap unmutes */

/* Stop the device (this is what unmutes the Mac), destroy the IOProc, the
 * aggregate and the tap, in that order. Idempotent. */
static void teardown(struct poise_ca *n)
{
	pthread_mutex_lock(&n->lock);
	if (!n->stopped) {
		n->stopped = 1;
		if (n->aggregate_id && n->proc_id) {
			AudioDeviceStop(n->aggregate_id, n->proc_id);
			AudioDeviceDestroyIOProcID(n->aggregate_id, n->proc_id);
			n->proc_id = 0;
		}
		if (n->aggregate_id) {
			AudioHardwareDestroyAggregateDevice(n->aggregate_id);
			n->aggregate_id = 0;
		}
		if (n->tap_id) {
			AudioHardwareDestroyProcessTap(n->tap_id);
			n->tap_id = 0;
		}
	}
	pthread_mutex_unlock(&n->lock);
}

static void fail_with(struct poise_ca *n, const char *msg)
{
	pthread_mutex_lock(&n->lock);
	if (!n->err[0])
		snprintf(n->err, sizeof(n->err), "%s", msg);
	pthread_mutex_unlock(&n->lock);
	atomic_store(&n->failed, 1);
}

/* Mute contract: a tap that stops being read keeps the whole Mac silent, so a device that
 * stops calling back must not leave one behind. The first callback is
 * poise_ca_new()'s business (a missing grant looks exactly like this). */
static void *watchdog_thread(void *arg)
{
	struct poise_ca *n = arg;

	for (;;) {
		struct timespec ts = { 0, WATCHDOG_TICK_MS * 1000000L };

		nanosleep(&ts, NULL);
		if (atomic_load(&n->monitor_stop))
			break;
		uint64_t last = atomic_load(&n->last_callback_ms);
		if (!last)
			continue;
		if (monotonic_ms_() - last <= WATCHDOG_MS)
			continue;
		fail_with(n, "poise stopped and audio was restored: the audio device "
		             "stopped calling back for 250 ms");
		teardown(n);
		break;
	}
	return NULL;
}

/* Every live node, for the atexit safety net: a tap that outlives the process
 * mutes the whole Mac until it is destroyed. */
#define MAX_NODES 8
static struct poise_ca *g_nodes[MAX_NODES];
static pthread_mutex_t g_nodes_lock = PTHREAD_MUTEX_INITIALIZER;
static int g_atexit_armed;

static void destroy_node(struct poise_ca *n);

static void on_exit(void)
{
	struct poise_ca *live[MAX_NODES];

	pthread_mutex_lock(&g_nodes_lock);
	memcpy(live, g_nodes, sizeof(live));
	memset(g_nodes, 0, sizeof(g_nodes));
	pthread_mutex_unlock(&g_nodes_lock);
	for (int i = 0; i < MAX_NODES; i++) {
		if (live[i])
			destroy_node(live[i]);
	}
}

static void register_node(struct poise_ca *n)
{
	pthread_mutex_lock(&g_nodes_lock);
	for (int i = 0; i < MAX_NODES; i++) {
		if (!g_nodes[i]) {
			g_nodes[i] = n;
			break;
		}
	}
	if (!g_atexit_armed) {
		g_atexit_armed = 1;
		atexit(on_exit);
	}
	pthread_mutex_unlock(&g_nodes_lock);
}

static void unregister_node(struct poise_ca *n)
{
	pthread_mutex_lock(&g_nodes_lock);
	for (int i = 0; i < MAX_NODES; i++) {
		if (g_nodes[i] == n)
			g_nodes[i] = NULL;
	}
	pthread_mutex_unlock(&g_nodes_lock);
}

/* --------------------------------------------------------------- the node */

static void free_node(struct poise_ca *n)
{
	atomic_store(&n->monitor_stop, 1);
	if (n->monitor_started)
		pthread_join(n->monitor, NULL);
	teardown(n);
	if (n->core) {
		poise_core_stop(n->core);
		poise_core_free(n->core);
		n->core = NULL;
	}
	free(n->scratch);
	n->scratch = NULL;
	pthread_mutex_destroy(&n->lock);
	free(n);
}

static void destroy_node(struct poise_ca *n)
{
	unregister_node(n);
	free_node(n);
}

void poise_ca_destroy(struct poise_ca *n)
{
	if (n)
		destroy_node(n);
}

poise_core *poise_ca_core(struct poise_ca *n)
{
	return n ? n->core : NULL;
}

uint32_t poise_ca_frame(struct poise_ca *n)
{
	return n && n->core ? poise_core_frame(n->core) : 0;
}

uint64_t poise_ca_delay_samples(struct poise_ca *n)
{
	return n && n->core ? poise_core_delay(n->core) : 0;
}

uint64_t poise_ca_io_latency_samples(struct poise_ca *n)
{
	int64_t delta;

	if (!n || !atomic_load(&n->c.has_time))
		return 0;
	delta = atomic_load(&n->c.delta_max);
	return delta > 0 ? (uint64_t)delta : 0;
}

int poise_ca_status(struct poise_ca *n, char *err, size_t errlen)
{
	if (!n || !atomic_load(&n->failed))
		return 0;
	if (err && errlen) {
		pthread_mutex_lock(&n->lock);
		snprintf(err, errlen, "%s", n->err);
		pthread_mutex_unlock(&n->lock);
	}
	return 1;
}

void poise_ca_get_stats(struct poise_ca *n, uint64_t *out, uint32_t n_stats)
{
	uint64_t core[POISE_STAT_COUNT];
	uint64_t v[POISE_CA_STAT_COUNT];
	uint32_t i;

	if (!n || !out)
		return;
	memset(core, 0, sizeof(core));
	if (n->core)
		poise_core_get_stats(n->core, core, POISE_STAT_COUNT);
	v[POISE_CA_CALLBACKS] = atomic_load(&n->c.callbacks);
	v[POISE_CA_INPUT_FRAMES] = atomic_load(&n->c.input_frames);
	v[POISE_CA_OUTPUT_FRAMES] = atomic_load(&n->c.output_frames);
	v[POISE_CA_FRAMES_WET] = core[POISE_STAT_FRAMES_WET];
	v[POISE_CA_FRAMES_DRY] = core[POISE_STAT_FRAMES_DRY];
	v[POISE_CA_FRAMES_SKIPPED] = core[POISE_STAT_FRAMES_SKIPPED];
	v[POISE_CA_FRAMES_LATE] = core[POISE_STAT_FRAMES_LATE];
	v[POISE_CA_DELAY_CHANGES] = core[POISE_STAT_DELAY_CHANGES];
	v[POISE_CA_RESYNCS] = core[POISE_STAT_RESYNCS];
	v[POISE_CA_INPUT_GAPS] = core[POISE_STAT_INPUT_GAPS];
	v[POISE_CA_QUANTUM_MAX] = core[POISE_STAT_QUANTUM_MAX];
	v[POISE_CA_DELAY_SAMPLES] = core[POISE_STAT_DELAY];
	v[POISE_CA_DROPPED] = atomic_load(&n->c.dropped);
	v[POISE_CA_OVERLOADS] = atomic_load(&n->c.overloads);
	v[POISE_CA_RESTARTS] = 0;    /* the device-change listeners are not implemented */
	v[POISE_CA_TAP_ALIVE] = 1;
	v[POISE_CA_QUIET_FRAMES] = atomic_load(&n->c.quiet_frames);
	v[POISE_CA_SAW_SIGNAL] = (uint64_t)atomic_load(&n->c.saw_signal);
	v[POISE_CA_DRIFT_SAMPLES] = (uint64_t)(int64_t)(atomic_load(&n->c.input_frames) -
	                                                atomic_load(&n->c.output_frames));
	v[POISE_CA_TIME_DELTA_MIN] = (uint64_t)atomic_load(&n->c.delta_min);
	v[POISE_CA_TIME_DELTA_MAX] = (uint64_t)atomic_load(&n->c.delta_max);
	v[POISE_CA_RT_POLICY] = (uint64_t)atomic_load(&n->c.rt_policy_set);
	for (i = 0; i < n_stats && i < POISE_CA_STAT_COUNT; i++)
		out[i] = v[i];
}

uint32_t poise_ca_stat_count(void)
{
	return POISE_CA_STAT_COUNT;
}

struct poise_ca *poise_ca_new(const char *output_device, uint32_t frame,
                              uint32_t engine_latency, uint32_t quantum, uint32_t margin,
                              uint32_t fade, float dry_gain, uint32_t rate, int tap_mute,
                              char *err, size_t errlen)
{
	struct poise_ca *n = calloc(1, sizeof(*n));
	if (!n) {
		snprintf(err, errlen, "out of memory");
		return NULL;
	}
	pthread_mutex_init(&n->lock, NULL);
	n->rate = rate ? rate : POISE_COREAUDIO_RATE;
	n->tap_mute = tap_mute;
	n->requested = make_format(n->rate);

	n->output_device = find_output_device(output_device);
	if (!n->output_device) {
		snprintf(err, errlen, "no output device matches \"%s\"",
		         output_device ? output_device : "default");
		goto fail;
	}
	hal_get_string(n->output_device, kAudioObjectPropertyName, kAudioObjectPropertyScopeGlobal,
	               n->device_name, sizeof(n->device_name));
	{
		char uid[256] = "";
		hal_get_string(n->output_device, kAudioDevicePropertyDeviceUID,
		               kAudioObjectPropertyScopeGlobal, uid, sizeof(uid));
		UInt32 size = sizeof(n->device_nominal_rate);
		hal_get(n->output_device, kAudioDevicePropertyNominalSampleRate,
		        kAudioObjectPropertyScopeGlobal, &n->device_nominal_rate, &size);
		AudioStreamID first = 0;
		UInt32 fsize = sizeof(first);
		if (hal_get(n->output_device, kAudioDevicePropertyStreams, kAudioObjectPropertyScopeOutput,
		            &first, &fsize) == noErr && fsize) {
			UInt32 sz = sizeof(n->device_format);
			hal_get(first, kAudioStreamPropertyVirtualFormat, kAudioObjectPropertyScopeGlobal,
			        &n->device_format, &sz);
		}
		printf("poise: output device: \"%s\" (uid %s), nominal %.0f Hz\n", n->device_name, uid,
		       n->device_nominal_rate);
	}

	/* The tap. A missing TCC grant makes this fail; the prompt needs a human, so
	 * wait for one instead of failing immediately. */
	OSStatus st;
	unsigned waited_ms = 0;
	for (;;) {
		st = create_tap(n, &n->tap_id);
		if (st == noErr)
			break;
		if (waited_ms >= TCC_WAIT_SECONDS * 1000u) {
			snprintf(err, errlen,
			         "AudioHardwareCreateProcessTap failed: OSStatus %d '%s' after waiting %u s "
			         "for the System Audio Recording grant",
			         (int)st, fourcc(st, (char[8]){ 0 }), TCC_WAIT_SECONDS);
			goto fail;
		}
		printf("poise: WAITING FOR HUMAN: approve the System Audio Recording prompt\n");
		printf("poise:   System Settings > Privacy & Security > Screen & System Audio Recording\n");
		fflush(stdout);
		struct timespec ts = { 0, TCC_RETRY_MS * 1000000L };
		nanosleep(&ts, NULL);
		waited_ms += TCC_RETRY_MS;
	}

	{
		char uid[256] = "";
		UInt32 size = sizeof(n->tap_format);
		tap_uid(n->tap_id, uid, sizeof(uid));
		if (hal_get(n->tap_id, kAudioTapPropertyFormat, kAudioObjectPropertyScopeGlobal,
		            &n->tap_format, &size) != noErr)
			memset(&n->tap_format, 0, sizeof(n->tap_format));

		/* Ask the tap for the node's format too; it is advisory (the aggregate
		 * stream format is what the IOProc gets), so a refusal is only a note. */
		st = hal_set(n->tap_id, kAudioTapPropertyFormat, kAudioObjectPropertyScopeGlobal,
		             &n->requested, sizeof(n->requested));
		if (st != noErr)
			report_status("tap: set kAudioTapPropertyFormat (advisory)", st);

		/* Read the description back: the evidence that the tap really excludes
		 * Poise's own process (measurements/mac-tap-spike.md (e)). */
		{
			CFTypeRef back = NULL;
			UInt32 bsize = sizeof(back);
			AudioObjectPropertyAddress ba = { kAudioTapPropertyDescription,
			                                  kAudioObjectPropertyScopeGlobal,
			                                  kAudioObjectPropertyElementMain };
			if (AudioObjectGetPropertyData(n->tap_id, &ba, 0, NULL, &bsize, &back) == noErr && back) {
				CATapDescription *d = (__bridge CATapDescription *)back;
				NSMutableString *procs = [NSMutableString string];
				for (NSNumber *p in d.processes)
					[procs appendFormat:@"%u ", p.unsignedIntValue];
				printf("poise: tap %s uid %s: exclusive=%d mixdown=%d mono=%d private=%d "
				       "muteBehavior=%ld processes=[%s]\n",
				       d.name.UTF8String, uid, d.isExclusive, d.isMixdown, d.isMono, d.isPrivate,
				       (long)d.muteBehavior, procs.UTF8String);
				CFRelease(back);
			}
		}

		if (create_aggregate(n, uid) != noErr) {
			snprintf(err, errlen, "cannot create the aggregate device for \"%s\"",
			         output_device ? output_device : "default output");
			goto fail;
		}
	}

	/* Explicit rate, Float32 on both sides: the HAL resamples the device. */
	set_stream_formats(n, kAudioObjectPropertyScopeInput, &n->input_format, "aggregate input");
	set_stream_formats(n, kAudioObjectPropertyScopeOutput, &n->output_format, "aggregate output");
	read_back_aggregate(n);

	printf("poise: requested format: %.0f Hz, %u ch, Float32\n", n->requested.mSampleRate,
	       (unsigned)n->requested.mChannelsPerFrame);
	print_asbd("tap format (kAudioTapPropertyFormat)", &n->tap_format);
	print_asbd("aggregate input stream (read back)", &n->input_format);
	print_asbd("aggregate output stream (read back)", &n->output_format);
	printf("poise: aggregate clock master: %s; sub-tap drift compensation read back %u\n",
	       n->clock_uid[0] ? n->clock_uid : "(not reported)", (unsigned)n->drift_compensation);

	/* Format contract: 48 kHz (or the requested rate) or refuse - never run the engine at a
	 * rate other than the one the streams actually carry. */
	if (!format_acceptable(&n->input_format, &n->requested)) {
		snprintf(err, errlen,
		         "refusing to run: the aggregate input stream is %.0f Hz, %u ch, flags 0x%x, not "
		         "the requested %.0f Hz Float32 (device \"%s\" runs at %.0f Hz)",
		         n->input_format.mSampleRate, (unsigned)n->input_format.mChannelsPerFrame,
		         (unsigned)n->input_format.mFormatFlags, n->requested.mSampleRate,
		         n->device_name, n->device_nominal_rate);
		goto fail;
	}
	if (!format_acceptable(&n->output_format, &n->requested)) {
		snprintf(err, errlen,
		         "refusing to run: the aggregate output stream is %.0f Hz, %u ch, flags 0x%x, not "
		         "the requested %.0f Hz Float32 (device \"%s\" runs at %.0f Hz)",
		         n->output_format.mSampleRate, (unsigned)n->output_format.mChannelsPerFrame,
		         (unsigned)n->output_format.mFormatFlags, n->requested.mSampleRate,
		         n->device_name, n->device_nominal_rate);
		goto fail;
	}

	n->core = poise_core_new(frame, engine_latency, quantum, margin, fade, dry_gain);
	if (!n->core) {
		snprintf(err, errlen, "invalid core parameters: frame %u, fade %u", frame, fade);
		goto fail;
	}
	n->scratch = calloc(SCRATCH_FRAMES, sizeof(float));
	if (!n->scratch) {
		snprintf(err, errlen, "out of memory");
		goto fail;
	}

	st = AudioDeviceCreateIOProcID(n->aggregate_id, ioproc, n, &n->proc_id);
	if (st != noErr) {
		report_status("AudioDeviceCreateIOProcID", st);
		snprintf(err, errlen, "AudioDeviceCreateIOProcID failed: OSStatus %d", (int)st);
		goto fail;
	}
	st = AudioDeviceStart(n->aggregate_id, n->proc_id);
	if (st != noErr) {
		report_status("AudioDeviceStart", st);
		snprintf(err, errlen, "AudioDeviceStart failed: OSStatus %d", (int)st);
		goto fail;
	}
	/* AudioDeviceStart returns noErr even when the HAL then declines to run the
	 * IO context, and a denied System Audio Recording grant looks the same; the
	 * only symptom is that no callback ever arrives. Report that as a failure
	 * rather than as a silent capture (capture health). */
	for (unsigned waited = 0; waited < STARTUP_CALLBACK_MS; waited += 25) {
		if (atomic_load(&n->c.callbacks))
			break;
		struct timespec ts = { 0, 25 * 1000000L };
		nanosleep(&ts, NULL);
	}
	if (!atomic_load(&n->c.callbacks)) {
		snprintf(err, errlen,
		         "the aggregate started (no error) but no IOProc callback arrived in %u ms: the "
		         "HAL did not run the aggregate (a denied System Audio Recording grant looks "
		         "like this)", STARTUP_CALLBACK_MS);
		goto fail;
	}

	atomic_store(&n->monitor_stop, 0);
	if (pthread_create(&n->monitor, NULL, watchdog_thread, n) == 0) {
		n->monitor_started = 1;
	} else {
		fprintf(stderr, "poise: cannot start the watchdog thread\n");
	}
	register_node(n);
	return n;

fail:
	free_node(n);
	return NULL;
}

/* ------------------------------------------------------------------- CLI */

#ifdef POISE_CA_CLI

/* The standalone spike harness: it runs an identity "engine" on a worker thread
 * so the core's exchange, the dry fallback and the counters can be measured
 * without Python. Not part of the library (poise_coreaudio.h). */

#define CLI_WRITER_TICK_MS 50u

enum cli_sample_format {
	CLI_F32, /* 32-bit float WAV (format tag 3) */
	CLI_S16, /* 16-bit PCM WAV (format tag 1) */
};

struct cli_meter {
	FILE *f;
	unsigned rate;
	enum cli_sample_format fmt;
	uint64_t frames;
	float peak;
	double energy;
	float *tail; /* the last second, for the feedback probe */
	uint64_t tail_pos;
	uint64_t tail_filled;
	double tail_energy;
};

static void put16(FILE *f, uint16_t v)
{
	fputc(v & 0xff, f);
	fputc((v >> 8) & 0xff, f);
}

static void put32(FILE *f, uint32_t v)
{
	put16(f, v & 0xffff);
	put16(f, (v >> 16) & 0xffff);
}

static void wav_header(FILE *f, unsigned rate, unsigned channels,
                       enum cli_sample_format fmt, uint64_t frames)
{
	unsigned bits = (fmt == CLI_F32) ? 32 : 16;
	unsigned align = channels * bits / 8;
	uint64_t data = frames * align;
	if (data > 0xffffffffu)
		data = 0xffffffffu;
	fseek(f, 0, SEEK_SET);
	fwrite("RIFF", 1, 4, f);
	put32(f, (uint32_t)(36 + data));
	fwrite("WAVE", 1, 4, f);
	fwrite("fmt ", 1, 4, f);
	put32(f, 16);
	put16(f, (fmt == CLI_F32) ? 3 : 1); /* WAVE_FORMAT_IEEE_FLOAT / PCM */
	put16(f, channels);
	put32(f, rate);
	put32(f, rate * align);
	put16(f, align);
	put16(f, bits);
	fwrite("data", 1, 4, f);
	put32(f, (uint32_t)data);
	fflush(f);
}

/* The meter is created whether or not a WAV is asked for: the run summary and
 * the silence warning come from it (see the note in mac-tap-spike.md about
 * measuring only when recording). */
static int wav_open(struct cli_meter *w, const char *path, unsigned rate,
                    enum cli_sample_format fmt)
{
	memset(w, 0, sizeof(*w));
	w->rate = rate;
	w->fmt = fmt;
	w->tail = calloc((size_t)rate * POISE_COREAUDIO_CHANNELS, sizeof(float));
	if (!path)
		return 1;
	w->f = fopen(path, "wb+");
	if (!w->f) {
		fprintf(stderr, "poise: cannot write %s: %s\n", path, strerror(errno));
		free(w->tail);
		w->tail = NULL;
		return 0;
	}
	wav_header(w->f, rate, POISE_COREAUDIO_CHANNELS, fmt, 0);
	return 1;
}

static void wav_write(struct cli_meter *w, const float *mono, uint32_t frames)
{
	size_t channels = POISE_COREAUDIO_CHANNELS;

	for (uint32_t i = 0; i < frames; i++) {
		float x = mono[i];
		float ax = fabsf(x);
		if (ax > w->peak)
			w->peak = ax;
		w->energy += (double)x * x * (double)channels;
		if (w->tail) {
			size_t at = (size_t)w->tail_pos;
			double old = w->tail[at];
			w->tail_energy += (double)x * x * (double)channels - old * old;
			w->tail[at] = x;
			w->tail_pos = (w->tail_pos + 1) % ((size_t)w->rate * channels);
			if (w->tail_filled < (uint64_t)w->rate * channels)
				w->tail_filled++;
		}
	}
	w->frames += frames;
	if (!w->f)
		return;
	if (w->fmt == CLI_F32) {
		for (uint32_t i = 0; i < frames; i++) {
			fwrite(&mono[i], sizeof(float), 1, w->f);
			fwrite(&mono[i], sizeof(float), 1, w->f);
		}
	} else {
		for (uint32_t i = 0; i < frames; i++) {
			float x = mono[i];
			if (x > 1.0f)
				x = 1.0f;
			if (x < -1.0f)
				x = -1.0f;
			int16_t s = (int16_t)lrintf(x * 32767.0f);
			fwrite(&s, sizeof(s), 1, w->f);
			fwrite(&s, sizeof(s), 1, w->f);
		}
	}
}

static void wav_close(struct cli_meter *w)
{
	if (!w->f)
		return;
	wav_header(w->f, w->rate, POISE_COREAUDIO_CHANNELS, w->fmt, w->frames);
	fclose(w->f);
	w->f = NULL;
	free(w->tail);
	w->tail = NULL;
}

static volatile sig_atomic_t g_stop;

static void on_signal(int sig)
{
	(void)sig;
	g_stop = 1;
}

struct cli_worker {
	struct poise_ca *n;
	poise_core *core;
	uint32_t frame;
	struct cli_meter meter;
	unsigned stall_at_ms; /* when to hold a frame back once (0 = never) */
	unsigned stall_ms;
	_Atomic int stalled;
	_Atomic int stop;
	pthread_t thread;
	int started;
};

/* The identity "engine": take each frame from the core, write it, hand it back.
 * A frame this thread does not hand back in time plays dry at the same delay,
 * which is what --stall-at exercises. */
static void *cli_worker_thread(void *arg)
{
	struct cli_worker *w = arg;
	float *buf = calloc(w->frame, sizeof(float));
	uint64_t start = monotonic_ms_();

	if (!buf)
		return NULL;
	while (!atomic_load(&w->stop)) {
		int64_t k = poise_core_wait_frame(w->core, buf, 100);
		if (k == -2)
			break;
		if (k >= 0) {
			wav_write(&w->meter, buf, w->frame);
			poise_core_put_frame(w->core, k, buf);
		}
		if (w->stall_at_ms && !atomic_load(&w->stalled) &&
		    monotonic_ms_() - start >= w->stall_at_ms) {
			atomic_store(&w->stalled, 1);
			printf("poise: worker holds a frame back for %u ms\n", w->stall_ms);
			fflush(stdout);
			struct timespec ts = { w->stall_ms / 1000,
			                       (long)(w->stall_ms % 1000) * 1000000L };
			nanosleep(&ts, NULL);
		}
	}
	free(buf);
	return NULL;
}

static void cli_worker_start(struct cli_worker *w, struct poise_ca *n,
                             const char *out_path, unsigned rate,
                             enum cli_sample_format fmt, unsigned stall_at_ms,
                             unsigned stall_ms)
{
	memset(w, 0, sizeof(*w));
	w->n = n;
	w->core = poise_ca_core(n);
	w->frame = poise_ca_frame(n);
	w->stall_at_ms = stall_at_ms;
	w->stall_ms = stall_ms;
	atomic_store(&w->stalled, 0);
	atomic_store(&w->stop, 0);
	if (!wav_open(&w->meter, out_path, rate, fmt)) {
		fprintf(stderr, "poise: recording disabled\n");
	}
	if (pthread_create(&w->thread, NULL, cli_worker_thread, w) == 0)
		w->started = 1;
}

static void cli_worker_stop(struct cli_worker *w)
{
	atomic_store(&w->stop, 1);
	poise_core_stop(w->core);
	if (w->started)
		pthread_join(w->thread, NULL);
	w->started = 0;
	wav_close(&w->meter);
}

static float to_dbfs(float x)
{
	if (x <= 1e-6f)
		return -120.0f;
	return 20.0f * log10f(x);
}

static const char *transport_name(UInt32 transport, char buf[8])
{
	switch (transport) {
	case kAudioDeviceTransportTypeBuiltIn: return "built-in";
	case kAudioDeviceTransportTypeUSB: return "usb";
	case kAudioDeviceTransportTypeBluetooth: return "bluetooth";
	case kAudioDeviceTransportTypeBluetoothLE: return "bluetooth-le";
	case kAudioDeviceTransportTypeHDMI: return "hdmi";
	case kAudioDeviceTransportTypeDisplayPort: return "displayport";
	case kAudioDeviceTransportTypeAirPlay: return "airplay";
	case kAudioDeviceTransportTypeAVB: return "avb";
	case kAudioDeviceTransportTypeAggregate: return "aggregate";
	case kAudioDeviceTransportTypeVirtual: return "virtual";
	default: break;
	}
	snprintf(buf, 8, "%c%c%c%c",
	         (char)((transport >> 24) & 0xff), (char)((transport >> 16) & 0xff),
	         (char)((transport >> 8) & 0xff), (char)(transport & 0xff));
	return buf;
}

void poise_ca_list_devices(void)
{
	UInt32 count = 0;
	AudioObjectID *devs = hal_device_list(&count);
	for (UInt32 i = 0; i < count; i++) {
		char name[256] = "";
		char uid[256] = "";
		char tbuf[8];
		UInt32 transport = 0;
		UInt32 tsize = sizeof(transport);
		double rate = 0;
		UInt32 size = sizeof(rate);
		hal_get_string(devs[i], kAudioObjectPropertyName, kAudioObjectPropertyScopeGlobal, name,
		               sizeof(name));
		hal_get_string(devs[i], kAudioDevicePropertyDeviceUID, kAudioObjectPropertyScopeGlobal, uid,
		               sizeof(uid));
		hal_get(devs[i], kAudioDevicePropertyTransportType, kAudioObjectPropertyScopeGlobal,
		        &transport, &tsize);
		hal_get(devs[i], kAudioDevicePropertyNominalSampleRate, kAudioObjectPropertyScopeGlobal,
		        &rate, &size);
		printf("%-40s %-8s %7.0f Hz  out=%s  uid=%s\n", name,
		       transport_name(transport, tbuf), rate,
		       device_has_output(devs[i]) ? "yes" : "no", uid);
	}
	free(devs);
}

static void usage(void)
{
	printf("usage: poise_coreaudio --seconds N [--out file.wav] [--passthrough]\n"
	       "                       [--device NAME] [--rate HZ] [--format f32|s16] [--verbose]\n"
	       "                       [--frame N] [--margin N] [--engine-latency N]\n"
	       "                       [--stall-at MS --stall-ms MS]\n"
	       "       poise_coreaudio --list-devices\n"
	       "\n"
	       "  --seconds 0   run until SIGINT/SIGTERM\n"
	       "  --stall-at    hold one frame back after MS (shows the dry fallback)\n"
	       "  --passthrough accepted for old measurement commands: the node always\n"
	       "                plays what the core gives it\n");
}

int main(int argc, char **argv)
{
	@autoreleasepool {
		const char *device = NULL;
		const char *out_path = NULL;
		unsigned seconds = 5;
		unsigned rate = POISE_COREAUDIO_RATE;
		unsigned frame = 512;
		unsigned margin = 256;
		unsigned engine_latency = 0;
		unsigned quantum = 512;
		unsigned fade = 64;
		unsigned stall_at = 0;
		unsigned stall_ms = 0;
		enum cli_sample_format fmt = CLI_F32;
		int list = 0;
		int verbose = 0;
		int passthrough = 0;

		for (int i = 1; i < argc; i++) {
			if (!strcmp(argv[i], "--seconds") && i + 1 < argc) {
				seconds = (unsigned)strtoul(argv[++i], NULL, 10);
			} else if (!strcmp(argv[i], "--out") && i + 1 < argc) {
				out_path = argv[++i];
			} else if (!strcmp(argv[i], "--passthrough")) {
				passthrough = 1;
			} else if (!strcmp(argv[i], "--device") && i + 1 < argc) {
				device = argv[++i];
			} else if (!strcmp(argv[i], "--rate") && i + 1 < argc) {
				rate = (unsigned)strtoul(argv[++i], NULL, 10);
			} else if (!strcmp(argv[i], "--frame") && i + 1 < argc) {
				frame = (unsigned)strtoul(argv[++i], NULL, 10);
			} else if (!strcmp(argv[i], "--margin") && i + 1 < argc) {
				margin = (unsigned)strtoul(argv[++i], NULL, 10);
			} else if (!strcmp(argv[i], "--engine-latency") && i + 1 < argc) {
				engine_latency = (unsigned)strtoul(argv[++i], NULL, 10);
			} else if (!strcmp(argv[i], "--stall-at") && i + 1 < argc) {
				stall_at = (unsigned)strtoul(argv[++i], NULL, 10);
			} else if (!strcmp(argv[i], "--stall-ms") && i + 1 < argc) {
				stall_ms = (unsigned)strtoul(argv[++i], NULL, 10);
			} else if (!strcmp(argv[i], "--format") && i + 1 < argc) {
				const char *f = argv[++i];
				if (!strcmp(f, "s16"))
					fmt = CLI_S16;
				else if (!strcmp(f, "f32"))
					fmt = CLI_F32;
				else {
					fprintf(stderr, "poise: unknown --format %s\n", f);
					return 1;
				}
			} else if (!strcmp(argv[i], "--verbose") || !strcmp(argv[i], "-v")) {
				verbose = 1;
			} else if (!strcmp(argv[i], "--list-devices")) {
				list = 1;
			} else if (!strcmp(argv[i], "--help") || !strcmp(argv[i], "-h")) {
				usage();
				return 0;
			} else {
				fprintf(stderr, "poise: unknown argument %s\n", argv[i]);
				usage();
				return 1;
			}
		}

		if (list) {
			poise_ca_list_devices();
			return 0;
		}

		struct sigaction sa;
		memset(&sa, 0, sizeof(sa));
		sa.sa_handler = on_signal;
		sigaction(SIGINT, &sa, NULL);
		sigaction(SIGTERM, &sa, NULL);

		printf("poise: macOS %s, node with the fixed-delay core (poise_core %u stats)\n",
		       [[[NSProcessInfo processInfo] operatingSystemVersionString] UTF8String],
		       (unsigned)poise_core_stat_count());
		if (passthrough)
			printf("poise: --passthrough: the node always plays what the core gives it\n");
		fflush(stdout);

		char err[1024] = "";
		struct poise_ca *n = poise_ca_new(device, frame, engine_latency, quantum, margin,
		                                  fade, 1.0f, rate, 1, err, sizeof(err));
		if (!n) {
			fprintf(stderr, "poise: %s\n", err);
			return 2;
		}
		if (verbose) {
			printf("poise: RT policy: %s\n",
			       atomic_load(&n->c.rt_policy_set) ? "time-constraint" : "not set");
		}

		struct cli_worker worker;
		cli_worker_start(&worker, n, out_path, rate, fmt, stall_at, stall_ms);

		struct timespec t0, t1;
		clock_gettime(CLOCK_MONOTONIC, &t0);
		unsigned elapsed_ms = 0;
		while (!g_stop) {
			if (seconds && elapsed_ms >= seconds * 1000u)
				break;
			struct timespec ts = { 0, 50 * 1000000L };
			nanosleep(&ts, NULL);
			elapsed_ms += 50;
			char msg[512];
			if (poise_ca_status(n, msg, sizeof(msg))) {
				fprintf(stderr, "poise: %s\n", msg);
				break;
			}
		}
		clock_gettime(CLOCK_MONOTONIC, &t1);
		double wall = (double)(t1.tv_sec - t0.tv_sec) + (double)(t1.tv_nsec - t0.tv_nsec) / 1e9;

		uint64_t st[POISE_CA_STAT_COUNT];
		poise_ca_get_stats(n, st, POISE_CA_STAT_COUNT);
		uint64_t delay = poise_ca_delay_samples(n);
		uint64_t io = poise_ca_io_latency_samples(n);
		int64_t in_adv = atomic_load(&n->c.last_in_time) - atomic_load(&n->c.first_in_time);
		int64_t out_adv = atomic_load(&n->c.last_out_time) - atomic_load(&n->c.first_out_time);
		int has_time = atomic_load(&n->c.has_time);
		cli_worker_stop(&worker);
		poise_ca_destroy(n);

		struct cli_meter *w = &worker.meter;
		double in_s = (double)st[POISE_CA_INPUT_FRAMES] / rate;
		double out_s = (double)st[POISE_CA_OUTPUT_FRAMES] / rate;
		double ppm = st[POISE_CA_INPUT_FRAMES]
		                 ? (double)((int64_t)st[POISE_CA_OUTPUT_FRAMES] -
		                            (int64_t)st[POISE_CA_INPUT_FRAMES]) /
		                       (double)st[POISE_CA_INPUT_FRAMES] * 1e6
		                 : 0.0;
		double ms_per_sample = 1000.0 / (double)rate;
		float rms = w->frames ? (float)sqrt(w->energy /
		                                    ((double)w->frames * POISE_COREAUDIO_CHANNELS))
		                      : 0.0f;
		double n_tail = (double)w->tail_filled;
		float tail = n_tail > 0 ? (float)sqrt(fmax(w->tail_energy, 0.0) / n_tail) : 0.0f;

		printf("poise: wall %.2f s; tap delivered %llu frames (%.3f s), output played %llu frames "
		       "(%.3f s)\n",
		       wall, (unsigned long long)st[POISE_CA_INPUT_FRAMES], in_s,
		       (unsigned long long)st[POISE_CA_OUTPUT_FRAMES], out_s);
		printf("poise: drift output-tap %+lld frames, %+.2f ppm\n",
		       (long long)((int64_t)st[POISE_CA_OUTPUT_FRAMES] -
		                   (int64_t)st[POISE_CA_INPUT_FRAMES]), ppm);
		{
			double clock_ppm = in_adv ? (double)(out_adv - in_adv) / (double)in_adv * 1e6 : 0.0;
			if (has_time)
				printf("poise: clocks: tap advanced %lld samples, output advanced %lld samples over "
				       "the same %llu callbacks: %+lld samples, %+.2f ppm\n",
				       (long long)in_adv, (long long)out_adv,
				       (unsigned long long)st[POISE_CA_CALLBACKS],
				       (long long)(out_adv - in_adv), clock_ppm);
		}
		printf("poise: callbacks %llu, quantum max %llu frames\n",
		       (unsigned long long)st[POISE_CA_CALLBACKS],
		       (unsigned long long)st[POISE_CA_QUANTUM_MAX]);
		printf("poise: frames processed %llu (wet), dry %llu, skipped %llu, late %llu\n",
		       (unsigned long long)st[POISE_CA_FRAMES_WET],
		       (unsigned long long)st[POISE_CA_FRAMES_DRY],
		       (unsigned long long)st[POISE_CA_FRAMES_SKIPPED],
		       (unsigned long long)st[POISE_CA_FRAMES_LATE]);
		printf("poise: dropped %llu frames; overloads %llu; delay changes %llu; resyncs %llu; "
		       "input gaps %llu\n",
		       (unsigned long long)st[POISE_CA_DROPPED],
		       (unsigned long long)st[POISE_CA_OVERLOADS],
		       (unsigned long long)st[POISE_CA_DELAY_CHANGES],
		       (unsigned long long)st[POISE_CA_RESYNCS],
		       (unsigned long long)st[POISE_CA_INPUT_GAPS]);
		printf("poise: delay %llu samples (%.1f ms); device side %llu samples (%.1f ms); total "
		       "added %.1f ms (engine delay excluded)\n",
		       (unsigned long long)delay, (double)delay * ms_per_sample,
		       (unsigned long long)io, (double)io * ms_per_sample,
		       (double)(delay + io) * ms_per_sample);
		printf("poise: capture health: saw_signal %llu, quiet frames %llu (capture health)\n",
		       (unsigned long long)st[POISE_CA_SAW_SIGNAL],
		       (unsigned long long)st[POISE_CA_QUIET_FRAMES]);
		printf("poise: played: peak %.1f dBFS, rms %.1f dBFS, last-second rms %.1f dBFS\n",
		       to_dbfs(w->peak), to_dbfs(rms), to_dbfs(tail));
		printf("poise: RT policy: %s\n",
		       st[POISE_CA_RT_POLICY] ? "time-constraint" : "not set");
		if (out_path)
			printf("poise: wrote %s\n", out_path);
		if (!st[POISE_CA_INPUT_FRAMES]) {
			fprintf(stderr, "poise: no frames at all: the tap was never read\n");
			return 4;
		}
		if (!st[POISE_CA_SAW_SIGNAL]) {
			fprintf(stderr,
			        "poise: captured only silence: either nothing was playing, or the System Audio "
			        "Recording grant is missing\n");
			return 5;
		}
	}
	return 0;
}

#endif /* POISE_CA_CLI */
