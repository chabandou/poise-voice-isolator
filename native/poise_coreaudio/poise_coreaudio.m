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
 *                            |  non-interleaved stream format on both sides
 *                     one IOProc (THREAD_TIME_CONSTRAINT_POLICY)
 *                            |
 *                capture ring -> WAV (the spike) / poise_core (T4)
 *                            |
 *              passthrough: the same buffers go to the output buffers
 *
 * Why the format is set, not negotiated: Core Audio has no AUTOCONVERTPCM
 * (poise_wasapi.c asks WASAPI for it); the aggregate's stream format is what
 * the IOProc sees, and the HAL resamples the physical device to it. So the
 * node always runs at 48 kHz, and a device that will not take that format is
 * refused rather than run at another rate (plan C2).
 *
 * Why the tap must not outlive the process: with MutedWhenTapped, the tap
 * silences every app's audio while it is being read. It is destroyed on the
 * normal path, on SIGINT/SIGTERM and from atexit (plan C1).
 *
 * The mute is released by AudioDeviceStop(): MutedWhenTapped mutes only while
 * the tap is read, so the order here is stop the device, destroy the IOProc,
 * the aggregate, then the tap. Destroying the tap first would leave a live
 * aggregate pointing at a dead object (the HAL refuses), and the aggregate
 * cannot be destroyed while its device runs, so this is the only order that
 * always ends with no tap and no silence.
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

#define TAP_NAME "Poise Tap Spike"
#define AGGREGATE_NAME "Poise Tap Spike"
#define SCRATCH_FRAMES 8192u      /* largest callback handled in one go */
#define RING_SECONDS 4u           /* capture ring depth */
#define WRITER_TICK_MS 50u
#define TCC_WAIT_SECONDS 180u
#define TCC_RETRY_MS 3000u

static volatile sig_atomic_t g_stop;

struct poise_mac_atomic_counters {
	_Atomic uint64_t input_frames;
	_Atomic uint64_t output_frames;
	_Atomic uint64_t callbacks;
	_Atomic uint64_t quantum_min;
	_Atomic uint64_t quantum_max;
	_Atomic uint64_t dropped_frames;
	_Atomic uint64_t overloads;
	_Atomic int rt_policy_set;
	/* Clocks: the tap's time stamp is in the tap's clock domain, the output's in
	 * the output device's. Their rates differ, which is what drift means here. */
	_Atomic int64_t first_in_time;
	_Atomic int64_t last_in_time;
	_Atomic int64_t first_out_time;
	_Atomic int64_t last_out_time;
	_Atomic int64_t delta_min;
	_Atomic int64_t delta_max;
	_Atomic int has_time;
};

struct poise_ring {
	float *frames; /* interleaved stereo */
	uint64_t capacity;
	_Atomic uint64_t head; /* frames pushed */
	_Atomic uint64_t tail; /* frames popped */
};

struct poise_wav {
	FILE *f;
	unsigned rate;
	unsigned channels;
	enum poise_mac_sample_format fmt;
	uint64_t frames;
	float peak;
	double energy;
	float *tail; /* the last second, for the feedback probe */
	uint64_t tail_pos;
	uint64_t tail_filled;
	double tail_energy;
};

struct poise_mac_session {
	struct poise_mac_session_config cfg;
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
	int tap_format_settable;
	int started;
	int policy_verified;          /* THREAD_TIME_CONSTRAINT_POLICY read back */
	uint32_t policy_period;
	uint32_t policy_computation;
	uint32_t policy_constraint;
	uint32_t policy_preemptible;
	uint32_t time_flags_in;
	uint32_t time_flags_out;
	struct poise_mac_atomic_counters c;
	struct poise_ring ring;
	struct poise_wav wav;
	pthread_t writer;
	_Atomic int writer_stop;
	float *scratch;
};


/* ---------------------------------------------------------------- helpers */

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

/* ------------------------------------------------------------------- ring */

static void ring_init(struct poise_ring *r, unsigned rate, unsigned seconds)
{
	r->capacity = (uint64_t)rate * seconds;
	r->frames = calloc((size_t)r->capacity * POISE_COREAUDIO_CHANNELS, sizeof(float));
	atomic_store(&r->head, 0);
	atomic_store(&r->tail, 0);
}

static void ring_free(struct poise_ring *r)
{
	free(r->frames);
	r->frames = NULL;
}

static uint64_t ring_space(const struct poise_ring *r)
{
	uint64_t head = atomic_load_explicit(&r->head, memory_order_relaxed);
	uint64_t tail = atomic_load_explicit(&r->tail, memory_order_acquire);
	return r->capacity - (head - tail);
}

static void ring_push(struct poise_ring *r, const float *src, uint32_t frames,
                      _Atomic uint64_t *dropped)
{
	if (!r->frames)
		return;
	uint64_t space = ring_space(r);
	uint32_t take = frames;
	if (take > space) {
		atomic_fetch_add(dropped, frames - space);
		take = (uint32_t)space;
	}
	uint64_t head = atomic_load_explicit(&r->head, memory_order_relaxed);
	for (uint32_t i = 0; i < take; i++) {
		uint64_t at = (head + i) % r->capacity;
		r->frames[at * 2 + 0] = src[i * 2 + 0];
		r->frames[at * 2 + 1] = src[i * 2 + 1];
	}
	atomic_store_explicit(&r->head, head + take, memory_order_release);
}

static uint32_t ring_pop(struct poise_ring *r, float *dst, uint32_t frames)
{
	if (!r->frames)
		return 0;
	uint64_t head = atomic_load_explicit(&r->head, memory_order_acquire);
	uint64_t tail = atomic_load_explicit(&r->tail, memory_order_relaxed);
	uint64_t used = head - tail;
	uint32_t take = frames;
	if (take > used)
		take = (uint32_t)used;
	for (uint32_t i = 0; i < take; i++) {
		uint64_t at = (tail + i) % r->capacity;
		dst[i * 2 + 0] = r->frames[at * 2 + 0];
		dst[i * 2 + 1] = r->frames[at * 2 + 1];
	}
	atomic_store_explicit(&r->tail, tail + take, memory_order_release);
	return take;
}

/* -------------------------------------------------------------------- WAV */

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
                       enum poise_mac_sample_format fmt, uint64_t frames)
{
	unsigned bits = (fmt == POISE_MAC_F32) ? 32 : 16;
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
	put16(f, (fmt == POISE_MAC_F32) ? 3 : 1); /* WAVE_FORMAT_IEEE_FLOAT / PCM */
	put16(f, channels);
	put32(f, rate);
	put32(f, rate * align);
	put16(f, align);
	put16(f, bits);
	fwrite("data", 1, 4, f);
	put32(f, (uint32_t)data);
	fflush(f);
}

static int wav_open(struct poise_wav *w, const char *path, unsigned rate,
                    enum poise_mac_sample_format fmt)
{
	memset(w, 0, sizeof(*w));
	w->rate = rate;
	w->channels = POISE_COREAUDIO_CHANNELS;
	w->fmt = fmt;
	w->tail = calloc((size_t)rate * w->channels, sizeof(float));
	/* No path: a meter-only instance. The levels below are what the run
	 * summary and the silence warning report, so they must be measured
	 * whether or not a WAV was asked for. */
	if (!path)
		return 1;
	w->f = fopen(path, "wb+");
	if (!w->f) {
		fprintf(stderr, "poise: cannot write %s: %s\n", path, strerror(errno));
		free(w->tail);
		w->tail = NULL;
		return 0;
	}
	wav_header(w->f, rate, w->channels, fmt, 0);
	return 1;
}

static void wav_write(struct poise_wav *w, const float *src, uint32_t frames)
{
	if (!frames)
		return;
	size_t samples = (size_t)frames * w->channels;
	for (size_t i = 0; i < samples; i++) {
		float x = src[i];
		float ax = fabsf(x);
		if (ax > w->peak)
			w->peak = ax;
		w->energy += (double)x * x;
		if (w->tail) {
			double old = w->tail[w->tail_pos];
			w->tail_energy += (double)x * x - old * old;
			w->tail[w->tail_pos] = x;
			w->tail_pos = (w->tail_pos + 1) % ((size_t)w->rate * w->channels);
			if (w->tail_filled < (uint64_t)w->rate * w->channels)
				w->tail_filled++;
		}
	}
	w->frames += frames;
	if (!w->f)
		return; /* meter only: nothing to write */
	if (w->fmt == POISE_MAC_F32) {
		fwrite(src, sizeof(float), samples, w->f);
	} else {
		static int16_t *pcm;
		static size_t pcm_cap;
		if (pcm_cap < samples) {
			free(pcm);
			pcm_cap = samples * 2;
			pcm = malloc(pcm_cap * sizeof(int16_t));
		}
		for (size_t i = 0; i < samples; i++) {
			float x = src[i];
			if (x > 1.0f)
				x = 1.0f;
			if (x < -1.0f)
				x = -1.0f;
			pcm[i] = (int16_t)lrintf(x * 32767.0f);
		}
		fwrite(pcm, sizeof(int16_t), samples, w->f);
	}
}

static void wav_close(struct poise_wav *w)
{
	if (!w->f)
		return;
	wav_header(w->f, w->rate, w->channels, w->fmt, w->frames);
	fclose(w->f);
	w->f = NULL;
	free(w->tail);
	w->tail = NULL;
}

/* ---------------------------------------------------------- buffer layouts */

/* Copies one chunk of a Core Audio buffer list into interleaved stereo. Returns
 * 0 for a layout this spike does not handle (2x mono or 1x stereo only). */
static int abl_read(const AudioBufferList *abl, float *dst, uint32_t frames,
                    uint64_t offset)
{
	if (!abl || abl->mNumberBuffers == 0)
		return 0;
	/* Never write past the buffer the HAL handed us: truncate instead. */
	for (UInt32 i = 0; i < abl->mNumberBuffers; i++) {
		uint32_t ch = abl->mBuffers[i].mNumberChannels
		                  ? abl->mBuffers[i].mNumberChannels : 1;
		uint64_t cap = (uint64_t)abl->mBuffers[i].mDataByteSize /
		               (sizeof(float) * ch);
		if ((uint64_t)offset >= cap)
			return 0;
		if ((uint64_t)offset + frames > cap)
			frames = (uint32_t)(cap - (uint64_t)offset);
	}
	if (!frames)
		return 0;
	if (abl->mNumberBuffers == 1 && abl->mBuffers[0].mNumberChannels == 2) {
		const float *src = (const float *)abl->mBuffers[0].mData + offset * 2;
		memcpy(dst, src, (size_t)frames * 2 * sizeof(float));
		return 1;
	}
	if (abl->mNumberBuffers >= 2 && abl->mBuffers[0].mNumberChannels == 1 &&
	    abl->mBuffers[1].mNumberChannels == 1) {
		const float *l = (const float *)abl->mBuffers[0].mData + offset;
		const float *r = (const float *)abl->mBuffers[1].mData + offset;
		for (uint32_t i = 0; i < frames; i++) {
			dst[i * 2 + 0] = l[i];
			dst[i * 2 + 1] = r[i];
		}
		return 1;
	}
	if (abl->mNumberBuffers == 1 && abl->mBuffers[0].mNumberChannels == 1) {
		const float *m = (const float *)abl->mBuffers[0].mData + offset;
		for (uint32_t i = 0; i < frames; i++) {
			dst[i * 2 + 0] = m[i];
			dst[i * 2 + 1] = m[i];
		}
		return 1;
	}
	return 0;
}

static int abl_write(AudioBufferList *abl, const float *src, uint32_t frames,
                     uint64_t offset)
{
	if (!abl || abl->mNumberBuffers == 0)
		return 0;
	if (abl->mNumberBuffers == 1 && abl->mBuffers[0].mNumberChannels == 2) {
		float *dst = (float *)abl->mBuffers[0].mData + offset * 2;
		memcpy(dst, src, (size_t)frames * 2 * sizeof(float));
		return 1;
	}
	if (abl->mNumberBuffers >= 2 && abl->mBuffers[0].mNumberChannels == 1 &&
	    abl->mBuffers[1].mNumberChannels == 1) {
		float *l = (float *)abl->mBuffers[0].mData + offset;
		float *r = (float *)abl->mBuffers[1].mData + offset;
		for (uint32_t i = 0; i < frames; i++) {
			l[i] = src[i * 2 + 0];
			r[i] = src[i * 2 + 1];
		}
		return 1;
	}
	if (abl->mNumberBuffers == 1 && abl->mBuffers[0].mNumberChannels == 1) {
		float *m = (float *)abl->mBuffers[0].mData + offset;
		for (uint32_t i = 0; i < frames; i++)
			m[i] = 0.5f * (src[i * 2 + 0] + src[i * 2 + 1]);
		return 1;
	}
	return 0;
}

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

/* ---------------------------------------------------------------- IOProc */

/* The analogue of the Windows MMCSS "Pro Audio" path: ask for a time-constraint
 * thread sized to one callback. Set once, from the first callback, because
 * Core Audio has no thread-start hook. */
static void set_realtime_policy(struct poise_mac_session *s, uint32_t frames)
{
	double rate = s->cfg.rate;
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
	if (kr == KERN_SUCCESS) {
		atomic_store(&s->c.rt_policy_set, 1);
	} else {
		fprintf(stderr, "poise: thread_policy_set(THREAD_TIME_CONSTRAINT_POLICY): kr=%d\n",
		        (int)kr);
	}
}

static OSStatus ioproc(AudioObjectID dev, const AudioTimeStamp *now,
                       const AudioBufferList *inInputData, const AudioTimeStamp *inInputTime,
                       AudioBufferList *outOutputData, const AudioTimeStamp *inOutputTime,
                       void *ctx)
{
	struct poise_mac_session *s = ctx;
	(void)dev;
	(void)now;

	uint32_t in_frames = abl_frames(inInputData);
	uint32_t out_frames = abl_frames(outOutputData);

	uint64_t call = atomic_fetch_add(&s->c.callbacks, 1);
	if (call == 0 && in_frames)
		set_realtime_policy(s, in_frames);
	if (call == 1) {
		/* Read the policy back once, to prove it took rather than trusting the
		 * return value. */
		thread_time_constraint_policy_data_t got;
		mach_msg_type_number_t count = THREAD_TIME_CONSTRAINT_POLICY_COUNT;
		boolean_t get_default = 0;
		kern_return_t kr = thread_policy_get(mach_thread_self(), THREAD_TIME_CONSTRAINT_POLICY,
		                                     (thread_policy_t)&got, &count, &get_default);
		if (kr == KERN_SUCCESS) {
			s->policy_period = got.period;
			s->policy_computation = got.computation;
			s->policy_constraint = got.constraint;
			s->policy_preemptible = got.preemptible;
			s->policy_verified = 1;
		}
	}
	atomic_fetch_add(&s->c.input_frames, in_frames);
	atomic_fetch_add(&s->c.output_frames, out_frames);
	if (in_frames) {
		uint64_t min = atomic_load(&s->c.quantum_min);
		if (!min || in_frames < min)
			atomic_store(&s->c.quantum_min, in_frames);
		if (in_frames > atomic_load(&s->c.quantum_max))
			atomic_store(&s->c.quantum_max, in_frames);
	}

	/* Clock domains: the tap's time stamp is the tap's clock, the output's is
	 * the output device's. Their rates differ; that is the drift (probe (d)). */
	if (inInputTime && inOutputTime) {
		int64_t in_t = (int64_t)llround(inInputTime->mSampleTime);
		int64_t out_t = (int64_t)llround(inOutputTime->mSampleTime);
		if (!atomic_load(&s->c.has_time)) {
			s->time_flags_in = inInputTime->mFlags;
			s->time_flags_out = inOutputTime->mFlags;
			atomic_store(&s->c.first_in_time, in_t);
			atomic_store(&s->c.first_out_time, out_t);
			atomic_store(&s->c.delta_min, out_t - in_t);
			atomic_store(&s->c.delta_max, out_t - in_t);
			atomic_store(&s->c.has_time, 1);
		}
		atomic_store(&s->c.last_in_time, in_t);
		atomic_store(&s->c.last_out_time, out_t);
		if (out_t - in_t < atomic_load(&s->c.delta_min))
			atomic_store(&s->c.delta_min, out_t - in_t);
		if (out_t - in_t > atomic_load(&s->c.delta_max))
			atomic_store(&s->c.delta_max, out_t - in_t);
	}

	uint32_t frames = in_frames;
	if (frames > SCRATCH_FRAMES) {
		atomic_fetch_add(&s->c.overloads, 1);
		frames = SCRATCH_FRAMES;
	}
	for (uint32_t done = 0; done < frames;) {
		uint32_t chunk = frames - done;
		if (chunk > 1024)
			chunk = 1024;
		if (!abl_read(inInputData, s->scratch, chunk, done)) {
			atomic_fetch_add(&s->c.overloads, 1);
			break;
		}
		ring_push(&s->ring, s->scratch, chunk, &s->c.dropped_frames);
		/* The output buffer can be SHORTER than what the tap delivered (a
		 * device start/stop transition, or a device whose output quantum is
		 * smaller than the tap's). Writing in_frames there would run past the
		 * HAL's buffer inside the realtime callback. */
		if (s->cfg.passthrough && outOutputData && done < out_frames) {
			uint32_t room = out_frames - done;
			abl_write(outOutputData, s->scratch,
			          chunk < room ? chunk : room, done);
		}
		done += chunk;
	}
	/* With pass-through the output must be filled for the whole callback even
	 * if the tap delivered less. */
	if (s->cfg.passthrough && outOutputData && out_frames > frames) {
		uint32_t from = frames;
		while (from < out_frames) {
			uint32_t chunk = out_frames - from;
			if (chunk > SCRATCH_FRAMES)
				chunk = SCRATCH_FRAMES;
			memset(s->scratch, 0, (size_t)chunk * 2 * sizeof(float));
			abl_write(outOutputData, s->scratch, chunk, from);
			from += chunk;
		}
	}
	return noErr;
}

static void *writer_thread(void *arg)
{
	struct poise_mac_session *s = arg;
	float buf[1024 * 2];
	uint32_t n;
	for (;;) {
		while ((n = ring_pop(&s->ring, buf, 1024)) > 0)
			wav_write(&s->wav, buf, n);
		if (atomic_load(&s->writer_stop) &&
		    atomic_load(&s->ring.head) == atomic_load(&s->ring.tail))
			break;
		struct timespec ts;
		ts.tv_sec = 0;
		ts.tv_nsec = WRITER_TICK_MS * 1000000L;
		nanosleep(&ts, NULL);
	}
	return NULL;
}

/* --------------------------------------------------------------- the tap */

static OSStatus create_tap(struct poise_mac_session *s, AudioObjectID *tap)
{
	/* Poise's own process is excluded so the node never re-captures its own
	 * output: the aggregate writes the same audio it reads, so including self
	 * would close a loop (plan probe (e)). */
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
	desc.muteBehavior = CATapMutedWhenTapped;
	desc.privateTap = NO;
	desc.mixdown = YES;
	desc.mono = NO;
	desc.exclusive = YES;
	if (s->cfg.verbose) {
		printf("poise: tap: stereo mixdown, exclude self pid %d (process object %u), "
		       "muteBehavior=MutedWhenTapped, private=no\n", (int)pid, (unsigned)self);
	}
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

static OSStatus set_stream_formats(struct poise_mac_session *s, AudioObjectPropertyScope scope,
                                   AudioStreamBasicDescription *readback, const char *what)
{
	UInt32 size = hal_data_size(s->aggregate_id, kAudioDevicePropertyStreams, scope);
	if (!size) {
		report_status(what, kAudioHardwareBadObjectError);
		return kAudioHardwareBadObjectError;
	}
	AudioStreamID *streams = calloc(1, size);
	if (!streams)
		return kAudioHardwareUnspecifiedError;
	if (hal_get(s->aggregate_id, kAudioDevicePropertyStreams, scope, streams, &size) != noErr) {
		free(streams);
		return kAudioHardwareUnspecifiedError;
	}
	UInt32 count = size / sizeof(AudioStreamID);
	OSStatus result = noErr;
	OSStatus st;
	for (UInt32 i = 0; i < count; i++) {
		st = hal_set(streams[i], kAudioStreamPropertyVirtualFormat, kAudioObjectPropertyScopeGlobal,
		             &s->requested, sizeof(s->requested));
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

static OSStatus create_aggregate(struct poise_mac_session *s, const char *tapuid)
{
	char outuid[256] = "";
	hal_get_string(s->output_device, kAudioDevicePropertyDeviceUID, kAudioObjectPropertyScopeGlobal,
	               outuid, sizeof(outuid));
	if (!outuid[0]) {
		fprintf(stderr, "poise: output device has no UID\n");
		return kAudioHardwareBadObjectError;
	}

	NSString *aggUID = [NSString stringWithFormat:@"dev.poise.spike.%@", [[NSUUID UUID] UUIDString]];
	NSDictionary *subDevice = @{ @kAudioSubDeviceUIDKey : @(outuid) };
	NSDictionary *tapEntry = @{
		@kAudioSubTapUIDKey : @(tapuid),
		/* Per-sub-tap drift compensation: the tap's clock and the output device's
		 * clock are not the same clock, so the HAL must resample one of them. */
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
	                                                 &s->aggregate_id);
	if (st != noErr) {
		report_status("AudioHardwareCreateAggregateDevice", st);
		/* The clock-device key is the one the API is least forgiving about; retry
		 * without it, since the main sub-device is already the clock master. */
		NSMutableDictionary *retry = [desc mutableCopy];
		[retry removeObjectForKey:@kAudioAggregateDeviceClockDeviceKey];
		st = AudioHardwareCreateAggregateDevice((__bridge CFDictionaryRef)retry,
		                                        &s->aggregate_id);
		if (st != noErr) {
			report_status("AudioHardwareCreateAggregateDevice (no clock key)", st);
			return st;
		}
		fprintf(stderr, "poise: aggregate accepted only without the explicit clock device\n");
	}
	return noErr;
}

static void read_back_aggregate(struct poise_mac_session *s)
{
	/* Clock master, as the HAL sees it. */
	CFStringRef clock = NULL;
	UInt32 size = sizeof(clock);
	AudioObjectPropertyAddress a = { kAudioAggregateDevicePropertyClockDevice,
	                                 kAudioObjectPropertyScopeGlobal,
	                                 kAudioObjectPropertyElementMain };
	if (AudioObjectGetPropertyData(s->aggregate_id, &a, 0, NULL, &size, &clock) == noErr && clock) {
		cfstring_copy(clock, s->clock_uid, sizeof(s->clock_uid));
		CFRelease(clock);
	}

	/* Composition, as the HAL built it: shows whether the tap survived. */
	if (s->cfg.verbose) {
		CFDictionaryRef comp = NULL;
		UInt32 csize = sizeof(comp);
		AudioObjectPropertyAddress ca = { kAudioAggregateDevicePropertyComposition,
		                                  kAudioObjectPropertyScopeGlobal,
		                                  kAudioObjectPropertyElementMain };
		if (AudioObjectGetPropertyData(s->aggregate_id, &ca, 0, NULL, &csize, &comp) == noErr && comp) {
			printf("poise: aggregate composition: %s\n",
			       [[(__bridge NSDictionary *)comp description] UTF8String]);
			CFRelease(comp);
		}
	}

	/* Per-sub-tap drift compensation, as read back. */
	AudioObjectID *subtaps = NULL;
	size = 0;
	a.mSelector = kAudioAggregateDevicePropertySubTapList;
	if (AudioObjectGetPropertyDataSize(s->aggregate_id, &a, 0, NULL, &size) == noErr && size) {
		subtaps = calloc(1, size);
		if (subtaps &&
		    AudioObjectGetPropertyData(s->aggregate_id, &a, 0, NULL, &size, subtaps) == noErr) {
			UInt32 count = size / sizeof(AudioObjectID);
			for (UInt32 i = 0; i < count; i++) {
				UInt32 value = 0;
				UInt32 vsize = sizeof(value);
				AudioObjectPropertyAddress d = { kAudioSubTapPropertyDriftCompensation,
				                                 kAudioObjectPropertyScopeGlobal,
				                                 kAudioObjectPropertyElementMain };
				OSStatus dst = AudioObjectGetPropertyData(subtaps[i], &d, 0, NULL, &vsize, &value);
				if (dst == noErr) {
					s->drift_compensation = value;
				} else if (s->cfg.verbose) {
					char what[128];
					snprintf(what, sizeof(what), "sub-tap %u: read kAudioSubTapPropertyDriftCompensation",
					         (unsigned)i);
					report_status(what, dst);
				}
				if (s->cfg.verbose) {
					UInt32 quality = 0;
					UInt32 qsize = sizeof(quality);
					AudioObjectPropertyAddress q = { kAudioSubTapPropertyDriftCompensationQuality,
					                                 kAudioObjectPropertyScopeGlobal,
					                                 kAudioObjectPropertyElementMain };
					OSStatus qst = AudioObjectGetPropertyData(subtaps[i], &q, 0, NULL, &qsize, &quality);
					printf("poise: sub-tap %u drift compensation %u (quality read st=%d value=%u)\n",
					       (unsigned)i, (unsigned)value, (int)qst, (unsigned)quality);
				}
			}
		}
		free(subtaps);
	}
}

/* --------------------------------------------------------------- session */

void poise_mac_request_stop(void)
{
	g_stop = 1;
}

struct poise_mac_session *poise_mac_session_start(const struct poise_mac_session_config *cfg,
                                                  char *err, size_t err_size)
{
	struct poise_mac_session *s = calloc(1, sizeof(*s));
	if (!s) {
		snprintf(err, err_size, "out of memory");
		return NULL;
	}
	s->cfg = *cfg;
	s->requested = make_format(cfg->rate);
	s->output_device = find_output_device(cfg->output_device);
	if (!s->output_device) {
		snprintf(err, err_size, "no output device matches \"%s\"",
		         cfg->output_device ? cfg->output_device : "default");
		goto fail;
	}
	{
		char name[256] = "";
		char uid[256] = "";
		hal_get_string(s->output_device, kAudioObjectPropertyName, kAudioObjectPropertyScopeGlobal,
		               name, sizeof(name));
		hal_get_string(s->output_device, kAudioDevicePropertyDeviceUID, kAudioObjectPropertyScopeGlobal,
		               uid, sizeof(uid));
		UInt32 size = sizeof(s->device_nominal_rate);
		hal_get(s->output_device, kAudioDevicePropertyNominalSampleRate,
		        kAudioObjectPropertyScopeGlobal, &s->device_nominal_rate, &size);
		AudioStreamID first = 0;
		UInt32 fsize = sizeof(first);
		if (hal_get(s->output_device, kAudioDevicePropertyStreams, kAudioObjectPropertyScopeOutput,
		            &first, &fsize) == noErr && fsize) {
			UInt32 sz = sizeof(s->device_format);
			hal_get(first, kAudioStreamPropertyVirtualFormat, kAudioObjectPropertyScopeGlobal,
			        &s->device_format, &sz);
		}
		printf("poise: output device: \"%s\" (uid %s), nominal %.0f Hz\n", name, uid,
		       s->device_nominal_rate);
	}

	/* The tap. A missing TCC grant makes this fail; the prompt needs a human, so
	 * wait for one instead of failing immediately. */
	OSStatus st;
	unsigned waited_ms = 0;
	for (;;) {
		st = create_tap(s, &s->tap_id);
		if (st == noErr)
			break;
		if (waited_ms >= TCC_WAIT_SECONDS * 1000u) {
			snprintf(err, err_size,
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
		if (g_stop) {
			snprintf(err, err_size, "stopped while waiting for the tap");
			goto fail;
		}
	}

	{
		char uid[256] = "";
		tap_uid(s->tap_id, uid, sizeof(uid));
		UInt32 size = sizeof(s->tap_format);
		if (hal_get(s->tap_id, kAudioTapPropertyFormat, kAudioObjectPropertyScopeGlobal,
		            &s->tap_format, &size) != noErr)
			memset(&s->tap_format, 0, sizeof(s->tap_format));
		if (cfg->verbose)
			printf("poise: tap object %u, uid %s\n", (unsigned)s->tap_id, uid);

		/* Ask the tap for the node's format too; it is advisory (the aggregate
		 * stream format is what the IOProc gets), so a refusal is only a note. */
		st = hal_set(s->tap_id, kAudioTapPropertyFormat, kAudioObjectPropertyScopeGlobal,
		             &s->requested, sizeof(s->requested));
		s->tap_format_settable = (st == noErr);
		if (st != noErr)
			report_status("tap: set kAudioTapPropertyFormat (advisory)", st);

		/* Read the description back: this is the evidence that the tap really
		 * excludes Poise's own process (probe (e)). */
		if (cfg->verbose) {
			CFTypeRef back = NULL;
			UInt32 bsize = sizeof(back);
			AudioObjectPropertyAddress ba = { kAudioTapPropertyDescription,
			                                  kAudioObjectPropertyScopeGlobal,
			                                  kAudioObjectPropertyElementMain };
			if (AudioObjectGetPropertyData(s->tap_id, &ba, 0, NULL, &bsize, &back) == noErr && back) {
				CATapDescription *d = (__bridge CATapDescription *)back;
				NSMutableString *procs = [NSMutableString string];
				for (NSNumber *n in d.processes)
					[procs appendFormat:@"%u ", n.unsignedIntValue];
				printf("poise: tap description read back: name=\"%s\" exclusive=%d mixdown=%d "
				       "mono=%d private=%d muteBehavior=%ld processes=[%s]\n",
				       d.name.UTF8String, d.isExclusive, d.isMixdown, d.isMono, d.isPrivate,
				       (long)d.muteBehavior, procs.UTF8String);
				CFRelease(back);
			}
		}

		if (create_aggregate(s, uid) != noErr) {
			snprintf(err, err_size, "cannot create the aggregate device for \"%s\"",
			         cfg->output_device ? cfg->output_device : "default output");
			goto fail;
		}
	}

	/* Explicit 48 kHz Float32 non-interleaved on both sides. */
	set_stream_formats(s, kAudioObjectPropertyScopeInput, &s->input_format, "aggregate input");
	set_stream_formats(s, kAudioObjectPropertyScopeOutput, &s->output_format, "aggregate output");
	read_back_aggregate(s);

	poise_mac_session_report(s);

	if (!format_acceptable(&s->input_format, &s->requested)) {
		char name[256] = "";
		hal_get_string(s->output_device, kAudioObjectPropertyName, kAudioObjectPropertyScopeGlobal,
		               name, sizeof(name));
		snprintf(err, err_size,
		         "refusing to run: the aggregate input stream is %.0f Hz, %u ch, flags 0x%x, not "
		         "the requested %.0f Hz Float32 non-interleaved (device \"%s\" runs at %.0f Hz)",
		         s->input_format.mSampleRate, (unsigned)s->input_format.mChannelsPerFrame,
		         (unsigned)s->input_format.mFormatFlags, (double)cfg->rate, name,
		         s->device_nominal_rate);
		goto fail;
	}
	if (!format_acceptable(&s->output_format, &s->requested)) {
		char name[256] = "";
		hal_get_string(s->output_device, kAudioObjectPropertyName, kAudioObjectPropertyScopeGlobal,
		               name, sizeof(name));
		snprintf(err, err_size,
		         "refusing to run: the aggregate output stream is %.0f Hz, %u ch, flags 0x%x, not "
		         "the requested %.0f Hz Float32 non-interleaved (device \"%s\" runs at %.0f Hz)",
		         s->output_format.mSampleRate, (unsigned)s->output_format.mChannelsPerFrame,
		         (unsigned)s->output_format.mFormatFlags, (double)cfg->rate, name,
		         s->device_nominal_rate);
		goto fail;
	}

	ring_init(&s->ring, cfg->rate, RING_SECONDS);
	s->scratch = calloc(SCRATCH_FRAMES * POISE_COREAUDIO_CHANNELS, sizeof(float));
	if (!s->ring.frames || !s->scratch) {
		snprintf(err, err_size, "out of memory");
		goto fail;
	}
	if (!wav_open(&s->wav, cfg->out_path, cfg->rate, cfg->sample_format)) {
		snprintf(err, err_size, "cannot write %s", cfg->out_path);
		goto fail;
	}
	atomic_store(&s->writer_stop, 0);
	if (pthread_create(&s->writer, NULL, writer_thread, s) != 0) {
		snprintf(err, err_size, "cannot start the writer thread");
		goto fail;
	}
	s->started = 1;

	st = AudioDeviceCreateIOProcID(s->aggregate_id, ioproc, s, &s->proc_id);
	if (st != noErr) {
		report_status("AudioDeviceCreateIOProcID", st);
		snprintf(err, err_size, "AudioDeviceCreateIOProcID failed: OSStatus %d", (int)st);
		goto fail;
	}
	st = AudioDeviceStart(s->aggregate_id, s->proc_id);
	if (st == noErr && cfg->verbose) {
		UInt32 running = 0, alive = 0, size = sizeof(running);
		hal_get(s->aggregate_id, kAudioDevicePropertyDeviceIsRunning,
		        kAudioObjectPropertyScopeGlobal, &running, &size);
		size = sizeof(alive);
		hal_get(s->aggregate_id, kAudioDevicePropertyDeviceIsAlive,
		        kAudioObjectPropertyScopeGlobal, &alive, &size);
		fprintf(stderr, "poise: after start: aggregate %u running=%u alive=%u\n",
		        (unsigned)s->aggregate_id, (unsigned)running, (unsigned)alive);
	}
	if (st != noErr) {
		report_status("AudioDeviceStart", st);
		snprintf(err, err_size, "AudioDeviceStart failed: OSStatus %d", (int)st);
		goto fail;
	}
	/* AudioDeviceStart returns noErr even when the HAL then declines to run the
	 * IO context (seen on this host after a previous instance was torn down); the
	 * only symptom is that no callback ever arrives. Treat that as a failure, not
	 * as a silent capture. */
	for (unsigned waited = 0; waited < 3000; waited += 25) {
		if (atomic_load(&s->c.callbacks))
			break;
		struct timespec ts = { 0, 25 * 1000000L };
		nanosleep(&ts, NULL);
		if (g_stop)
			break;
	}
	if (!atomic_load(&s->c.callbacks)) {
		snprintf(err, err_size,
		         "the aggregate started (no error) but no IOProc callback arrived in 3 s: the HAL "
		         "did not run the aggregate");
		goto fail;
	}
	return s;

fail:
	poise_mac_session_stop(s);
	return NULL;
}

void poise_mac_session_stop(struct poise_mac_session *s)
{
	if (!s)
		return;
	if (s->aggregate_id && s->proc_id) {
		/* This is what unmutes the Mac: MutedWhenTapped mutes only while the tap
		 * is read. */
		AudioDeviceStop(s->aggregate_id, s->proc_id);
		AudioDeviceDestroyIOProcID(s->aggregate_id, s->proc_id);
		s->proc_id = 0;
	}
	if (s->aggregate_id) {
		AudioHardwareDestroyAggregateDevice(s->aggregate_id);
		s->aggregate_id = 0;
	}
	if (s->tap_id) {
		AudioHardwareDestroyProcessTap(s->tap_id);
		s->tap_id = 0;
	}
	if (s->started) {
		atomic_store(&s->writer_stop, 1);
		pthread_join(s->writer, NULL);
		s->started = 0;
	}
	wav_close(&s->wav);
	ring_free(&s->ring);
	free(s->scratch);
	s->scratch = NULL;
}

void poise_mac_session_counters(const struct poise_mac_session *s,
                                struct poise_mac_counters *out)
{
	memset(out, 0, sizeof(*out));
	out->input_frames = atomic_load(&s->c.input_frames);
	out->output_frames = atomic_load(&s->c.output_frames);
	out->callbacks = atomic_load(&s->c.callbacks);
	out->quantum_min = atomic_load(&s->c.quantum_min);
	out->quantum_max = atomic_load(&s->c.quantum_max);
	out->dropped_frames = atomic_load(&s->c.dropped_frames);
	out->overloads = atomic_load(&s->c.overloads);
	out->rt_policy_set = atomic_load(&s->c.rt_policy_set);
}

void poise_mac_session_levels(const struct poise_mac_session *s, float *peak, float *rms,
                              float *tail_rms)
{
	const struct poise_wav *w = &s->wav;
	if (peak)
		*peak = w->peak;
	if (rms)
		*rms = w->frames ? (float)sqrt(w->energy / ((double)w->frames * w->channels)) : 0.0f;
	if (tail_rms) {
		double n = (double)w->tail_filled;
		*tail_rms = n > 0 ? (float)sqrt(fmax(w->tail_energy, 0.0) / n) : 0.0f;
	}
}

void poise_mac_session_report(const struct poise_mac_session *s)
{
	char name[256] = "";
	hal_get_string(s->output_device, kAudioObjectPropertyName, kAudioObjectPropertyScopeGlobal,
	               name, sizeof(name));
	printf("poise: requested format: %.0f Hz, %u ch, Float32, non-interleaved\n",
	       s->requested.mSampleRate, (unsigned)s->requested.mChannelsPerFrame);
	printf("poise: tap format is %s; aggregate input is %s; aggregate output is %s\n",
	       is_non_interleaved(&s->tap_format) ? "non-interleaved" : "interleaved",
	       is_non_interleaved(&s->input_format) ? "non-interleaved" : "interleaved",
	       is_non_interleaved(&s->output_format) ? "non-interleaved" : "interleaved");
	print_asbd("tap format (kAudioTapPropertyFormat)", &s->tap_format);
	print_asbd("aggregate input stream (read back)", &s->input_format);
	print_asbd("aggregate output stream (read back)", &s->output_format);
	print_asbd("output device stream (virtual)", &s->device_format);
	printf("poise: output device nominal rate: %.0f Hz (\"%s\")\n", s->device_nominal_rate, name);
	printf("poise: aggregate clock master: %s\n", s->clock_uid[0] ? s->clock_uid : "(not reported)");
	/* Requested through kAudioSubTapDriftCompensationKey when the aggregate was
	 * created; kAudioSubTapPropertyDriftCompensation is not readable from a
	 * client process here (see measurements/mac-tap-spike.md (d)). */
	printf("poise: per-sub-tap drift compensation: requested 1 (kAudioSubTapDriftCompensationKey), "
	       "property read back %u%s\n", (unsigned)s->drift_compensation,
	       s->drift_compensation ? " (on)" : " (unreadable from this process)");
}

void poise_mac_list_devices(void)
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

void poise_mac_session_run(struct poise_mac_session *s)
{
	if (!s)
		return;
	unsigned elapsed_ms = 0;
	unsigned next_report = 1000;
	while (!g_stop) {
		if (s->cfg.seconds && elapsed_ms >= s->cfg.seconds * 1000u)
			break;
		struct timespec ts = { 0, 50 * 1000000L };
		nanosleep(&ts, NULL);
		elapsed_ms += 50;
		if (s->cfg.verbose && elapsed_ms >= next_report) {
			UInt32 running = 0, size = sizeof(running);
			hal_get(s->aggregate_id, kAudioDevicePropertyDeviceIsRunning,
			        kAudioObjectPropertyScopeGlobal, &running, &size);
			fprintf(stderr,
			        "poise: t=%.1f s callbacks=%llu input=%llu output=%llu aggregate-running=%u\n",
			        elapsed_ms / 1000.0, (unsigned long long)atomic_load(&s->c.callbacks),
			        (unsigned long long)atomic_load(&s->c.input_frames),
			        (unsigned long long)atomic_load(&s->c.output_frames), (unsigned)running);
			next_report += 1000;
		}
	}
}

/* ------------------------------------------------------------------- CLI */

/* The CLI's live session, for atexit (C1: the tap must never outlive the
 * process). */
static struct poise_mac_session *g_session_ptr;

static void on_signal(int sig)
{
	(void)sig;
	/* The tap is destroyed by the main loop (or atexit) once this is seen;
	 * nothing async-signal-unsafe happens here. */
	poise_mac_request_stop();
}

static void on_exit(void)
{
	/* Last line of defence for C1: a tap that outlives the process mutes the
	 * whole Mac until it is destroyed. */
	if (g_session_ptr)
		poise_mac_session_stop(g_session_ptr);
}
static float to_dbfs(float x)
{
	if (x <= 1e-6f)
		return -120.0f;
	return 20.0f * log10f(x);
}

static void usage(void)
{
	printf("usage: poise_coreaudio --seconds N [--out file.wav] [--passthrough]\n"
	       "                       [--device NAME] [--rate HZ] [--format f32|s16] [--verbose]\n"
	       "       poise_coreaudio --list-devices\n"
	       "\n"
	       "  --seconds 0   run until SIGINT/SIGTERM\n");
}

int main(int argc, char **argv)
{
	@autoreleasepool {
		struct poise_mac_session_config cfg;
		memset(&cfg, 0, sizeof(cfg));
		cfg.seconds = 5;
		cfg.rate = POISE_COREAUDIO_RATE;
		cfg.sample_format = POISE_MAC_F32;
		int list = 0;

		for (int i = 1; i < argc; i++) {
			if (!strcmp(argv[i], "--seconds") && i + 1 < argc) {
				cfg.seconds = (unsigned)strtoul(argv[++i], NULL, 10);
			} else if (!strcmp(argv[i], "--out") && i + 1 < argc) {
				cfg.out_path = argv[++i];
			} else if (!strcmp(argv[i], "--passthrough")) {
				cfg.passthrough = 1;
			} else if (!strcmp(argv[i], "--device") && i + 1 < argc) {
				cfg.output_device = argv[++i];
			} else if (!strcmp(argv[i], "--rate") && i + 1 < argc) {
				cfg.rate = (unsigned)strtoul(argv[++i], NULL, 10);
			} else if (!strcmp(argv[i], "--format") && i + 1 < argc) {
				const char *f = argv[++i];
				if (!strcmp(f, "s16"))
					cfg.sample_format = POISE_MAC_S16;
				else if (!strcmp(f, "f32"))
					cfg.sample_format = POISE_MAC_F32;
				else {
					fprintf(stderr, "poise: unknown --format %s\n", f);
					return 1;
				}
			} else if (!strcmp(argv[i], "--verbose") || !strcmp(argv[i], "-v")) {
				cfg.verbose = 1;
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
			poise_mac_list_devices();
			return 0;
		}

		struct sigaction sa;
		memset(&sa, 0, sizeof(sa));
		sa.sa_handler = on_signal;
		sigaction(SIGINT, &sa, NULL);
		sigaction(SIGTERM, &sa, NULL);
		atexit(on_exit);

		printf("poise: macOS %s, %s\n", [[[NSProcessInfo processInfo] operatingSystemVersionString] UTF8String],
		       cfg.passthrough ? "pass-through" : "capture only");

		char err[1024] = "";
		struct poise_mac_session *s = poise_mac_session_start(&cfg, err, sizeof(err));
		if (!s) {
			fprintf(stderr, "poise: %s\n", err);
			return 2;
		}
		g_session_ptr = s;

		struct timespec t0, t1;
		clock_gettime(CLOCK_MONOTONIC, &t0);
		poise_mac_session_run(s);
		clock_gettime(CLOCK_MONOTONIC, &t1);
		double wall = (double)(t1.tv_sec - t0.tv_sec) + (double)(t1.tv_nsec - t0.tv_nsec) / 1e9;

		poise_mac_session_stop(s);
		g_session_ptr = NULL;

		struct poise_mac_counters c;
		poise_mac_session_counters(s, &c);
		float peak = 0, rms = 0, tail = 0;
		poise_mac_session_levels(s, &peak, &rms, &tail);

		double in_s = (double)c.input_frames / cfg.rate;
		double out_s = (double)c.output_frames / cfg.rate;
		double ppm = c.input_frames ? (double)((int64_t)c.output_frames - (int64_t)c.input_frames) /
		                                  (double)c.input_frames * 1e6
		                            : 0.0;
		printf("poise: wall %.2f s; tap delivered %llu frames (%.3f s), output consumed %llu frames "
		       "(%.3f s)\n",
		       wall, (unsigned long long)c.input_frames, in_s,
		       (unsigned long long)c.output_frames, out_s);
		printf("poise: drift output-tap %+lld frames, %+.2f ppm\n",
		       (long long)((int64_t)c.output_frames - (int64_t)c.input_frames), ppm);
		if (atomic_load(&s->c.has_time)) {
			int64_t in_adv = atomic_load(&s->c.last_in_time) - atomic_load(&s->c.first_in_time);
			int64_t out_adv = atomic_load(&s->c.last_out_time) - atomic_load(&s->c.first_out_time);
			double clock_ppm = in_adv ? (double)(out_adv - in_adv) / (double)in_adv * 1e6 : 0.0;
			printf("poise: clocks: tap advanced %lld samples, output advanced %lld samples over the "
			       "same %llu callbacks: %+lld samples, %+.2f ppm\n",
			       (long long)in_adv, (long long)out_adv, (unsigned long long)c.callbacks,
			       (long long)(out_adv - in_adv), clock_ppm);
			printf("poise: output-minus-tap time stamp delta: %lld..%lld samples "
			       "(input time flags 0x%x, output time flags 0x%x)\n",
			       (long long)atomic_load(&s->c.delta_min),
			       (long long)atomic_load(&s->c.delta_max), s->time_flags_in, s->time_flags_out);
		}
		printf("poise: callbacks %llu, quantum %llu..%llu frames\n",
		       (unsigned long long)c.callbacks, (unsigned long long)c.quantum_min,
		       (unsigned long long)c.quantum_max);
		printf("poise: peak %.1f dBFS, rms %.1f dBFS, last-second rms %.1f dBFS\n",
		       to_dbfs(peak), to_dbfs(rms), to_dbfs(tail));
		printf("poise: RT policy: %s; dropped %llu frames; overloads %llu\n",
		       c.rt_policy_set ? "time-constraint" : "not set",
		       (unsigned long long)c.dropped_frames, (unsigned long long)c.overloads);
		if (s->policy_verified)
			printf("poise: RT policy read back on the IOProc thread: period %u ticks, computation "
			       "%u, constraint %u, preemptible %u\n",
			       s->policy_period, s->policy_computation, s->policy_constraint,
			       s->policy_preemptible);
		if (cfg.out_path)
			printf("poise: wrote %s\n", cfg.out_path);
		if (!c.input_frames) {
			fprintf(stderr, "poise: no frames at all: the tap was never read\n");
			free(s);
			return 4;
		}
		if (peak <= 0.0f) {
			fprintf(stderr,
			        "poise: captured only silence: either nothing was playing, or the System Audio "
			        "Recording grant is missing\n");
			free(s);
			return 5;
		}
		free(s);
	}
	return 0;
}
