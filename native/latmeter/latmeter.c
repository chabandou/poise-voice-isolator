/*
 * latmeter: measure Poise's end-to-end delay on Windows, from outside.
 *
 * Plays a mono signal into one render endpoint (CABLE Input, as a video
 * player would), logs that stream's clock (IAudioClock: the position a
 * player syncs its video to) and records, with their QPC timestamps,
 * loopback streams of that endpoint ("ref") and of the speakers ("lis"),
 * and optionally a capture endpoint ("tap", e.g. CABLE Output, which is
 * what Poise reads). tools/win_latency.py lines the recordings up to get
 * the delay through Poise every few hundred ms.
 *
 * Loopback timestamps are the driver's "heard at" estimate: measured on
 * a Realtek laptop, 16 ms after the device position for the speakers and
 * ~145 ms after it for VB-Cable (its reported latency). The clock log is
 * the reference that matches what a player sees.
 *
 *   latmeter <play-endpoint> <listen-endpoint> <signal.f32> <seconds>
 *            <out-prefix> [tap-capture-endpoint]
 *
 * signal.f32: mono float32 at 48 kHz, looped. Writes <prefix>.<tag>.f32
 * (mono float32) and <prefix>.<tag>.csv (one line per packet: first
 * sample index, its QPC time stamp, frames, flags, QPC time it was read;
 * times in 100 ns units) for each
 * recording, plus <prefix>.clk.csv (render clock: samples written,
 * device position in samples, QPC time in 100 ns units).
 *
 * Build: zig cc -target x86_64-windows-gnu -O2 -o latmeter.exe latmeter.c
 *        -lole32 -lavrt -lwinmm
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
#include <avrt.h>
#include <timeapi.h>

#include <stdarg.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define RATE 48000u

#ifndef AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM
#define AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM 0x80000000
#endif
#ifndef AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY
#define AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY 0x08000000
#endif

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

static _Atomic int g_stop;
static float *g_signal;
static size_t g_signal_len;

static void die(const char *what, HRESULT hr)
{
	fprintf(stderr, "latmeter: %s failed (0x%08lx)\n", what, (unsigned long)hr);
	exit(1);
}

static BOOL WINAPI on_ctrl(DWORD type)
{
	atomic_store(&g_stop, 1);
	return TRUE;
}

static IMMDevice *find_endpoint(IMMDeviceEnumerator *en, EDataFlow flow,
		const char *name)
{
	IMMDeviceCollection *coll = NULL;
	IMMDevice *found = NULL;
	wchar_t want[512];
	UINT count = 0, i;

	MultiByteToWideChar(CP_UTF8, 0, name, -1, want, 512);
	if (FAILED(IMMDeviceEnumerator_EnumAudioEndpoints(en, flow,
			DEVICE_STATE_ACTIVE, &coll)))
		return NULL;
	IMMDeviceCollection_GetCount(coll, &count);
	for (i = 0; i < count && found == NULL; i++) {
		IMMDevice *dev = NULL;
		IPropertyStore *props = NULL;
		PROPVARIANT pv;

		if (FAILED(IMMDeviceCollection_Item(coll, i, &dev)))
			continue;
		PropVariantInit(&pv);
		if (SUCCEEDED(IMMDevice_OpenPropertyStore(dev, STGM_READ, &props)) &&
		    SUCCEEDED(IPropertyStore_GetValue(props, &PKEY_Device_FriendlyName_, &pv)) &&
		    pv.vt == VT_LPWSTR && wcscmp(pv.pwszVal, want) == 0) {
			found = dev;
			dev = NULL;
		}
		PropVariantClear(&pv);
		if (props)
			IPropertyStore_Release(props);
		if (dev)
			IMMDevice_Release(dev);
	}
	IMMDeviceCollection_Release(coll);
	return found;
}

static void stereo_float(WAVEFORMATEXTENSIBLE *wfx)
{
	memset(wfx, 0, sizeof(*wfx));
	wfx->Format.wFormatTag = WAVE_FORMAT_EXTENSIBLE;
	wfx->Format.nChannels = 2;
	wfx->Format.nSamplesPerSec = RATE;
	wfx->Format.wBitsPerSample = 32;
	wfx->Format.nBlockAlign = 8;
	wfx->Format.nAvgBytesPerSec = RATE * 8;
	wfx->Format.cbSize = sizeof(*wfx) - sizeof(WAVEFORMATEX);
	wfx->Samples.wValidBitsPerSample = 32;
	wfx->dwChannelMask = SPEAKER_FRONT_LEFT | SPEAKER_FRONT_RIGHT;
	wfx->SubFormat = SUBTYPE_IEEE_FLOAT_;
}

static IAudioClient *open_client(IMMDeviceEnumerator *en, EDataFlow flow,
		const char *name, DWORD flags, REFERENCE_TIME buffer)
{
	WAVEFORMATEXTENSIBLE wfx;
	IAudioClient *client = NULL;
	IMMDevice *dev = find_endpoint(en, flow, name);
	HRESULT hr;

	if (dev == NULL) {
		fprintf(stderr, "latmeter: no active output endpoint named \"%s\"\n", name);
		exit(1);
	}
	hr = IMMDevice_Activate(dev, &IID_IAudioClient_, CLSCTX_ALL, NULL,
			(void **)&client);
	IMMDevice_Release(dev);
	if (FAILED(hr))
		die("Activate", hr);
	stereo_float(&wfx);
	hr = IAudioClient_Initialize(client, AUDCLNT_SHAREMODE_SHARED,
			flags | AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM |
			AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY,
			buffer, 0, (WAVEFORMATEX *)&wfx, NULL);
	if (FAILED(hr))
		die("Initialize", hr);
	return client;
}

/* Bytes on their way to a file. The audio threads only copy into a ring;
 * the writer thread does the file I/O (a disk stall under load once held
 * a writing capture thread for 1.9 s, and loopback then lost audio
 * without flagging it). One producer, one consumer. */
struct ring {
	char *buf;
	size_t size;              /* power of two */
	_Atomic size_t head, tail;
	_Atomic uint64_t lost;    /* bytes dropped: the writer fell 1 ring behind */
	FILE *file;
};

#define MAX_RINGS 8
static struct ring *g_rings[MAX_RINGS];
static int g_n_rings;
static _Atomic int g_writer_stop;

static void ring_open(struct ring *r, const char *path, const char *mode,
		size_t size)
{
	r->buf = malloc(size);
	r->size = size;
	atomic_init(&r->head, 0);
	atomic_init(&r->tail, 0);
	atomic_init(&r->lost, 0);
	r->file = fopen(path, mode);
	if (r->buf == NULL || r->file == NULL || g_n_rings == MAX_RINGS) {
		fprintf(stderr, "latmeter: cannot write %s\n", path);
		exit(1);
	}
	g_rings[g_n_rings++] = r;
}

static void ring_put(struct ring *r, const void *data, size_t n)
{
	size_t head = atomic_load_explicit(&r->head, memory_order_relaxed);
	size_t tail = atomic_load_explicit(&r->tail, memory_order_acquire);
	size_t at = head & (r->size - 1), first;

	if (head - tail + n > r->size) {
		atomic_fetch_add(&r->lost, n);
		return;
	}
	first = n < r->size - at ? n : r->size - at;
	memcpy(r->buf + at, data, first);
	memcpy(r->buf, (const char *)data + first, n - first);
	atomic_store_explicit(&r->head, head + n, memory_order_release);
}

static void ring_printf(struct ring *r, const char *fmt, ...)
{
	char line[256];
	va_list ap;
	int n;

	va_start(ap, fmt);
	n = vsnprintf(line, sizeof(line), fmt, ap);
	va_end(ap);
	if (n > 0)
		ring_put(r, line, (size_t)n < sizeof(line) ? (size_t)n : sizeof(line) - 1);
}

static void ring_flush(struct ring *r)
{
	size_t head = atomic_load_explicit(&r->head, memory_order_acquire);
	size_t tail = atomic_load_explicit(&r->tail, memory_order_relaxed);
	size_t n = head - tail, at = tail & (r->size - 1), first;

	if (n == 0)
		return;
	first = n < r->size - at ? n : r->size - at;
	fwrite(r->buf + at, 1, first, r->file);
	fwrite(r->buf, 1, n - first, r->file);
	atomic_store_explicit(&r->tail, head, memory_order_release);
}

static DWORD WINAPI writer_thread(void *arg)
{
	int i;

	while (!atomic_load(&g_writer_stop)) {
		for (i = 0; i < g_n_rings; i++)
			ring_flush(g_rings[i]);
		Sleep(20);
	}
	for (i = 0; i < g_n_rings; i++) {
		ring_flush(g_rings[i]);
		fclose(g_rings[i]->file);
	}
	return 0;
}

struct loopback {
	IAudioClient *client;
	IAudioCaptureClient *cap;
	struct ring pcm, log;
	uint64_t pos;
	float *mono;
	UINT32 mono_size;
};

/* A loopback recording of a render endpoint, or a capture endpoint. */
static void open_recording(IMMDeviceEnumerator *en, EDataFlow flow,
		const char *name, const char *prefix, const char *tag,
		struct loopback *lb)
{
	char path[1024];
	HRESULT hr;

	memset(lb, 0, sizeof(*lb));
	lb->client = open_client(en, flow, name,
			flow == eRender ? AUDCLNT_STREAMFLAGS_LOOPBACK : 0, 20000000);
	hr = IAudioClient_GetService(lb->client, &IID_IAudioCaptureClient_,
			(void **)&lb->cap);
	if (FAILED(hr))
		die("loopback GetService", hr);
	IAudioClient_GetBufferSize(lb->client, &lb->mono_size);
	lb->mono = calloc(lb->mono_size, sizeof(float));
	if (lb->mono == NULL) {
		fprintf(stderr, "latmeter: out of memory\n");
		exit(1);
	}
	/* 87 s of samples and minutes of packet lines in hand. */
	snprintf(path, sizeof(path), "%s.%s.f32", prefix, tag);
	ring_open(&lb->pcm, path, "wb", (size_t)1 << 24);
	snprintf(path, sizeof(path), "%s.%s.csv", prefix, tag);
	ring_open(&lb->log, path, "w", (size_t)1 << 20);
	ring_printf(&lb->log, "pos,qpc100ns,frames,flags,read100ns\n");
}

static uint64_t now_100ns(void)
{
	static LARGE_INTEGER freq;
	LARGE_INTEGER now;

	if (freq.QuadPart == 0)
		QueryPerformanceFrequency(&freq);
	QueryPerformanceCounter(&now);
	return (uint64_t)((double)now.QuadPart * 1e7 / (double)freq.QuadPart);
}

static void drain_loopback(struct loopback *lb)
{
	for (;;) {
		BYTE *data;
		UINT32 frames, next = 0, i;
		DWORD flags;
		UINT64 devpos, qpc;
		HRESULT hr;

		hr = IAudioCaptureClient_GetNextPacketSize(lb->cap, &next);
		if (FAILED(hr))
			die("GetNextPacketSize", hr);
		if (next == 0)
			return;
		hr = IAudioCaptureClient_GetBuffer(lb->cap, &data, &frames, &flags,
				&devpos, &qpc);
		if (FAILED(hr))
			die("GetBuffer", hr);
		if (frames > lb->mono_size)
			frames = lb->mono_size;
		for (i = 0; i < frames; i++) {
			const float *s = (const float *)data + 2 * i;
			lb->mono[i] = (flags & AUDCLNT_BUFFERFLAGS_SILENT) ? 0.0f :
				0.5f * (s[0] + s[1]);
		}
		ring_put(&lb->pcm, lb->mono, frames * sizeof(float));
		ring_printf(&lb->log, "%llu,%llu,%u,%lu,%llu\n", (unsigned long long)lb->pos,
				(unsigned long long)qpc, frames, (unsigned long)flags,
				(unsigned long long)now_100ns());
		lb->pos += frames;
		IAudioCaptureClient_ReleaseBuffer(lb->cap, frames);
	}
}

struct player {
	IAudioClient *client;
	IAudioRenderClient *ren;
	IAudioClock *clock;
	HANDLE event;
	UINT32 buffer;
	UINT64 freq;
	uint64_t written;
	size_t sig_pos;
	struct ring log;
};

static void play_fill(struct player *p)
{
	UINT32 padding = 0, avail, i;
	BYTE *data;
	float *out;
	UINT64 pos = 0, qpc = 0;

	if (FAILED(IAudioClient_GetCurrentPadding(p->client, &padding)))
		return;
	avail = p->buffer - padding;
	if (avail && SUCCEEDED(IAudioRenderClient_GetBuffer(p->ren, avail, &data))) {
		out = (float *)data;
		for (i = 0; i < avail; i++) {
			float v = g_signal[p->sig_pos];

			out[2 * i] = out[2 * i + 1] = v;
			if (++p->sig_pos == g_signal_len)
				p->sig_pos = 0;
		}
		IAudioRenderClient_ReleaseBuffer(p->ren, avail, 0);
		p->written += avail;
	}
	if (SUCCEEDED(IAudioClock_GetPosition(p->clock, &pos, &qpc)))
		ring_printf(&p->log, "%llu,%.3f,%llu\n", (unsigned long long)p->written,
				(double)pos * RATE / (double)p->freq,
				(unsigned long long)qpc);
}

static DWORD WINAPI player_thread(void *arg)
{
	struct player *p = arg;
	DWORD task = 0;
	HANDLE mm = AvSetMmThreadCharacteristicsW(L"Pro Audio", &task);

	while (!atomic_load(&g_stop)) {
		if (WaitForSingleObject(p->event, 200) == WAIT_OBJECT_0)
			play_fill(p);
	}
	if (mm)
		AvRevertMmThreadCharacteristics(mm);
	return 0;
}

static float *read_signal(const char *path, size_t *len)
{
	FILE *f = fopen(path, "rb");
	long size;
	float *buf;

	if (f == NULL)
		return NULL;
	fseek(f, 0, SEEK_END);
	size = ftell(f);
	fseek(f, 0, SEEK_SET);
	if (size < (long)(RATE * sizeof(float))) {
		fclose(f);
		return NULL;
	}
	buf = malloc((size_t)size);
	*len = fread(buf, sizeof(float), (size_t)size / sizeof(float), f);
	fclose(f);
	return buf;
}

int main(int argc, char **argv)
{
	IMMDeviceEnumerator *en = NULL;
	struct player p;
	struct loopback ref, lis, tap;
	int with_tap = argc == 7, i;
	uint64_t lost = 0;
	HANDLE writer;
	char path[1024];
	double seconds;
	ULONGLONG t_end;
	HANDLE th;
	HRESULT hr;

	if (argc != 6 && argc != 7) {
		fprintf(stderr, "usage: latmeter <play-endpoint> <listen-endpoint> "
				"<signal.f32> <seconds> <out-prefix> "
				"[tap-capture-endpoint]\n");
		return 2;
	}
	g_signal = read_signal(argv[3], &g_signal_len);
	if (g_signal == NULL) {
		fprintf(stderr, "latmeter: cannot read %s (>= 1 s of float32)\n", argv[3]);
		return 1;
	}
	seconds = atof(argv[4]);
	SetConsoleCtrlHandler(on_ctrl, TRUE);
	timeBeginPeriod(1);
	hr = CoInitializeEx(NULL, COINIT_MULTITHREADED);
	if (FAILED(hr))
		die("CoInitializeEx", hr);
	hr = CoCreateInstance(&CLSID_MMDeviceEnumerator_, NULL, CLSCTX_ALL,
			&IID_IMMDeviceEnumerator_, (void **)&en);
	if (FAILED(hr))
		die("device enumerator", hr);

	memset(&p, 0, sizeof(p));
	p.client = open_client(en, eRender, argv[1],
			AUDCLNT_STREAMFLAGS_EVENTCALLBACK, 300000);
	if (FAILED(hr = IAudioClient_GetService(p.client, &IID_IAudioRenderClient_,
			(void **)&p.ren)))
		die("render GetService", hr);
	if (FAILED(hr = IAudioClient_GetService(p.client, &IID_IAudioClock_,
			(void **)&p.clock)))
		die("clock GetService", hr);
	IAudioClock_GetFrequency(p.clock, &p.freq);
	IAudioClient_GetBufferSize(p.client, &p.buffer);
	p.event = CreateEventW(NULL, FALSE, FALSE, NULL);
	IAudioClient_SetEventHandle(p.client, p.event);
	snprintf(path, sizeof(path), "%s.clk.csv", argv[5]);
	ring_open(&p.log, path, "w", (size_t)1 << 20);
	ring_printf(&p.log, "written,devpos,qpc100ns\n");

	open_recording(en, eRender, argv[1], argv[5], "ref", &ref);
	open_recording(en, eRender, argv[2], argv[5], "lis", &lis);
	if (with_tap)
		open_recording(en, eCapture, argv[6], argv[5], "tap", &tap);
	IMMDeviceEnumerator_Release(en);

	writer = CreateThread(NULL, 0, writer_thread, NULL, 0, NULL);
	play_fill(&p);
	if (FAILED(hr = IAudioClient_Start(ref.client)))
		die("start reference loopback", hr);
	if (FAILED(hr = IAudioClient_Start(lis.client)))
		die("start listen loopback", hr);
	if (with_tap && FAILED(hr = IAudioClient_Start(tap.client)))
		die("start tap capture", hr);
	if (FAILED(hr = IAudioClient_Start(p.client)))
		die("start player", hr);
	th = CreateThread(NULL, 0, player_thread, &p, 0, NULL);
	fprintf(stderr, "latmeter: playing into \"%s\", listening to \"%s\" for %.0f s\n",
			argv[1], argv[2], seconds);

	/* Recordings must not lose audio under the load being measured: this
	 * thread drains them with MMCSS priority into 2 s buffers (at normal
	 * priority it once went 1.3 s without a CPU under full load) and
	 * leaves the files to the writer thread. */
	{
		DWORD task = 0;
		AvSetMmThreadCharacteristicsW(L"Pro Audio", &task);
	}
	t_end = GetTickCount64() + (ULONGLONG)(seconds * 1000.0);
	while (!atomic_load(&g_stop) && GetTickCount64() < t_end) {
		drain_loopback(&ref);
		drain_loopback(&lis);
		if (with_tap)
			drain_loopback(&tap);
		Sleep(2);
	}
	atomic_store(&g_stop, 1);
	WaitForSingleObject(th, INFINITE);
	drain_loopback(&ref);
	drain_loopback(&lis);
	if (with_tap) {
		drain_loopback(&tap);
		IAudioClient_Stop(tap.client);
	}
	IAudioClient_Stop(p.client);
	IAudioClient_Stop(ref.client);
	IAudioClient_Stop(lis.client);
	atomic_store(&g_writer_stop, 1);
	WaitForSingleObject(writer, INFINITE);
	for (i = 0; i < g_n_rings; i++)
		lost += atomic_load(&g_rings[i]->lost);
	if (lost)
		fprintf(stderr, "latmeter: WARNING: %llu bytes not written (disk too "
				"slow): the recordings are incomplete\n",
				(unsigned long long)lost);
	fprintf(stderr, "latmeter: done (%llu samples played, %llu/%llu recorded)\n",
			(unsigned long long)p.written, (unsigned long long)ref.pos,
			(unsigned long long)lis.pos);
	timeEndPeriod(1);
	CoUninitialize();
	return 0;
}
