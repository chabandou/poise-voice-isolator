"""Time alignment: engine dry mix and AAD bypass vs the model's own delay.

Every path to the output (processed, dry-mixed, AAD-bypassed) must be
delayed by engine.latency_samples, or mixing combs and each bypass<->active
switch jumps the audio by the model delay (repeated/skipped audio, A/V
offset that changes between silent and active stretches).
"""
import numpy as np
import pytest

from stream_denoiser.constants import (
    MODEL_DEEPFILTERNET3, MODEL_GTCRN, MODEL_RNNOISE,
)
from stream_denoiser.engines import create_engine, RNNoiseEngine
from stream_denoiser.engines.base import DelayLine, DenoiseEngine
from stream_denoiser.processor import DenoiserAudioProcessor

FRAME = 512
SR = 48000


def _lag(x, y, max_lag):
    """Delay (0..max_lag samples) at which `y` best matches `x`."""
    n = len(x) + len(y)
    c = np.fft.irfft(np.fft.rfft(y, n) * np.conj(np.fft.rfft(x, n)), n)
    return int(np.argmax(np.abs(c[:max_lag + 1])))


def _runs(flags):
    """[(start, stop)] of consecutive True entries."""
    runs, start = [], None
    for i, f in enumerate(list(flags) + [False]):
        if f and start is None:
            start = i
        elif not f and start is not None:
            runs.append((start, i))
            start = None
    return runs


# -- DelayLine -------------------------------------------------------------------
def test_delay_line_delays_exactly_for_any_frame_lengths():
    rng = np.random.default_rng(0)
    x = rng.standard_normal(9000).astype(np.float32)
    line = DelayLine(1536)
    sizes = [1, 7, 300, 512, 2000, 1536, 3, 512]
    out, pos = [], 0
    while pos < len(x):
        n = min(sizes[len(out) % len(sizes)], len(x) - pos)
        out.append(line.process(x[pos:pos + n]))
        pos += n
    expected = np.concatenate([np.zeros(1536, np.float32), x])[:len(x)]
    np.testing.assert_array_equal(np.concatenate(out), expected)


def test_delay_line_zero_delay_passes_through_as_a_copy():
    line = DelayLine(0)
    x = np.arange(5, dtype=np.float32)
    y = line.process(x)
    np.testing.assert_array_equal(y, x)
    y[:] = -1.0
    np.testing.assert_array_equal(x, np.arange(5))


def test_delay_line_output_does_not_alias_its_history():
    line = DelayLine(4, history=8)
    first = line.process(np.ones(6, dtype=np.float32))
    first[:] = 99.0                       # caller mutates in place
    np.testing.assert_array_equal(line.recent(6), np.ones(6))
    np.testing.assert_array_equal(line.process(np.zeros(6, np.float32)),
                                  [1, 1, 1, 1, 0, 0])


def test_delay_line_recent_and_reset():
    line = DelayLine(3, history=2)
    np.testing.assert_array_equal(line.recent(5), np.zeros(5))
    line.process(np.array([1, 2, 3, 4], dtype=np.float32))
    np.testing.assert_array_equal(line.recent(5), [0, 1, 2, 3, 4])
    np.testing.assert_array_equal(line.recent(2), [3, 4])
    with pytest.raises(ValueError):
        line.recent(6)
    line.reset()
    np.testing.assert_array_equal(line.recent(5), np.zeros(5))


# -- AAD bypass with a pure-delay engine -----------------------------------------
class _DelayEngine(DenoiseEngine):
    """A "model" that outputs `gain` * its input, latency_samples late.

    Stateful like a real model: its pipeline only moves when it is called,
    so frames it skips never show up in its output.
    """

    name = "delay"

    def __init__(self, latency_frames=3, gain=1.0):
        self.required_frame_size = FRAME
        self.latency_samples = latency_frames * FRAME
        self.gain = gain
        self.fed = []                                     # every input frame
        self._line = DelayLine(self.latency_samples)

    def process_frame(self, frame):
        self.fed.append(np.array(frame, dtype=np.float32))
        return (self.gain * self._line.process(frame)).astype(np.float32)

    def reset(self):
        self._line.reset()


def _noise_bursts(pattern, seed=0):
    """White noise in stretches of (frames, rms)."""
    rng = np.random.default_rng(seed)
    return np.concatenate([
        (rng.standard_normal(frames * FRAME) * rms).astype(np.float32)
        for frames, rms in pattern])


# Loud (-20 dB) stretches with quiet (-60 dB) gaps longer than the AAD
# hang time (28 frames at 512), so the processor bypasses and resumes.
_PATTERN = [(40, 0.1), (70, 0.001), (30, 0.1), (60, 0.001), (40, 0.1)]


def _run(proc, x):
    """Process `x` frame by frame; return output and per-frame bypass flags."""
    out, bypassed = [], []
    for i in range(len(x) // FRAME):
        out.append(proc.process_chunk(x[i * FRAME:(i + 1) * FRAME].copy()).copy())
        bypassed.append(bool(proc.aad and proc.aad.bypass_active))
    return np.concatenate(out), bypassed


def test_bypass_output_matches_fully_processed_output():
    """With an identity model, AAD on must give exactly the AAD-off stream:
    bypassed frames are as late as processed ones, and resuming re-primes
    the engine instead of replaying what it held from before the bypass."""
    x = _noise_bursts(_PATTERN)
    aad_proc = DenoiserAudioProcessor(_DelayEngine(), frame_size=FRAME,
                                      enable_aad=True)
    ref_proc = DenoiserAudioProcessor(_DelayEngine(), frame_size=FRAME,
                                      enable_aad=False)
    out, bypassed = _run(aad_proc, x)
    ref, _ = _run(ref_proc, x)

    assert len(_runs(bypassed)) == 2                       # two bypass stretches
    assert aad_proc.get_stats()["aad_bypassed"] > 50
    np.testing.assert_allclose(out, ref, rtol=0, atol=1e-6)


def test_bypassed_and_processed_stretches_have_the_same_lag():
    engine = _DelayEngine(gain=0.5)                       # wet != dry
    proc = DenoiserAudioProcessor(engine, frame_size=FRAME, enable_aad=True)
    x = _noise_bursts(_PATTERN, seed=1)
    out, bypassed = _run(proc, x)
    L, lf = engine.latency_samples, engine.latency_samples // FRAME

    bypass_runs = _runs(bypassed)
    active_runs = _runs([not b for b in bypassed])
    assert bypass_runs and len(active_runs) >= 2
    for start, stop in bypass_runs + active_runs:
        # Output frames start+1 .. stop-1 are steady (no fade); they
        # carry input frames lf earlier.
        a, b = (start + 1 - lf) * FRAME, (stop - lf) * FRAME
        if a < 0:
            a = 0
        lag = _lag(x[a:b], out[a:b + 2 * L], 2 * L)
        assert lag == L, (start, stop, lag)


def _smooth_sine(pattern, freq=1234.5):
    """A sine whose amplitude moves between (frames, peak) stretches with
    raised-cosine ramps, so the input itself has no steps."""
    env = np.concatenate([np.full(frames * FRAME, peak) for frames, peak in pattern])
    ramp = 4 * FRAME
    kernel = np.hanning(ramp)
    env = np.convolve(np.pad(env, ramp // 2, mode="edge"),
                      kernel / kernel.sum(), mode="same")[ramp // 2:-ramp // 2]
    t = np.arange(len(env)) / SR
    return (env * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_bypass_transitions_are_click_free():
    """A polarity-flipping "model" is the worst case for a hard wet<->dry
    switch (the waveform jumps by twice its value); the per-frame
    crossfade must keep both transitions as smooth as the signal."""
    proc = DenoiserAudioProcessor(_DelayEngine(gain=-1.0), frame_size=FRAME,
                                  enable_aad=True)
    x = _smooth_sine([(40, 0.3), (70, 0.002), (40, 0.3)])
    out, bypassed = _run(proc, x)

    (b_start, b_stop), = _runs(bypassed)
    step = np.abs(np.diff(out))
    # The quiet sine's own sample-to-sample movement, measured mid-bypass
    natural = step[(b_start + 5) * FRAME:(b_stop - 5) * FRAME].max()
    # Fade-out frame b_start, fade-in frame b_stop (both over quiet input,
    # which the onset reaches only lf frames later), with their edges.
    for k in (b_start, b_stop):
        around = step[(k - 2) * FRAME:(k + 1) * FRAME + 1]
        assert around.max() < 2.0 * natural, (k, around.max() / natural)


def test_resume_reprimes_engine_with_the_skipped_input():
    engine = _DelayEngine()
    proc = DenoiserAudioProcessor(engine, frame_size=FRAME, enable_aad=True)
    prime = proc._prime_frames
    assert prime == 3 + 1                                 # lookahead + overlap
    x = _noise_bursts(_PATTERN)
    resumes, was_bypassed = 0, False
    for k in range(len(x) // FRAME):
        proc.process_chunk(x[k * FRAME:(k + 1) * FRAME].copy())
        if was_bypassed and not proc.aad.bypass_active:
            # The engine's inputs up to the resumed frame k are the real,
            # contiguous input, not a jump from before the bypass.
            resumes += 1
            np.testing.assert_array_equal(
                np.concatenate(engine.fed[-(prime + 1):]),
                x[(k - prime) * FRAME:(k + 1) * FRAME])
        was_bypassed = proc.aad.bypass_active
    assert resumes == 2


def test_short_bypass_keeps_the_engine_input_contiguous():
    """A bypass shorter than the prime window re-feeds exactly the frames
    the engine skipped: it sees the whole input once, in order."""
    engine = _DelayEngine()
    proc = DenoiserAudioProcessor(engine, frame_size=FRAME, enable_aad=True)
    hang = proc.aad.hang_frames
    # Quiet just long enough for a 2-frame bypass, then loud again
    x = _noise_bursts([(10, 0.1), (hang + 1, 0.001), (10, 0.1)])
    _, bypassed = _run(proc, x)

    assert sum(bypassed) == 2
    np.testing.assert_array_equal(np.concatenate(engine.fed), x)


def test_reset_restarts_alignment_state():
    x = _noise_bursts(_PATTERN[:3])
    proc = DenoiserAudioProcessor(_DelayEngine(gain=0.5), frame_size=FRAME,
                                  enable_aad=True)
    first, _ = _run(proc, x)
    proc.reset()
    again, _ = _run(proc, x)
    np.testing.assert_array_equal(first, again)


def test_zero_latency_engine_bypass_is_undelayed():
    engine = _DelayEngine(latency_frames=0)
    proc = DenoiserAudioProcessor(engine, frame_size=FRAME, enable_aad=True)
    quiet = np.full(FRAME, 0.0005, dtype=np.float32)
    quiet[::2] *= -1
    out = proc.process_chunk(quiet.copy())
    assert engine.fed == []                               # bypassed
    np.testing.assert_allclose(out, quiet * proc.output_gain, atol=1e-7)


# -- real engines ----------------------------------------------------------------
def _make(name, atten_lim_db):
    if name == MODEL_RNNOISE and not RNNoiseEngine.is_available():
        pytest.skip("librnnoise not available")
    try:
        return create_engine(name, atten_lim_db=atten_lim_db)
    except FileNotFoundError as e:
        pytest.skip(f"{name} model files not found: {e}")


def _process(engine, x):
    n = engine.required_frame_size
    return np.concatenate([engine.process_frame(x[i * n:(i + 1) * n].copy()).copy()
                           for i in range(len(x) // n)])


@pytest.mark.parametrize("name", [MODEL_DEEPFILTERNET3, MODEL_GTCRN,
                                  MODEL_RNNOISE])
def test_engine_dry_mix_lags_by_latency_samples(name):
    """out = f*dry + (1-f)*wet; the model ignores the mix, so the dry path
    can be recovered exactly and must be the input, latency_samples late."""
    wet_engine, mix_engine = _make(name, None), _make(name, -6.0)
    try:
        n, L = mix_engine.required_frame_size, mix_engine.latency_samples
        assert L > 0
        rng = np.random.default_rng(3)
        x = (rng.standard_normal(30 * n) * 0.1).astype(np.float32)
        wet, mixed = _process(wet_engine, x), _process(mix_engine, x)
        f = 10.0 ** (-6.0 / 20.0)
        dry_path = (mixed - (1.0 - f) * wet) / f

        assert _lag(x, dry_path, 4 * n) == L
        np.testing.assert_allclose(
            dry_path, np.concatenate([np.zeros(L, np.float32), x])[:len(x)],
            rtol=0, atol=1e-4)
    finally:
        wet_engine.close()
        mix_engine.close()


def _vowels(seconds=3.0, seed=0):
    """Speech-like test signal: a glottal pulse train with vibrato through
    three formant resonators, in 4 Hz syllables (the models keep it)."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * SR)) / SR
    f0 = 140 + 25 * np.sin(2 * np.pi * 3.1 * t) + 10 * np.sin(2 * np.pi * 0.7 * t)
    phase = np.cumsum(f0 / SR)
    y = (np.diff(np.floor(phase), prepend=0) > 0).astype(float)
    y += 0.02 * rng.standard_normal(len(t))
    # 2-pole resonators, applied in the frequency domain (numpy only)
    spec = np.fft.rfft(y)
    z = np.exp(-1j * np.pi * np.fft.rfftfreq(len(y), 1.0 / SR) * 2 / SR)
    for fc, bw in ((700, 90), (1200, 110), (2600, 160)):
        r, th = np.exp(-np.pi * bw / SR), 2 * np.pi * fc / SR
        spec *= (1 - r) / (1 - 2 * r * np.cos(th) * z + r * r * z * z)
    y = np.fft.irfft(spec, len(y))
    y *= 0.5 * (1 - np.cos(2 * np.pi * 4.0 * t))
    return (0.3 * y / np.max(np.abs(y))).astype(np.float32)


@pytest.mark.parametrize("name", [MODEL_DEEPFILTERNET3, MODEL_GTCRN,
                                  MODEL_RNNOISE])
def test_latency_samples_matches_the_models_wet_lag(name):
    """Guards the measured constants: re-measure if a model changes."""
    engine = _make(name, None)
    try:
        x = _vowels()
        wet = _process(engine, x)
        x = x[:len(wet)]
        L = engine.latency_samples
        assert _lag(x, wet, 4 * engine.required_frame_size) == L
        a, b = x[:len(x) - L], wet[L:]
        corr = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))
        assert corr > 0.8
    finally:
        engine.close()
