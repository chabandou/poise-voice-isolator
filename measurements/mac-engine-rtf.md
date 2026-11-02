# macOS engine measurements: load, RTF, isolation

Measured 2026-11-02 on the port's Apple Silicon host. Every number here
comes from `tools/mac_engine_smoke.py`, which drives the real engine
classes (`create_engine` → `DeepFilterNet3Engine` / `GTCRNEngine`) frame by
frame at the frame size each engine declares — the app's framing, streaming
state, GTCRN's 48→16→48 kHz resampling and dry mix, not a reimplementation.

## Setup

- Apple M2 Pro (10 cores: 6 performance + 4 efficiency), 16 GB, macOS
  27.0.1 (26A434), arm64, on AC power, idle machine, no other busy process
  during the runs
  (`pmset -g batt` → "AC Power"; `pmset -g therm` → no thermal warning).
- Python 3.12.16, numpy 1.26.4, **onnxruntime 1.31.1**, CPU only: the wheel
  also ships `CoreMLExecutionProvider`, but `engines/onnx_model.py`'s
  `load_session()` asks for `CPUExecutionProvider` explicitly, so that is
  what these numbers measure.
- ONNX Runtime threads: `intra_op` 2, `inter_op` 1 — the repo defaults from
  `constants.py:125-127` on this platform (`POISE_ONNX_THREADS` unset).
- Attenuation limit **-60 dB** (`create_engine()` default, i.e. the dry mix is
  ~0.001 and effectively absent). The app's strength dial only spans -50 .. -10
  dB with -50 as its default (`tui/settings.py:25-26`,
  `gui/widgets/dial.py:89-91`), so a user cannot reach this setting; the
  isolation figures move by less than 0.5 dB across that range (0.001 vs
  0.0032 dry fraction), so they are not sensitive to it.
- No audio fixture exists in the repo (no `.wav`/`.flac`/`.mp3` anywhere,
  `tests/` and `measurements/` included), so the test signal is synthesized
  in the tool: a formant-style voice (harmonic source + aspiration noise
  through moving formants, 3-6 Hz syllable envelope, fricative bursts) and a
  music bed (I-V-vi-IV chords with a melody, kick and hi-hat, 120 bpm). Both
  at -20 dBFS RMS.
- Signal: 1 s segments alternating `speech` / `music` / `mix`, 30 s total,
  seed 20261102 unless stated. The same signal feeds both engines, for both
  the timing pass and the isolation pass.

## 1. Do both engines load and run on macOS arm64?

Yes. Both vendored models load through `load_session()` and run frame by
frame with their own state feedback, no fallback, no provider warning:

| Engine | Model file | Load | Frame | Frames run |
|:--|:--|:--:|:--:|:--:|
| DeepFilterNet3 | `denoiser_model_df3.onnx` (8.9 MB) + states `.npz` | 0.016-0.057 s | 512 samples (10.67 ms) | 2821 |
| GTCRN | `gtcrn.onnx` (248 KB) | 0.015-0.017 s | 768 samples (16.0 ms) | 1881 |

Declared engine latency (`latency_samples`, read off the live objects and
matching `deepfilternet3.py:73` = 3 frames and `gtcrn.py:110` = FRAME + 96):

| Engine | `latency_samples` | ms at 48 kHz |
|:--|:--:|:--:|
| DeepFilterNet3 | 1536 | 32.0 |
| GTCRN | 864 | 18.0 |

RNNoise is not in this measurement: it has no macOS library by design
(`engines/rnnoise_lib.py`), so it is not a port candidate.

## 2. Real-time factor

RTF = processing time ÷ audio time. Mean RTF is
`sum(frame times) / (frames × frame duration)`; p95 RTF is
`p95(frame time) / frame duration`. Measured over 30.1 s of audio per engine
after a 2 s warm-up, three consecutive runs of the same command:

| Engine | Frame ms mean | Frame ms p95 | Frame ms max | RTF mean | RTF p95 | 30 s of audio takes |
|:--|:--:|:--:|:--:|:--:|:--:|:--:|
| DeepFilterNet3 | 0.334-0.378 | 0.381-0.396 | 0.539-0.634 | **0.031-0.035** | 0.036-0.037 | 0.94-1.07 s |
| GTCRN | 0.236-0.252 | 0.240-0.258 | 0.286-0.373 | **0.015-0.016** | 0.015-0.016 | 0.44-0.47 s |

The max column is one frame in a run and does move: in the other runs of this
session the worst single frame was 1.59 ms (DF3) and 0.83 ms (GTCRN), while
the means and p95s stayed where the table has them. That is scheduler noise
on one frame, not a cost the engine pays regularly.

Against the plan's acceptance thresholds (`README.md:56` numbers restated as
`DF3 < 0.30`, `GTCRN < 0.10`):

| Engine | Measured RTF | Threshold | Verdict |
|:--|:--:|:--:|:--|
| DeepFilterNet3 | 0.031-0.035 | < 0.30 | **met, ~9× under** |
| GTCRN | 0.015-0.016 | < 0.10 | **met, ~6.7× under** |

Both are far below the ~0.12 / ~0.04 the README quotes for a Ryzen 5 4500U,
and the ordering (GTCRN ≈ 2.3× cheaper than DF3) is the same. DF3 runs 93.75
frames per second of audio and GTCRN 62.5, so the per-frame budget (10.67 /
16.0 ms) is barely touched: even the worst single frame seen (1.59 ms) used
15 % of a DF3 frame.

## 3. Does it isolate speech?

**Metric, defined here:** the signal is cut into 1.0 s segments, each
labelled `speech` (voice only), `music` (music only) or `mix` (both). For
each segment the analysed window is the middle 60 % (clear of the 20 ms gate
ramps and of the engine's own latency); the engine's output is read
`latency_samples` later than the input, which is the alignment the engines
declare. The reported number is

```
delta_dB = 10 * log10( mean(out²) / mean(in²) )   over that window
```

so 0 dB = the segment's energy is unchanged, -40 dB = 1/10000 of it left.
The table gives the mean over the 10 segments of each kind, then the
per-segment range.

| Engine | speech-only | music-only | mix | separation (music − speech) |
|:--|:--:|:--:|:--:|:--:|
| DeepFilterNet3 | **-5.75 dB** (-18.83 .. -0.89) | **-41.42 dB** (-48.76 .. -27.65) | -4.68 dB | **35.7 dB** |
| GTCRN | **-4.37 dB** (-11.68 .. -0.39) | **-35.41 dB** (-48.21 .. -27.48) | -6.59 dB | **31.0 dB** |

Identical to the last digit in all three repeat runs (the signal is seeded
and the models are deterministic). Two other seeds, same 30 s / 10 segments
each, to show this is not one lucky signal:

| Seed | DF3 speech | DF3 music | GTCRN speech | GTCRN music |
|:--|:--:|:--:|:--:|:--:|
| 20261102 | -5.75 dB (-18.83 .. -0.89) | -41.42 dB (-48.76 .. -27.65) | -4.37 dB (-11.68 .. -0.39) | -35.41 dB (-48.21 .. -27.48) |
| 1 | -4.20 dB (-9.02 .. -0.81) | -42.44 dB (-48.58 .. -34.09) | -4.13 dB (-5.49 .. -1.33) | -35.41 dB (-46.54 .. -28.84) |
| 2 | -3.93 dB (-9.97 .. -0.51) | -40.77 dB (-50.03 .. -32.29) | -5.97 dB (-8.67 .. -2.63) | -35.65 dB (-46.94 .. -29.23) |

Every range above is printed by the tool for that seed, so all 30 segments
behind the claim below have a supporting number.

**Verdict: the result supports "speech retained, music suppressed".** The
music-only energy falls by at least 27 dB in every one of the 30 music
segments measured (3 seeds × 10; worst single segment -27.65 dB DF3, -27.48 dB
GTCRN; segment means 35-42 dB), while speech-only
energy stays within 6 dB of its input level in 8 of 10 segments on the
default seed, for both engines. The threshold behind "retained" is stated so
it can regress: **mean speech energy no worse than -6 dB, and no single 1 s
segment worse than -20 dB** — both engines clear the mean on all three seeds
(worst -5.97 dB, GTCRN seed 2), and DF3 misses the per-segment bound once
(-18.83 dB).

The `mix` row is context, not part of the metric, and it says something the
solo rows cannot: both engines pull back when a voice is present. An ideal
music removal plus the engine's own voice loss would drop a mixed segment by
-8.8 dB (DF3: 3.0 + 5.75) and -7.4 dB (GTCRN: 3.0 + 4.37) for two equal-level
sources; the engines drop it by 4.7 and 6.6 dB, so part of what they do to a
lone music bed they do not do when speech is playing over it.

Two caveats belong with the number rather than under it: both engines also
shave a few dB off the speech itself (DF3 -5.8 dB, GTCRN -4.4 dB on this
signal), and single segments can do much worse than the mean (DF3's worst
1 s speech segment lost 18.8 dB, GTCRN's 11.7 dB), so "speech retained" is a
statement about a 30 s average, not about every second. The app's output
stage adds `OUTPUT_GAIN_DB = +6.0` (`constants.py:116`) before the limiter, so
in the product DF3's net speech change is about +0.25 dB: the -5.8 dB here is
not a loudness regression. The metric also weights the loudest part of each
0.6 s window, so loss inside quiet syllables is invisible; and GTCRN's 16 kHz
path band-limits its output to ~7.6 kHz — here the tonal music stops at 4 kHz
and the hi-hat bursts sit ~38 dB lower, so its -35 dB is the model and not the
resampler, but a high-band-only residual would be measured as the resampler's.

## Commands

```sh
# from the repo root

# the three runs behind sections 2 and 3 (repeat the line for each run)
.venv/bin/python tools/mac_engine_smoke.py

# the other two seeds of the seed table
.venv/bin/python tools/mac_engine_smoke.py --seed 1
.venv/bin/python tools/mac_engine_smoke.py --seed 2

# longer audio, other warm-up
.venv/bin/python tools/mac_engine_smoke.py --seconds 60 --warmup-seconds 2
```

Exit code 0 when both engines ran; if one cannot load or run, the tool
prints that engine's own traceback and exits 1 (nothing is worked around).

## What this does not prove

- **Nothing about real content.** No recording is in the repo, so both
  signals are synthesized. A model trained on real speech and music is being
  asked about a formant synthesizer and a MIDI-like chord bed; whether real
  music (vocals, drums, broadband transients) is suppressed this far, and how
  much of a real voice survives, is not shown here. It answers "does the
  engine pass this voice and drop this music", not "how good is Poise on a
  YouTube video".
- **Nothing about a busy or warm machine.** Three 30 s runs per engine on AC
  power, all on an idle machine. No background load, no thermal soak, no
  battery. The max frame time (0.6-1.6 ms DF3) is not a worst case under
  load; the Windows measurements (`measurements/windows-latency.md`) show
  frame times can multiply under CPU contention, and a port that misses a
  frame plays dry.
- **Nothing about p99.9 or the frame budget under load.** p95 is reported;
  with a 10.67 ms budget and a 0.37 ms mean there is a lot of headroom, but
  this is a mean/p95 measurement, not a deadline-miss count.
- **Only the CPU provider.** The CoreML execution provider ships in this
  wheel and is not used by `load_session()`; a CoreML or ANE path would be a
  different (unmeasured) set of numbers, and this says nothing about whether
  it would be faster or slower.
- **Only the engine, not the audio path.** No device, no tap, no core delay,
  no worker thread. It does not measure A/V offset (that is T5h), nor whether
  the inference thread meets the deadline while a Core Audio IOProc runs
  beside it. The timer wraps `engine.process_frame()` alone: the app adds its
  own per-frame work on top (AAD, the +6 dB makeup gain, the soft limiter, the
  level meter and fractional-block resampling, `processor.py:358-386`), so
  these are engine-only numbers and `MAC_MARGIN_SAMPLES` must be sized from
  T5's `frames_dry` under load, not from this table alone.
- **Warm state only.** The measured pass runs after a 2 s warm-up and keeps
  that state, so the first second of a fresh session is excluded. That
  exclusion is about timing (page-in, ONNX Runtime's arena growth, the CPU's
  boost clock), not about the isolation number: on this signal a cold
  engine's first speech segment differed from its warm value by under 0.5 dB
  (-5.49 vs -5.79 dB DF3, -0.72 vs -0.39 dB GTCRN).
- **Energy, not perception.** "Music suppressed by 41 dB" is an energy ratio
  over 0.6 s windows; a quiet musical residual inside the speech band would
  not show up as a failure here, and speech intelligibility was not tested.
- **Not a regression test.** No baseline from another platform is in the
  repo to compare against: the README's Ryzen 5 4500U numbers are from
  another host, so they are a reference point, not a baseline for pass/fail.
