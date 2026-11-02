# macOS tap spike: feasibility probes for the Core Audio capture path

Measured 2026-11-02 on the port's Apple Silicon host. This is the gate G2 evidence for the plan's
architecture (§3): a global `CATapDescription` with `MuteBehaviorMutedWhenTapped`, a private aggregate
device whose clock master is the real output device, and one IOProc. Code: `native/poise_coreaudio/`
(`poise_coreaudio.m`, `Makefile`), bundle wrapper `tools/make_dev_app.sh`; raw run logs are quoted below.

## Setup

- Mac14,9, Apple M2 Pro (10 cores), 16 GB, **macOS 27.0.1 (26A434)**, arm64, AC power.
- Built with the Xcode 27.2 SDK, `-mmacosx-version-min=14.2`, `-fobjc-arc`, arm64.
- Every run below is **from the app bundle** (`build/PoiseDev.app`, bundle id `dev.poise.spike`,
  ad-hoc signed), launched through LaunchServices (`open -n -W … --args …`), because the TCC grant is
  attributed to the bundle — see (b).
- The output device throughout is the built-in "MacBook Pro Speakers" at 48 kHz.

## (a) Darwin semaphores

`semin_init` → `rc=-1 errno=78 "Function not implemented"`; `sem_timedwait` → *call to undeclared
function*. The Apple branch of `native/core/poise_core.c` therefore needs a different primitive; the
choice and its measurements are in `measurements/mac-wake.md` (Mach semaphores adopted).

## (b) Permission: which grant, and how it fails

| question | answer (measured) |
|:--|:--|
| TCC service | `kTCCServiceAudioCapture` (`log show`: `service=kTCCServiceAudioCapture`, `target_token={pid:…}`) |
| Info.plist key | `NSAudioCaptureUsageDescription` — present in the bundle; the bundle must be **non-sandboxed** |
| Where the user grants it | System Settings → Privacy & Security → **Screen & System Audio Recording** → the **"System Audio Recording Only"** section (the screenshot the operator confirmed shows PoiseDev toggled on there) |
| Prompt text | the standard "…would like to record this computer's audio" dialog with **Allow** / **Don't Allow** |
| What a denial looks like in code | **no error from the HAL.** Two symptoms were observed on this host: the aggregate starts and the IOProc runs with all-zero buffers, or the aggregate starts and no IOProc callback ever arrives. `AudioHardwareCreateProcessTap`/`AudioDeviceStart` return `noErr` in both cases; the only error a caller can see is one it invents itself (the spike exits non-zero after 3 s of no callbacks). |
| What tccd says | `sending empty reply to requestor=com.apple.audio.coreaudiod for service=kTCCServiceAudioCapture — auth_value absent; client will receive kTCCErrorDomain Code=2` |
| Grant identity | keyed to the **code identity**. After re-signing the ad-hoc bundle (`make_dev_app.sh` following a rebuild) capture stopped working; re-granting (`tccutil reset AudioCapture dev.poise.spike`, relaunch, click Allow) restored it immediately (`peak -9.1 dBFS`). The symptom observed after the re-sign was `the aggregate started (no error) but no IOProc callback arrived in 3 s`, which is **ambiguous**: the code documents the same symptom after a previous instance was torn down (`poise_coreaudio.m:1156-1159`), and no tccd line was captured for that particular run. What is not ambiguous is the zeros case, where `tccd` logged `auth_value absent … kTCCErrorDomain Code=2` — that is the evidence the contract C2b rests on. |
| Running the binary directly | `build/PoiseDev.app/Contents/MacOS/poise_coreaudio` run from a shell is attributed to the **terminal's** identity, not the bundle's. Whether it captures therefore depends on whether *that terminal* holds the grant, not on Poise: observed both ways on this host (zeros while the terminal lacked it, full capture once Ghostty held Screen & System Audio Recording). For a *user-facing* build, LaunchServices (`open`, i.e. a real app launch) is the supported path; for developer runs from a shell, the terminal's own grant applies. |
| Is the Settings toggle sufficient? | not by itself: a toggle that exists from an earlier denial can read as ON while tccd still reports `auth_value absent`. The reliable sequence is `tccutil reset AudioCapture <bundle-id>` → relaunch → **Allow** (not "Allow once"). |

**Design consequences.** The node cannot detect a denied grant through the audio API, so (i) the doctor
check must compare captured energy against "is the system playing", (ii) C1's watchdog cannot use
"no callbacks" as its only trigger — the "no callback in 3 s" path *is* what a bad grant looks like —
and (iii) a stable signing identity is load-bearing for the product, not cosmetic: with an ad-hoc
signature every rebuild re-prompts, which is exactly what a user of a self-built copy would hit.

## (c) Format and sample rate

Requested: 48000 Hz, 2 ch, Float32, **non-interleaved**. What the HAL actually gave:

```
poise: tap format is interleaved; aggregate input is interleaved; aggregate output is interleaved
poise: tap format (kAudioTapPropertyFormat): 48000 Hz, 2 ch, Float32 …, flags 0x9, 8 bytes/frame
poise: aggregate input stream  (read back): 48000 Hz, 2 ch, Float32 … flags 0x9
poise: aggregate output stream (read back): 48000 Hz, 2 ch, Float32 … flags 0x9
poise: output device stream (virtual):      48000 Hz, 2 ch, Float32 … flags 0x9
```

- **Interleaved, not planar.** `kAudioFormatFlagIsNonInterleaved` is not honoured for the tap or the
  aggregate streams on this OS. Contract C2 must therefore say "take the ASBD you are given and handle
  interleaved", not "demand non-interleaved".
- **The tap follows the device's nominal rate.** With `--rate 44100` the tap stream still came back at
  48 kHz while the aggregate output came back at 44.1 kHz, i.e. a **mixed-rate aggregate** (48k in /
  44.1k out) is constructible — and the spike refuses to run in that state. Two distinct refusals were
  observed, both naming the real rate (logs `/tmp/r44.out`, `/tmp/drift600b.err`):

  ```
  (--rate 44100, device at 48000)
  refusing to run: the aggregate input stream is 48000 Hz, 2 ch, flags 0x9, not the
  requested 44100 Hz Float32 non-interleaved (device "MacBook Pro Speakers" runs at 48000 Hz)

  (default 48000, device left at 44100 by the previous run)
  refusing to run: the aggregate output stream is 44100 Hz, 2 ch, flags 0x9, not the
  requested 48000 Hz Float32 non-interleaved (device "MacBook Pro Speakers" runs at 44100 Hz)
  ```

  A real node
  must either force the device to 48 kHz or resample; running the 48 kHz engine on 44.1 kHz buffers
  would make every `ms()` in `_loop_util.py` and the whole A/V budget wrong by 9 %.
- **The spike never writes the device's rate.** It only reads `kAudioDevicePropertyNominalSampleRate`
  (`poise_coreaudio.m:997-999`, printed at `:1254`) and sets the *aggregate stream's* virtual format; the
  two `hal_set` calls in the file are `kAudioStreamPropertyVirtualFormat` and the advisory
  `kAudioTapPropertyFormat`. The device was nevertheless observed at 44 100 Hz after a `--rate 44100`
  run and back at 48 000 Hz afterwards — some other actor changed it, so a real node must not assume it
  controls the rate, and (per C2) must either force it explicitly or refuse. Implementing set-and-restore
  is ~15 lines and belongs in T4.
- `kAudioTapPropertyFormat` is advisory and rejects writes here (`OSStatus 1852797029 'nope'`), and
  `kAudioSubTapPropertyDriftCompensation` is unreadable (`560947818 '!obj'`) — so C3's pre-decided
  fallback "turn on per-sub-tap drift compensation" is **not available on this OS**. If drift appears,
  the bridge (`wasapi_node.py:104-130` analogue) is the only option.

## (d) Drift between the tap and the output

Reported by the IOProc as "tap advanced N samples, output advanced N samples over the same K callbacks":

| run | wall | callbacks | quantum | tap frames | drift |
|:--|:--:|:--:|:--:|:--:|:--:|
| 1 | 15.26 s | 1433 | 512 | 733 696 | **+0 samples, +0.00 ppm** |
| 2 | 12.40 s | 1165 | 512 | 596 480 | +0 samples, +0.00 ppm |
| 3 | 30.00 s | 2861 | 512 | 1 464 320 | +0 samples, +0.00 ppm |
| 4 | 92.85 s | 8708 | 512 | 4 458 496 | +0 samples, +0.00 ppm |
| 5 | **610.36 s** | **57 223** | 512 | **29 298 176** | **+0 samples, +0.00 ppm** |

The tap and the output are driven by the **same** aggregate clock (the output device is clock master),
so the two counters advance in lockstep. The 10-minute run is the soak evidence: **57 223 callbacks,
29 298 176 frames each side, zero samples of drift**, i.e. below the 0.034 ppm resolution of a 29.3 M-sample
comparison, with `peak -1.2 dBFS` (the looping tone), `0 dropped frames` and `0 overloads`. `quantum` is a fixed **512 frames** on this
device, which is exactly `PW_QUANTUM`, so the existing delay sizing carries over unchanged.

Verbatim, the 10-minute run (`--seconds 600 --passthrough --out /tmp/drift10.wav`, launched from the
bundle, a 10 s -34 dBFS tone looping throughout):

```
poise: wall 610.36 s; tap delivered 29298176 frames (610.379 s), output consumed 29298176 frames (610.379 s)
poise: drift output-tap +0 frames, +0.00 ppm
poise: clocks: tap advanced 29297664 samples, output advanced 29297664 samples over the same 57223 callbacks:
       +0 samples, +0.00 ppm
poise: callbacks 57223, quantum 512..512 frames
poise: peak -1.2 dBFS, rms -33.7 dBFS, last-second rms -38.6 dBFS
poise: RT policy: time-constraint; dropped 0 frames; overloads 0
```

## (e) Feedback: Poise's own output is not re-captured

The tap is created with `initStereoGlobalTapButExcludeProcesses` and Poise's own process object in the
exclusion list; the readback confirms it:

```
poise: tap description read back: name="Poise Tap Spike" exclusive=1 mixdown=1 mono=0
       private=0 muteBehavior=2 processes=[134]
```

With `--passthrough` (captured audio written back to the aggregate's output) the run is stable — peak
and last-second RMS do not grow over 93 s, and the process never re-captures its own playout. This is
the property that makes the pass-through leg safe for the T5h latency harness.

## (f) Bluetooth / AirPlay output

**Unanswered on this host** — there is no Bluetooth or AirPlay device present:

```
LG HDR WFHD            hdmi     48000 Hz  out=yes
C922 Pro Stream Webcam usb      16000 Hz  out=no
MacBook Pro Microphone built-in 48000 Hz  out=no
MacBook Pro Speakers   built-in 48000 Hz  out=yes
```

An aggregate containing a Bluetooth device is the one common case that could break the design (AirPods
are a very common output). It needs a run on a machine with paired AirPods; until then the node must
fail with a clear message rather than silently.

## Realtime behaviour

```
poise: RT policy: time-constraint; dropped 0 frames; overloads 0
poise: RT policy read back on the IOProc thread: period 256000 ticks,
       computation 128000, constraint 256000, preemptible 0
poise: output-minus-tap time stamp delta: 1147..1147 samples (input time flags 0x7, output time flags 0x7)
```

- `THREAD_TIME_CONSTRAINT_POLICY` is applied on the IOProc thread (period 10.667 ms, computation 5.33 ms,
  constraint 10.667 ms) and 0 frames were dropped or counted as overloads across every run above.
- The output-minus-tap timestamp delta is a constant **1147 samples ≈ 23.9 ms**: the playout leg's own
  latency, which the A/V budget must include on top of the engine and core delays.

## A bug this spike found in itself (fixed)

The run summary's `peak`/`rms`/`last-second rms` were accumulated inside `wav_write()`, which returns
early when no `--out` is given — so every run without `--out` reported `peak -120.0 dBFS` and printed
`captured only silence: either nothing was playing, or the System Audio Recording grant is missing`,
even while it was capturing a tone at -9 dBFS into its ring buffer. Levels are now measured in a
meter-only instance that exists with or without a file. Worth recording because it cost real time and
because the same trap applies to any "measure only when recording" shortcut in T4.

## What this does not prove

- **A/V offset**: nothing here measures what leaves the speakers (that is T5h, with a microphone).
- **Bluetooth/AirPlay**, per (f).
- **The engine in the loop**: this spike passes audio through; T5 runs the real fixed-delay core and the
  ONNX engines and asserts `frames_dry == 0`.
- **Long-run stability** beyond the 10-minute run below, and nothing about thermal throttling.
- **Other macOS versions**: everything above is macOS 27.0.1. The floor the code targets is 14.2; a 14.x
  run may differ in the TCC pane wording and in which tap properties exist.

## Reproduce

```sh
# from the repo root
make -C native/poise_coreaudio
bash tools/make_dev_app.sh                     # builds + ad-hoc signs build/PoiseDev.app
tccutil reset AudioCapture dev.poise.spike     # re-arm the grant (no sudo)
open -n -W build/PoiseDev.app --stdout /tmp/poise.out --stderr /tmp/poise.err \
     --args --seconds 10 --passthrough --out /tmp/poise.wav
# click Allow in the dialog; then:
grep -E "peak|rms|callbacks|drift|clocks" /tmp/poise.out
```

## Gate G2 verdict

**GO**, with three amendments to the plan that this spike earned:

1. **C2** must accept interleaved Float32 (the HAL will not give planar), and must handle the mixed-rate
   aggregate case by forcing the device rate or resampling — refusing is the correct v1 behaviour.
2. **C3**'s "per-sub-tap drift compensation" fallback does not exist on this OS; the clock bridge is the
   only fallback, and the short-run drift is zero.
3. **C1/T9** must treat a denied grant as *silence* (or as missing callbacks) with no error, and the
   doctor check must compare energy against system activity. A stable signing identity is required for
   the grant to survive rebuilds — T12 is load-bearing for that, not cosmetic.
