#!/usr/bin/env python3
"""
macOS engine smoke test: do the two ONNX engines load, run, keep up and isolate?

    .venv/bin/python tools/mac_engine_smoke.py
    .venv/bin/python tools/mac_engine_smoke.py --seconds 60 --seed 1

Drives the real engine classes (`stream_denoiser.engines.create_engine` ->
`DeepFilterNet3Engine` / `GTCRNEngine`) frame by frame at the frame size each
engine declares, so the framing, the streaming state, GTCRN's 48->16->48 kHz
resampling and the dry mix are the app's, not a copy of them.

Per engine it reports:

* load time and the declared `latency_samples`,
* per-frame inference time (mean/p95/max) and
  RTF = processing time / audio time, where the mean RTF is
  sum(frame times) / (frames * frame duration) and the p95 RTF is
  p95(frame time) / frame duration,
* energy before/after the engine in speech-only and music-only segments of a
  synthesized mixture, in dB: 10*log10(mean power out / mean power in).

The mixture is synthesized here (formant-style speech, chord + percussion
music) because the repo ships no audio fixture. Segment layout, the gate
ramps and the analysed fraction are in the SIGNALS section below; the engine
output is read `latency_samples` later than the input, which is how the
report's windows are aligned.

Exits non-zero, printing the engine's own exception, if either engine cannot
load or run.
"""
import argparse
import platform
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from stream_denoiser.constants import (  # noqa: E402
    MODEL_DEEPFILTERNET3,
    MODEL_GTCRN,
    ONNX_INTER_OP_THREADS,
    ONNX_INTRA_OP_THREADS,
)
from stream_denoiser.engines import create_engine  # noqa: E402

SR = 48000

# ---------------------------------------------------------------- signals ---
# The mixture alternates these segment kinds, one second each; the same
# signal feeds both engines and both the timing and the isolation pass.
PATTERN = ("speech", "music", "mix")
SEGMENT_SECONDS = 1.0
#: Segment kinds each source plays in ("mix" = both).
SOURCE_SEGMENTS = {"speech": ("speech", "mix"), "music": ("music", "mix")}
#: Analysed part of each segment: the middle 60%, clear of the 20 ms gate
#: ramps at the segment edges and of the engine's own latency.
ANALYSIS_FRACTION = 0.6
#: Raised-cosine ramp on each source's on/off gate at a segment edge.
GATE_RAMP_SECONDS = 0.02
#: RMS level of each source while it plays (0.1 = -20 dBFS).
SOURCE_RMS = 0.1
#: Trailing silence so the last segment's latency-shifted output window exists.
TAIL_SECONDS = 0.1

#: Formants (F1-F4, Hz) and bandwidths (Hz) of four vowels: a, e, o, i.
VOWELS = (
    ((730.0, 1090.0, 2440.0, 3400.0), (90.0, 110.0, 170.0, 250.0)),
    ((530.0, 1840.0, 2480.0, 3500.0), (70.0, 100.0, 160.0, 240.0)),
    ((300.0, 870.0, 2240.0, 3300.0), (60.0, 90.0, 150.0, 230.0)),
    ((270.0, 2290.0, 3010.0, 3500.0), (60.0, 110.0, 170.0, 250.0)),
)
SYLLABLE_SECONDS = 0.24
SPEECH_F0_HZ = (105.0, 145.0)

#: I-V-vi-IV in C, MIDI note numbers, two seconds per chord, one melody note
#: per chord half. MIDI 60 = C4 = 261.6 Hz.
CHORDS = ((48, 52, 55), (55, 59, 62), (57, 60, 64), (53, 57, 60))
MELODY = (72, 76, 79, 74)
CHORD_SECONDS = 2.0
MUSIC_MAX_HZ = 4000.0
MUSIC_MAX_HARMONICS = 20


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.asarray(x, np.float64) ** 2)))


def _normalize(x: np.ndarray, rms: float) -> np.ndarray:
    """Scale `x` to the given RMS (0.1 = -20 dBFS), as float32."""
    current = _rms(x)
    return (x * (rms / current) if current > 0.0 else x).astype(np.float32)


def _formant_gain(freqs: np.ndarray, formants, bandwidths) -> np.ndarray:
    """Magnitude of a cascade of 2-pole resonances at `freqs` (unnormalized)."""
    f = np.asarray(freqs, np.float64)
    gain = np.zeros_like(f)
    for center, bandwidth in zip(formants, bandwidths):
        gain += 1.0 / np.sqrt((1.0 - (f / center) ** 2) ** 2
                              + (f / bandwidth) ** 2)
    return gain


def _syllable_envelope(seconds: float, rng) -> Tuple[np.ndarray, np.ndarray]:
    """
    Syllable amplitude envelope and its vowel index per sample.

    Syllables of 0.19-0.29 s with a rise-fall shape and a short gap between
    them, a phrase pause now and then, and a vowel chosen per syllable.
    """
    n = int(seconds * SR)
    env = np.zeros(n, dtype=np.float64)
    vowel_at = np.zeros(n, dtype=np.int64)
    pos = 0.0
    while pos < seconds:
        duration = SYLLABLE_SECONDS * rng.uniform(0.8, 1.2)
        voiced = duration * 0.75
        shape = np.sin(np.pi * np.arange(int(voiced * SR))
                       / max(int(voiced * SR), 1)) ** 1.2
        start = int(pos * SR)
        end = min(start + shape.shape[0], n)
        env[start:end] = rng.uniform(0.55, 1.0) * shape[:end - start]
        vowel_at[start:end] = rng.integers(0, len(VOWELS))
        pos += duration
        if rng.random() < 0.15:
            pos += 0.18
    return env, vowel_at


def _f0_contour(seconds: float, env: np.ndarray, rng) -> np.ndarray:
    """
    Pitch: a per-syllable base in SPEECH_F0_HZ held across each voiced run
    and ramped between runs, with declination, jitter and 5 Hz vibrato.
    """
    n = env.shape[0]
    t = np.arange(n) / SR
    voiced = env > 1e-3
    edges = np.flatnonzero(np.diff(np.concatenate(([0], voiced.view(np.int8),
                                                   [0]))))
    mids = [0]
    values = [rng.uniform(*SPEECH_F0_HZ)]
    for start, end in zip(edges[0::2], edges[1::2]):
        mids.append((start + end) // 2)
        values.append(rng.uniform(*SPEECH_F0_HZ))
    mids.append(n)
    values.append(values[-1])
    base = np.interp(np.arange(n), mids, values)
    # Jitter: a slow random walk of +-0.5 % (a real voice is never steady).
    knots = np.arange(0, n, int(0.02 * SR))
    jitter = np.interp(np.arange(n), knots, rng.standard_normal(knots.shape[0]))
    jitter = 1.0 + 0.005 * jitter / max(float(np.abs(jitter).max()), 1e-12)
    declination = 1.0 - 0.12 * (t / max(seconds, 1e-9))
    vibrato = 1.0 + 0.02 * np.sin(2.0 * np.pi * 5.0 * t)
    return base * jitter * declination * vibrato


def speech_like(seconds: float, rng) -> np.ndarray:
    """
    Synthetic speech: a harmonic (glottal) source plus aspiration noise,
    both shaped by moving formants, under a syllable envelope, with
    occasional fricative noise bursts.

    Not a recording: enough of speech's structure (harmonicity, a noise floor
    under the harmonics, a formant envelope, 3-6 Hz syllabic modulation,
    fricatives) for a speech model to treat it as speech, and nothing else.
    """
    n = int(seconds * SR)
    env, vowel_at = _syllable_envelope(seconds, rng)
    f0 = _f0_contour(seconds, env, rng)
    phase = 2.0 * np.pi * np.cumsum(f0) / SR

    # Formant tracks: interpolate each formant between syllable centers.
    centers = np.arange(0, n, int(SYLLABLE_SECONDS * SR))
    formant_tracks = []
    for index in range(len(VOWELS[0][0])):
        values = np.array([VOWELS[int(vowel_at[min(c, n - 1)])][0][index]
                           for c in centers])
        formant_tracks.append(np.interp(np.arange(n), centers, values))

    # Harmonic sum, 20 ms frames at 50% overlap with a Hann window: the
    # amplitude of each harmonic follows the formants at the frame center,
    # while the phase stays continuous across frames.
    frame, hop = int(0.02 * SR), int(0.01 * SR)
    window = np.hanning(frame)
    out = np.zeros(n, dtype=np.float64)
    top_hz = 7000.0
    # One fixed phase per harmonic (a glottal pulse train is not sine-phase);
    # re-randomizing per frame would make the source noise, not voice.
    offsets = rng.uniform(0.0, 2.0 * np.pi, int(top_hz / float(f0.min())) + 2)
    for start in range(0, n - frame, hop):
        center = start + frame // 2
        f_center = f0[center]
        formants = [track[center] for track in formant_tracks]
        bandwidths = VOWELS[int(vowel_at[center])][1]
        harmonics = np.arange(1, max(int(top_hz / f_center), 2) + 1)
        gains = _formant_gain(harmonics * f_center, formants, bandwidths)
        gains = gains / (harmonics ** 1.0)          # glottal spectral tilt
        gains = gains / max(float(gains.max()), 1e-12)
        block = np.sin(np.outer(harmonics, phase[start:start + frame])
                       + offsets[:harmonics.shape[0]][:, None])
        out[start:start + frame] += window * (gains[:, None] * block).sum(axis=0)

    out *= env

    # Aspiration: noise through the same vocal tract (an average vowel's
    # formants), 26 dB under the harmonics, present only while voiced. Real
    # speech has this noise floor between the harmonics; without it the source
    # is a set of pure tones, which is not what a speech model is trained on.
    noise = rng.standard_normal(n)
    freqs = np.fft.rfftfreq(n, 1.0 / SR)
    spectrum = np.fft.rfft(noise)
    aspiration_shape = _formant_gain(freqs, (500.0, 1500.0, 2500.0, 3400.0),
                                     (80.0, 100.0, 150.0, 250.0))
    aspiration_shape /= max(float(aspiration_shape.max()), 1e-12)
    aspiration = np.fft.irfft(spectrum * aspiration_shape, n) * env
    out += 0.05 * aspiration / max(_rms(aspiration), 1e-12) * _rms(out)

    # Fricatives: high-band noise bursts at a third of the syllable onsets.
    band = np.clip((freqs - 2500.0) / 2000.0, 0.0, 1.0) \
        * np.clip((8000.0 - freqs) / 2000.0, 0.0, 1.0)
    hiss = np.fft.irfft(spectrum * band, n)
    hiss_env = np.zeros(n)
    pos = 0.0
    while pos < seconds:
        if rng.random() < 0.35:
            start = int(pos * SR)
            length = int(0.07 * SR)
            burst = np.hanning(length)
            end = min(start + length, n)
            hiss_env[start:end] = burst[:end - start]
        pos += SYLLABLE_SECONDS * rng.uniform(0.8, 1.2)
    out += 0.25 * hiss * hiss_env / max(_rms(hiss * hiss_env), 1e-12) * _rms(out)
    return _normalize(out, SOURCE_RMS)


def _midi_hz(note: int) -> float:
    return 440.0 * 2.0 ** ((note - 69) / 12.0)


def _note(freq: float, seconds: float, rng, attack=0.02, release=0.15) -> np.ndarray:
    """Harmonic tone (sawtooth-ish) with an attack/release and 4.5 Hz tremolo."""
    n = int(seconds * SR)
    t = np.arange(n) / SR
    out = np.zeros(n, dtype=np.float64)
    harmonics = np.arange(1, min(int(MUSIC_MAX_HZ / freq), MUSIC_MAX_HARMONICS) + 1)
    for k in harmonics:
        out += np.sin(2.0 * np.pi * freq * k * t + rng.uniform(0.0, 2.0 * np.pi)) / k
    envelope = 1.0 + 0.1 * np.sin(2.0 * np.pi * 4.5 * t)
    a = min(int(attack * SR), n)
    r = min(int(release * SR), n)
    envelope[:a] *= np.linspace(0.0, 1.0, a)
    envelope[n - r:] *= np.linspace(1.0, 0.0, r)
    return out * envelope


def music_like(seconds: float, rng) -> np.ndarray:
    """
    Synthetic music: sustained four-part chords (I-V-vi-IV) with a melody on
    top, a kick on each beat and a hi-hat between, at 120 bpm.

    Tonal and rhythmic with no speech structure — the thing Poise is meant to
    suppress.
    """
    n = int(seconds * SR)
    out = np.zeros(n, dtype=np.float64)
    beat = 60.0 / 120.0
    chord_index = 0
    pos = 0.0
    while pos < seconds:
        chord = CHORDS[chord_index % len(CHORDS)]
        start = int(pos * SR)
        length = int(CHORD_SECONDS * SR)
        for note in chord:
            tone = _note(_midi_hz(note), CHORD_SECONDS, rng, attack=0.05,
                         release=0.3)
            end = min(start + length, n)
            out[start:end] += tone[:end - start]
        # Melody: one note per chord half.
        melody = MELODY[chord_index % len(MELODY)]
        for half in range(2):
            note_start = start + half * length // 2
            tone = _note(_midi_hz(melody + (0 if half == 0 else 2)),
                         CHORD_SECONDS / 2, rng)
            end = min(note_start + tone.shape[0], n)
            out[note_start:end] += tone[:end - note_start]
        chord_index += 1
        pos += CHORD_SECONDS

    # Kick: 55 Hz sine with a decaying pitch sweep, on every beat.
    pos = 0.0
    while pos < seconds:
        length = int(0.12 * SR)
        t = np.arange(length) / SR
        sweep = 55.0 + 90.0 * np.exp(-t / 0.02)
        kick = np.sin(2.0 * np.pi * np.cumsum(sweep) / SR) * np.exp(-t / 0.05)
        start = int(pos * SR)
        end = min(start + length, n)
        out[start:end] += 0.8 * kick[:end - start]
        pos += beat

    # Hi-hat: differentiated noise with a fast decay, on the off-beats.
    pos = beat / 2.0
    while pos < seconds:
        length = int(0.05 * SR)
        hat = np.diff(rng.standard_normal(length + 1)) * np.exp(
            -np.arange(length) / (0.01 * SR))
        start = int(pos * SR)
        end = min(start + length, n)
        out[start:end] += 0.25 * hat[:end - start] / max(_rms(hat), 1e-12) * 0.05
        pos += beat
    return _normalize(out, SOURCE_RMS)


def _gate(seconds: float, kind: str, pattern: Tuple[str, ...]) -> np.ndarray:
    """1 in the segments `kind` plays in, 0 elsewhere, raised-cosine edges."""
    n = int(seconds * SR)
    gate = np.zeros(n, dtype=np.float64)
    ramp = max(int(GATE_RAMP_SECONDS * SR), 1)
    segment = int(SEGMENT_SECONDS * SR)
    for index in range((n + segment - 1) // segment):
        if pattern[index % len(pattern)] not in SOURCE_SEGMENTS[kind]:
            continue
        start = index * segment
        end = min(start + segment, n)
        gate[start:end] = 1.0
        edge = min(ramp, (end - start) // 2)
        if edge > 0:
            gate[start:start + edge] = np.linspace(0.0, 1.0, edge)
            gate[end - edge:end] = np.linspace(1.0, 0.0, edge)
    return gate


def build_mixture(seconds: float, seed: int = 20261102):
    """
    The test signal: speech and music, each gated on/off per PATTERN.

    Returns (mixture, segments) where segments is a list of
    (kind, start_sample, end_sample) for the whole seconds of the pattern.
    """
    rng = np.random.default_rng(seed)
    speech = speech_like(seconds, rng)
    music = music_like(seconds, rng)
    mixture = (speech * _gate(seconds, "speech", PATTERN)
               + music * _gate(seconds, "music", PATTERN))

    segment = int(SEGMENT_SECONDS * SR)
    segments = []
    for index in range((int(seconds * SR) + segment - 1) // segment):
        start = index * segment
        segments.append((PATTERN[index % len(PATTERN)], start,
                         min(start + segment, int(seconds * SR))))
    mixture = np.concatenate(
        (mixture, np.zeros(int(TAIL_SECONDS * SR)))).astype(np.float32)
    return mixture, segments


# --------------------------------------------------------------- measuring ---
def host_info() -> Dict[str, str]:
    try:
        chip = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        chip = platform.processor() or platform.machine()
    import onnxruntime
    return {
        "chip": chip,
        "machine": platform.machine(),
        "macos": platform.mac_ver()[0] or platform.platform(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "onnxruntime": onnxruntime.__version__,
        "onnx_intra_op_threads": str(ONNX_INTRA_OP_THREADS),
        "onnx_inter_op_threads": str(ONNX_INTER_OP_THREADS),
    }


def _drive(engine, signal: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Run `signal` through the engine's own framing; time every frame."""
    n = int(engine.required_frame_size)
    count = signal.shape[0] // n
    frames = [np.ascontiguousarray(signal[i * n:(i + 1) * n], dtype=np.float32)
              for i in range(count)]
    out = np.empty(count * n, dtype=np.float32)
    ms = np.empty(count, dtype=np.float64)
    for i, frame in enumerate(frames):
        start = time.perf_counter_ns()
        out[i * n:(i + 1) * n] = engine.process_frame(frame)
        ms[i] = (time.perf_counter_ns() - start) / 1e6
    return out, ms


def _segment_deltas(out: np.ndarray, mixture: np.ndarray, segments,
                    latency: int) -> Dict[str, List[float]]:
    """Per-segment energy change in dB, output read `latency` samples late."""
    deltas: Dict[str, List[float]] = {}
    for kind, start, end in segments:
        length = end - start
        margin = int(length * (1.0 - ANALYSIS_FRACTION) / 2.0)
        w0, w1 = start + margin, end - margin
        power_in = float(np.mean(mixture[w0:w1].astype(np.float64) ** 2))
        power_out = float(np.mean(out[w0 + latency:w1 + latency]
                                  .astype(np.float64) ** 2))
        delta = 10.0 * np.log10(max(power_out, 1e-20) / max(power_in, 1e-20))
        deltas.setdefault(kind, []).append(float(delta))
    return deltas


def measure_engine(name: str, mixture: np.ndarray, segments,
                   warmup_seconds: float) -> Dict:
    result: Dict = {"model": name}
    started = time.perf_counter()
    try:
        engine = create_engine(name)
    except Exception:
        result["error"] = traceback.format_exc()
        return result
    result["load_s"] = round(time.perf_counter() - started, 3)

    frame_size = int(engine.required_frame_size)
    latency = int(engine.latency_samples)
    result["frame_size"] = frame_size
    result["frame_ms"] = round(frame_size / SR * 1000.0, 3)
    result["latency_samples"] = latency
    result["latency_ms"] = round(latency / SR * 1000.0, 2)
    result["atten_lim_db"] = engine.atten_lim_db

    warmup_frames = int(warmup_seconds * SR / frame_size)
    try:
        # Warm-up on the same engine instance, discarded: page-in, ONNX
        # Runtime's arena growth, the CPU's boost clock, and the first second
        # a model needs before its streaming state is meaningful. The measured
        # pass carries that state on, so it is a steady state, as a running
        # session is -- a cold start at t=0 is not part of these numbers.
        engine.reset()
        _drive(engine, mixture[:warmup_frames * frame_size])
        out, ms = _drive(engine, mixture)
    except Exception:
        result["error"] = traceback.format_exc()
        return result
    finally:
        engine.close()

    frame_ms = frame_size / SR * 1000.0
    result["frames"] = int(ms.shape[0])
    result["audio_s"] = round(ms.shape[0] * frame_ms / 1000.0, 2)
    result["frame_ms_mean"] = round(float(ms.mean()), 3)
    result["frame_ms_p95"] = round(float(np.percentile(ms, 95)), 3)
    result["frame_ms_max"] = round(float(ms.max()), 3)
    result["rtf_mean"] = round(float(ms.sum() / (ms.shape[0] * frame_ms)), 4)
    result["rtf_p95"] = round(float(np.percentile(ms, 95) / frame_ms), 4)
    result["isolation_db"] = {
        kind: {
            "n": len(values),
            "mean": round(float(np.mean(values)), 2),
            "min": round(float(np.min(values)), 2),
            "max": round(float(np.max(values)), 2),
        }
        for kind, values in _segment_deltas(out, mixture, segments, latency).items()
    }
    return result


def _print_result(result: Dict) -> None:
    print(f"\n== {result['model']} ==")
    if "error" in result:
        print(result["error"])
        return
    print(f"load {result['load_s']} s; frame {result['frame_size']} samples "
          f"({result['frame_ms']} ms); latency {result['latency_samples']} "
          f"samples ({result['latency_ms']} ms); "
          f"atten_lim_db {result['atten_lim_db']}")
    print(f"measured {result['audio_s']} s of audio "
          f"({result['frames']} frames) after a warm-up")
    print(f"per-frame ms: mean {result['frame_ms_mean']}  "
          f"p95 {result['frame_ms_p95']}  max {result['frame_ms_max']}")
    print(f"RTF: mean {result['rtf_mean']}  p95 {result['rtf_p95']}")
    print("energy change, output vs input (dB):")
    for kind, stats in result["isolation_db"].items():
        print(f"  {kind:<8} {stats['mean']:+.2f} dB  "
              f"(n={stats['n']}, {stats['min']:+.2f}..{stats['max']:+.2f})")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Load, run and measure the two ONNX engines on this host.")
    parser.add_argument("--seconds", type=float, default=30.0,
                        help="audio measured per engine (default 30)")
    parser.add_argument("--warmup-seconds", type=float, default=2.0,
                        help="audio run and discarded before measuring (default 2)")
    parser.add_argument("--seed", type=int, default=20261102,
                        help="seed for the synthesized signals (default 20261102)")
    args = parser.parse_args(argv)
    if args.seconds <= 0.0 or args.warmup_seconds < 0.0:
        parser.error("--seconds must be > 0 and --warmup-seconds >= 0")

    host = host_info()
    mixture, segments = build_mixture(args.seconds, args.seed)
    results = [measure_engine(name, mixture, segments, args.warmup_seconds)
               for name in (MODEL_DEEPFILTERNET3, MODEL_GTCRN)]

    print("host: " + ", ".join(f"{key} {value}" for key, value in host.items()))
    print(f"signal: {args.seconds} s, seed {args.seed}, "
          f"segments {SEGMENT_SECONDS} s of {PATTERN}")
    for result in results:
        _print_result(result)
    return 1 if any("error" in result for result in results) else 0


if __name__ == "__main__":
    sys.exit(main())
