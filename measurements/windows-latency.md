# Windows latency measurements

Measured 2026-10-13/14 on bare metal (earlier figures came from a VM,
where virtual audio timing behaves nothing like a sound card's). Every
number here comes from `tools/win_latency.py` with `native/latmeter`
unless stated otherwise. Per-run, per-phase numbers are in
[`windows-latency-runs.csv`](windows-latency-runs.csv); run IDs below
match its `run` column. The raw recordings (`build/latency/<run>`, ~6 GB)
stayed on the test machine.

## Setup

- HP Pavilion Laptop 15-eh0xxx, AMD Ryzen 5 4500U (6 cores, 6 threads),
  Windows 11 Pro 22631.
- Output: Speaker (Realtek(R) Audio), shared mode, 48 kHz, period 512
  samples (10.67 ms), buffer 1126 samples.
- Capture: CABLE Output (VB-Audio Virtual Cable), period 480 (10 ms).
- Engine: DeepFilterNet3, 512-sample frames, 1536 samples (32 ms) of
  lookahead. Runs use either the "shadow" engine (DF3 runs on every
  frame, the frame played is the input delayed by DF3's latency) or real
  DF3 at `--atten-lim-db -1` (89 % dry, aligned): both keep the test
  noise measurable with DF3's full CPU load.
- Python 3.12, onnxruntime 1.19.2 (newer builds crash on this machine's
  msvcp140 14.36), DLLs built with zig cc 0.17.

## Method

`latmeter` plays band-limited noise into CABLE Input like a video player,
logs that stream's clock (IAudioClock, what players sync video to), and
records CABLE Input (loopback), the speakers (loopback) and CABLE Output
(capture) with QPC time stamps. Every 250 ms a 100 ms window of what the
speakers played is matched against what was played into the cable.

| Metric | Meaning |
|---|---|
| A/V (`av_ms`) | speakers' loopback time minus the time CABLE Input's clock says the sample played: the offset a player that syncs to its audio clock gets |
| VB-Cable (`cable_ms`) | CABLE Input's clock to CABLE Output's capture time stamp |
| Poise (`poise_ms`) | A/V minus VB-Cable: Poise, the speakers' buffer, their reported latency |
| dropouts | runs of >= 64 silent samples in the speakers' audio (the signal never is silent) |
| bad windows | windows that did not match (correlation < 0.8): dropouts, skips, garbled audio |
| dry frames | frames the native path played unprocessed (inference late) |

Load phases: `idle`; `cpu` (one busy process per core, normal priority);
`gil` (a Python thread in the UI's process in 30 ms pure-Python bursts);
`gilblock` (that thread holding the GIL 80 ms every second in one C
call); `cpugil` (cpu and gil together).

### Calibration

| Finding | Value | Runs |
|---|---|---|
| Loopback time stamp minus the endpoint's own clock, Realtek | +16 ms | cal-speaker |
| Same, VB-Cable (its reported latency; 7168 samples = 149 ms) | +139 to +149 ms | cal-cable, smoke-wasapi |
| CABLE Output packet readable after its first sample's time stamp | ~21 ms (11 ms after the packet's end) | standalone |
| Speaker loopback packet readable after its time stamp | ~1 ms | standalone |
| CABLE Input loopback delivers audio later than CABLE Output capture | 82-101 ms later | H1b, H2b, S2 |
| Speakers hold beyond Poise's buffer (`render_queue` 1600 vs fill 1126) | ~10 ms | D1-D3 |

So capturing CABLE Output (what Poise does) is the fastest way to get
audio out of VB-Cable; loopback of CABLE Input, as FxSound does with its
own driver, is 80-100 ms slower with VB-Cable.

## 1. The branch, windows-desync, as found vs master's PortAudio loop

9 minutes each, shadow engine, Poise in the harness process.

| | A-wasapi (native, as committed) | B-portaudio (master's loop) |
|---|---|---|
| A/V | 220 ms, then 231.7 ms after one +10.8 ms step at 27 s | 162 ms |
| Drift over 9 min | none (±1 ms) | none (-0.4 to +2 ms/min) |
| Dropouts idle / cpu / gil / gilblock | 1 / 0 / 0 / 0 (the step) | 18 / 2050 / 1588 / 143 |
| Audio lost under cpu / gil | none | 11.7 s / 6.5 s per 2 min |
| Unprocessed frames | 984, incl. one 3.9 s stretch under cpu | - |

The old path does not drift on bare metal; it loses audio. Split (A2 vs
B): VB-Cable 52.8 vs 51.9 ms, Poise 169.7 vs 110.3 ms. (The CSV counts 4
idle dropouts for A-wasapi: 3 fall in the first 0.4 s of its recording,
before the cable's audio reached the speakers; later runs start their
first phase 0.5 s in.)

## 2. Fixes on windows-desync

### Clock bridge after a capture stall (simulation, tests/test_wasapi_bridge.py)

| | Before | After (fbd127d) |
|---|---|---|
| 150 ms stall: delay 5 s later | +20.8 ms (22.2 -> 43.0 ms) | -1.5 ms dip, back within ~5 s |
| Recovery | ~50 s | ~5 s |
| 7 stalls in 2 min | ratchets up | 20-25 ms throughout, target unchanged |

### Inference under full CPU load (DF3 frame time, 6 busy processes)

| Configuration | p50 | p99 | max | frames > 21 ms |
|---|---|---|---|---|
| idle, 2 ORT threads | 1.43 ms | 2.1 ms | 2.4 ms | 0 |
| idle, 1 ORT thread | 1.44 ms | 2.1 ms | 2.7 ms | 0 |
| load, 2 threads, HIGHEST | 1.49 ms | 22.9 ms | 37.0 ms | 15 |
| load, 1 thread, HIGHEST | 1.54 ms | 26.8 ms | 46.2 ms | 20 |
| load, 2 threads, MMCSS | 1.54 ms | 13.6 ms | 42.5 ms | 13 |
| load, 1 thread, MMCSS | 1.52 ms | 4.0 ms | 4.2 ms | 0 |

On the native path (dry frames, cpu / cpugil, 90 s each):

| Run | Configuration | cpu | cpugil |
|---|---|---|---|
| X0-wasapi | normal priority class, 2 threads | 241 | 464 |
| X1-wasapi | ABOVE_NORMAL class, 2 threads (rejected) | 280 | 915 |
| Y1-wasapi | MMCSS + 1 thread (de42b90) | 0 | 58 |

### Worker margin, native path in the UI's process (after MMCSS)

Dry frames per phase (60 s each), shadow engine:

| Run | Margin | idle | cpu | gil | gilblock | cpugil |
|---|---|---|---|---|---|---|
| M21-wasapi | 21.3 ms | 0 | 1 | 0 | 183 | 4 |
| M11-wasapi | 10.7 ms | 0 | 0 | 0 | 251 | 69 |

### Native path latency budget (A2-wasapi)

| Stage | ms |
|---|---|
| Clock-bridge FIFO (time average; adapts, 16-26 ms across runs) | 25.8 |
| Core delay: frame 10.7 + render quantum 10.7 + fade 1.3 + margin 21.3 | 44.0 |
| Engine lookahead | 32.0 |
| Speaker queue (Poise's buffer 23.5 + the speakers' own ~10) | ~33 |

Poise's own time, CABLE Output readable to speakers mixed: ~148 ms native
vs ~89 ms PortAudio.

## 3. The glitch staircase

Now and then the speaker endpoint drops 133-334 samples and every later
sample plays one period (~10.7 ms) later, for good. Each step matches a
dropout in the speakers' audio. Poise's counters (FIFO, render events,
`render_queue`, capture age) and the loopback time stamps do not move;
the bridge's rate and VB-Cable's share do not either, so it is not the
two devices' clocks disagreeing (that would also slip both ways and at
a steady interval). Steps are always +1 period.

| Run | Time after the measurement starts | Dropout (samples) | Step |
|---|---|---|---|
| W1-wasapi-proc | 5.5 s | 203 | +10.3 ms |
| M11-wasapi | 22 s | 176 | +9.3 ms |
| A-wasapi | 27 s | 219 | +10.8 ms |
| M5-wasapi | 37 s | - | +10.6 ms |
| D3-wasapi | 37.5 s | 134 | +9.9 ms |
| X1-wasapi | 141 s (cpugil) | 133 | +10.6 ms |
| M11-wasapi | 168 s (gil) | 334 | +11.3 ms |
| M21-wasapi | 283 s (cpugil) | 229 | +11.7 ms |

5 of the 8 came in the first 40 s of a session (in ~16 native-path
starts); after that, 3 in ~110 minutes, all under load.

Without Poise (N1-direct, `tools/win_steps.py`): latmeter played its
noise straight into the speakers for 60 minutes and recorded them: no
step, no dropout, the offset constant to the sample (1609 samples, 23.8
ms against the stream clock). That rules out a steady glitch rate of the
laptop's audio, not the start-up steps (one start) nor the rare later
ones (0 in 60 minutes is likely at 3 per 110). Not pursued further for
now; the next test would be many short starts with and without Poise.

## 4. PortAudio in its own process vs the native path

Real DF3 at -1 dB; phases idle 120 s, cpu 120, gil 120, gilblock 90,
cpugil 120, idle 60. Dropouts per phase:

| Run | Path | idle | cpu | gil | gilblock | cpugil | idle | A/V |
|---|---|---|---|---|---|---|---|---|
| H1b-wasapi | native, UI process, 21 ms margin | 0 | 0 | 0 | 0 | 0 | 0 | 227-228 ms |
| H2b-proc-rt | PortAudio, own process, MMCSS + 1 thread (good start) | 2 | 0 | 0 | 0 | 0 | 0 | 171-172 ms |
| H2-proc-rt | same (bad start) | 219 | 173 | 181 | 122 | 95 | 74 | 175-176 ms |
| H3b-proc-plain | PortAudio, own process, no fixes | 7 | 2852 | 4 | 0 | 3028 | 7 | ~170 ms |
| H4-inproc-rt | PortAudio, UI process, MMCSS + 1 thread (bad start) | 340 | 456 | 317 | 302 | 513 | 205 | ~171 ms |

H1b also played 279 frames unprocessed under gilblock and 2 under cpugil.
PortAudio's audio lost under cpu / cpugil without the fixes (H3b): 22.4 s
/ 31.0 s per 2 min.

Start-to-start spread, PortAudio in its own process with the fixes, 2 min
idle: S1 415 dropouts, S2 2, S3 420. Same loop in the UI's process
without fixes, 60 s idle: I-shadow 305, I-df3 8. 3 of 5 starts with the
fixes settled into ~200-420 dropouts per 2 min for the whole run.

H1 and H3 were discarded: latmeter's capture thread stalled 1.9-4 s on
disk I/O under load and the loopback lost audio unflagged (fixed in
bb37188 / e75a1e1).

## 5. What limits the native path's latency

- Shared-mode periods (IAudioClient3): Realtek speakers fixed at 512
  (10.67 ms), CABLE Output fixed at 480 (10 ms); only CABLE Input (the
  player's side) goes down to 128. No low-latency shared mode for Poise's
  endpoints on this machine.
- Worker margin 5.3 ms instead of 21.3 ms, native path in the UI's
  process, no UI load (M5-wasapi, 60 s idle + 60 s cpu): 0 unprocessed
  frames; core delay 1343 vs 2112 samples, FIFO 1060 vs 1196; A/V ~200 ms
  before a staircase step (H1b: 227 ms). Only safe without a UI holding
  the GIL (see M11).

## 6. Native path in the audio process (AudioHost), 5.3 ms margin

Same phases and engine as section 4. The UI's load (gil, gilblock)
runs in the harness process; inference runs in the audio process with
MMCSS, one ONNX thread and the collector paused.

| Run | Dropouts (all phases) | Dry frames (all phases) | A/V | VB-Cable | Poise |
|---|---|---|---|---|---|
| H1b-wasapi (UI process, 21 ms) | 0 | 279 gilblock, 2 cpugil | 227-228 ms | 58.6 ms | 169 ms |
| W1-wasapi-proc | 1 (a staircase step 5.5 s in) | 0 | 208.5 ms | 61.3 ms | 147 ms |
| W2-wasapi-proc | 0 | 0 | 203.4-203.7 ms | 56.2 ms | 147 ms |

For comparison, Poise's share with PortAudio is 108-110 ms (B, H2b, S2):
the native path in the audio process costs ~37 ms more, for no dropouts
and no clock fight.

A/V held within ~1 ms (p99-p1) through every phase. Inside Poise: core
delay 1344 vs 2112 samples; the FIFO stayed at its starting level (785
samples) instead of growing to ~1140; the speakers' own queue read
higher than in-process runs (`render_queue` 2113 in W1, 1938 in W2, vs
~1600).

That reading is not delay. Across 13 runs, Poise's share minus its core
delay and FIFO stays at 98.5-104.6 ms whether `render_queue` reads 33 or
44 ms (correlation 0.17): the speaker stream's clock reports a different
position on some starts. What does vary per start is the FIFO, 15.9-25.6
ms: 16.4 ms when VB-Cable's packets arrive one by one, up to ~25 ms
when some arrive in pairs, which lasts the whole session; the capture's
timing is now steered clear of the pairs at the start (section 10).

## 7. VB-Cable's own delay

Without Poise: latmeter plays into CABLE Input and captures CABLE Output,
8 s per fresh start (`tools/win_latency.py cable <label>`, recordings in
`build/latency/cable-<label>`). Times after CABLE Input's clock says the
sample played:

| Latency setting (control panel) | Run | Capture time stamp | Readable at CABLE Output |
|---|---|---|---|
| 7168 samples (default) | cable-before | median 54.4 ms (43.0-61.8) | median 63.7 ms (51.8-71.5) |
| 3x 2048 | cable-3x2048 | median 60.6 ms (51.7-72.3) | median 75.8 ms (69.7-90.3) |
| 3x 512 | cable-3x512 | median 61.3 ms (54.7-62.4) | median 71.8 ms (63.8-80.9) |
| 3x 128 | cable-3x128 | no audio: CABLE Output delivers silence | - |

6 starts each. The setting does not shrink VB-Cable's share: coarser
blocks (3x 2048) add delay, finer ones (3x 512) change nothing beyond
the start-to-start spread, and 3x 128 (384 samples, less than one 10 ms
WASAPI packet of 480) passes nothing at all. The default stays. The default adapts its block size to the
clients (the panel's statistics show mostly 256-sample blocks). The
driver's DMA buffer (4096 samples, both sides) is not among the settings.
(One change before 3x 2048 left CABLE Output delivering pure silence
until it was set again.)

## 8. The GUI on the audio process

`tools/win_gui_check.py` runs the GUI's AudioWorker as the main window
does (Qt event loop, signals, a live dial change) with VB-Cable
switching off (latmeter plays into CABLE Input itself); the load runs in
the GUI's process. Real DF3 at -1 dB, 60 s per phase (G1-gui):

| Phase | Dropouts | Dry frames | A/V (p99-p1) | VB-Cable | Poise |
|---|---|---|---|---|---|
| idle | 0 | 0 | 203.9 ms (2.7) | 52.1 ms | 151.9 ms |
| gilblock (the GUI holding the GIL 80 ms every second) | 0 | 0 | 203.8 ms (1.3) | 52.1 ms | 151.8 ms |
| cpugil | 0 | 0 | 204.8 ms (1.4) | 52.1 ms | 152.7 ms |

Short checks (15-20 s idle, GUI worker and harness `wasapi-proc`
alternating): A/V 196.5-211.6 ms, 0 dropouts, 0 dry frames. The first of
them, the first session after the VB-Cable setting changes of section 7,
had VB-Cable's share at 177.5 ms (A/V 330.9 ms) for the whole run, with
Poise's share normal (153.4 ms): a VB-Cable start outlier, not seen in
~40 other starts.

## 9. A hiss on one video (not a regression)

A "small hiss here and there" heard through the GUI on headphones
turned out to come from one video, in every build including the
installed 1.1.0. Checked on a recorded session (R1-session: what Poise
received and what the headphones got, latmeter's record-only mode):

- The headphones got what the processing makes of the same input
  offline (same spectrum to 24 kHz within 0.5 dB); the clock bridge's
  resampling changes nothing (input and output spectra within 0.2 dB up
  to 22 kHz).
- The processing on master and on the installed build's code (ca909a2)
  give the same output (within 1.9 dB of high-frequency energy in any
  50 ms window); so do onnxruntime 1.19.2 and 1.31.0 (within -135 dB);
  the model files are byte-identical.
- The dial's range changed (strongest -80 dB in 1.1.0, -50 dB now,
  8bd9537): that lets through a faint leak, 95 % below 1 kHz, typically
  70 dB under the output; not the hiss.
- Silent stretches in the headphone loopback are 16-bit rounding of
  near-silence after the volume, not dropouts.

## 10. The FIFO's level per start: VB-Cable's paired packets

A trace build of the DLL (every capture packet, render cycle, bridge
read and rate-control window; a scratch patch, not in the shipped DLL),
16 starts of 12 s, passthrough engine, nothing else running. "Paired":
packets that came in the same wake-up as the one before, after a 20 ms
gap, instead of 10 ms apart.

| CABLE Input | Paired packets, per start | FIFO target at the end, per start |
|---|---|---|
| idle | 0, 0, 0-3, 7, 9, 12, 13, 22 % | 16.4 ms x5, 22.2, 23.3, 23.6 ms |
| a player started 2 s before | 1, 21-31 % (x7) | 19.5-24.9 ms, all raised |

- Each start keeps its rate of pairs for the whole session (steady from
  one second to the next), and the pairs fall at random, not in a
  rhythm. In a pair, the first packet arrives 20 ms after its time stamp
  instead of ~10 ms: Windows' audio engine missed a pass on CABLE Output
  and delivered two periods at once. VB-Cable's own time stamps stay
  10 ms apart (also in latmeter's recordings of every earlier run).
- One pair at the wrong moment, against a read, starves a FIFO held at
  16.4 ms: the first-second rises are those. The level the bridge ends
  at is what the pairs need: the worst read in the rest of the session
  had the safety's 5 ms left within -2 to +2 ms (median +0.8 ms with a
  player). So the rise is not left over from the start, and holding the
  FIFO lower instead would starve on every badly placed pair.
- Not the timer resolution: the system's was already 1 ms (latmeter
  asks for it too).

CABLE Output captured in exclusive mode instead (a test program, 24-bit
PCM, the driver's 3 ms period; latmeter playing into CABLE Input, its
clock as the reference, 5 starts each mode, alternating):

| Capture | Packets | Arrival after the time stamp | Late (paired) | Readable after CABLE Input's clock |
|---|---|---|---|---|
| shared (as Poise) | 480 (10 ms) | median 10-20 ms, per start | 0-31 % per start | median 63.9 ms (59.9-77.3) |
| exclusive | 144 (3 ms) | 0.6 ms (max 4.6) | 0.1-0.2 % | median 159.7 ms (155.0-160.1) |

Exclusive mode removes the pairs and the engine's 10-20 ms, but
VB-Cable then delivers the audio ~96 ms later: ~149 ms of buffer (its
latency setting, 7168 samples by default, would account for it; not
tested with another setting) plus one period. Not usable as it is.

Also no help:

- CABLE Input's engine at 128 frames (2.7 ms; a silent IAudioClient3
  stream on it moves every stream there to that period, as Microsoft's
  low-latency notes say): paired packets 0-26 % per start and VB-Cable's
  delay 57-72 ms, as without (5 starts each, stream started before or
  after the player).
- Capturing CABLE Input's loopback instead of CABLE Output: readable
  137-161 ms after CABLE Input's clock (the earlier cable-* recordings),
  vs 62-72 ms for CABLE Output.

### Steering the capture timing

When packets arrive after their time stamp ("age") stays put for a
session (median per second within 0.5 ms over 12 s), and pairs happen
only at the two ends: ~10.5 ms (just after VB-Cable's tick) and ~19.5 ms
(just before the next). Fresh starts land at an end more often than not
(5 of 8 with a player at 19.5 ms, 3 at 10.6-11.0). Stopping and starting
the same stream (Stop, Reset, Start) moves the age, mostly a little
later each time (+0.3-0.8 ms per restart in Poise, wrapping from 19.5 to
~10.6); a new client instead lands anywhere. VB-Cable's own delay (its
time stamps against CABLE Input's clock) does not change with restarts
(46.7 ms, then 62.7 ms for 7 restarts in one run), so only the age can
be chosen. A microphone's packets arrive 0.2 ms after their stamp after
any restart: hardware keeps the time itself.

The native path now restarts the capture before the bridge takes any
audio until 10 packets (after 3 skipped) arrive 12.5-15.5 ms after
their stamps with none paired (12.5-18 ms after 6 tries; as it comes
after 12; devices with packets younger than a period are left alone).
10 packets are enough: over 44 tries their median age was within
~0.3 ms of 20 packets', and restarts do not bunch the first packets
(pairs as frequent at every position after a restart). Starts with a
player running (trace build, passthrough, 15 s each):

| | Starts at the FIFO's floor (16.4 ms) | Packet age after the start | Paired | Restarts | Silence at the start |
|---|---|---|---|---|---|
| before (8 starts) | 0 | 10.6-11.0 or 19.5 ms | 1-31 % | - | ~0.05 s |
| steered, 20-packet tries (10 starts) | 10 | 12.5-13.6 ms | 0 | 0-6 | 0.4-2.3 s |
| steered, 10-packet tries (10 starts) | 10 | 12.4-14.1 ms | 0 | 1-4 | 0.3-0.7 s |

End to end, real DF3 in the audio process, 60 s idle each (F1-F3 with
20-packet tries, F4 with 10):

| Run | A/V | VB-Cable | Poise | FIFO | Restarts |
|---|---|---|---|---|---|
| F1-steer | 191.6 ms (p99-p1 0.9) | 47.4 ms | 144.1 ms | 16.4 ms | 2 |
| F2-steer | 198.6 ms (1.2) | 52.4 ms | 146.2 ms | 16.4 ms | 1 |
| F3-steer | 196.9 ms, then 206.1 after a staircase step at 11 s | 62.5 ms | 143.6 ms | 16.4 ms | 3 |
| F4-steer | 193.2 ms (1.3) | 48.5 ms | 144.8 ms | 16.4 ms | 0 |

Poise's share is 143.6-146.2 ms on every start (147 ms on W1/W2, which
started clean; a start with pairs adds its FIFO's ~8 ms). VB-Cable's share
now includes the steered age (12.4-14.1 ms instead of up to 19.5 ms) but
still varies with VB-Cable's own delay. The cost: 0.3-0.7 s of silence
when a session starts (up to ~1.6 s if all 12 tries are needed); a
session took ~1 s from start to sound before.

## Open issues

- The glitch staircase (section 3).
- PortAudio's bad starts (section 4).
- VB-Cable's share of the A/V offset: 45-68 ms depending on the start;
  neither its latency setting (section 7) nor restarting the capture
  (section 10) reduces its own part of it.
