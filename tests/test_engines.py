"""Tests for denoising engines (DeepFilterNet3 + RNNoise; GTCRN in
test_gtcrn.py)."""
import numpy as np
import pytest

from stream_denoiser.constants import (
    DEFAULT_FRAME_SIZE,
    DEFAULT_MODEL,
    MODEL_DEEPFILTERNET3,
    MODEL_GTCRN,
    MODEL_RNNOISE,
)
from stream_denoiser.engines import (
    create_engine,
    available_models,
    DeepFilterNet3Engine,
    RNNoiseEngine,
)
from stream_denoiser.processor import DenoiserAudioProcessor


def test_factory_unknown_model_raises():
    with pytest.raises(ValueError):
        create_engine("not-a-model")


def test_factory_rnnoise_type_or_skip():
    if not RNNoiseEngine.is_available():
        pytest.skip("librnnoise not available")
    engine = create_engine(MODEL_RNNOISE)
    try:
        assert isinstance(engine, RNNoiseEngine)
        assert engine.name == MODEL_RNNOISE
        assert engine.required_frame_size == DEFAULT_FRAME_SIZE
    finally:
        engine.close()


def test_available_models_lists_deepfilternet3():
    assert MODEL_DEEPFILTERNET3 in available_models()


def test_default_model_is_deepfilternet3():
    assert DEFAULT_MODEL == MODEL_DEEPFILTERNET3
    # create_engine() with no name follows the default
    try:
        engine = create_engine()
    except FileNotFoundError as e:
        pytest.skip(f"deepfilternet3 model files not found: {e}")
    try:
        assert isinstance(engine, DeepFilterNet3Engine)
    finally:
        engine.close()


def _make_df3_engine():
    try:
        return create_engine(MODEL_DEEPFILTERNET3)
    except FileNotFoundError as e:
        pytest.skip(f"deepfilternet3 model files not found: {e}")


def test_factory_deepfilternet3_type():
    engine = _make_df3_engine()
    try:
        assert isinstance(engine, DeepFilterNet3Engine)
        assert engine.name == MODEL_DEEPFILTERNET3
        assert engine.required_frame_size == 512
    finally:
        engine.close()


def test_deepfilternet3_output_shape_finite_range():
    engine = _make_df3_engine()
    try:
        n = engine.required_frame_size
        rng = np.random.default_rng(0)
        frame = (rng.standard_normal(n) * 0.1).astype(np.float32)
        out = engine.process_frame(frame)
        assert out.shape == (n,)
        assert out.dtype == np.float32
        assert np.all(np.isfinite(out))
    finally:
        engine.close()


def test_deepfilternet3_silence_stays_silent():
    engine = _make_df3_engine()
    try:
        n = engine.required_frame_size
        out = engine.process_frame(np.zeros(n, dtype=np.float32))
        assert float(np.max(np.abs(out))) < 1e-3
    finally:
        engine.close()


def test_deepfilternet3_reset_is_deterministic():
    engine = _make_df3_engine()
    try:
        n = engine.required_frame_size
        rng = np.random.default_rng(42)
        frame = (rng.standard_normal(n) * 0.2).astype(np.float32)
        first = engine.process_frame(frame.copy()).copy()
        engine.reset()
        second = engine.process_frame(frame.copy()).copy()
        np.testing.assert_allclose(first, second, rtol=1e-5, atol=1e-6)
    finally:
        engine.close()


# -- DF3 behaviour ---------------------------------------------------------------
SR = 48000


def _process(engine, x):
    n = engine.required_frame_size
    return np.concatenate([engine.process_frame(x[i:i + n].copy()).copy()
                           for i in range(0, len(x) // n * n, n)])


def _rms(x):
    return float(np.sqrt(np.mean(np.asarray(x, np.float64) ** 2)))


def _voice(seconds):
    """Voice-like test signal: a gliding 140 Hz harmonic tone in syllables."""
    t = np.arange(int(seconds * SR)) / SR
    phase = 2 * np.pi * np.cumsum(140 + 30 * np.sin(2 * np.pi * 0.6 * t)) / SR
    tone = sum(np.sin(k * phase) / k for k in range(1, 30))
    syllables = np.clip(np.sin(2 * np.pi * 3.0 * t), 0, None) ** 0.5
    return (0.1 * tone * syllables).astype(np.float32)


def test_deepfilternet3_removes_white_noise():
    engine = _make_df3_engine_at(None)
    try:
        noise = (np.random.default_rng(1).standard_normal(2 * SR) * 0.05).astype(np.float32)
        out = _process(engine, noise)
        assert 20 * np.log10(_rms(out[SR:]) / _rms(noise)) < -30.0     # ~-41 dB
    finally:
        engine.close()


def test_deepfilternet3_keeps_voice_and_lifts_its_snr():
    """Clean voice passes nearly unchanged (~-0.5 dB); in noise at 4.5 dB
    SNR the output's SNR is ~17 dB."""
    v = _voice(3.0)
    clean, noisy = _make_df3_engine_at(None), _make_df3_engine_at(None)
    try:
        L = clean.latency_samples
        kept = _process(clean, v)
        ref = v[SR:len(kept) - L]                                  # past the warm-up, delay-aligned
        kept = kept[SR + L:]
        assert abs(20 * np.log10(_rms(kept) / _rms(ref))) < 3.0

        noise = (np.random.default_rng(2).standard_normal(3 * SR) * 0.03).astype(np.float32)
        out = _process(noisy, v + noise)[SR + L:]
        speech = ref * (np.dot(out, ref) / np.dot(ref, ref))       # the part of the output that is the voice
        snr_in = 20 * np.log10(_rms(v) / _rms(noise))
        snr_out = 20 * np.log10(_rms(speech) / _rms(out - speech))
        assert snr_out > snr_in + 8.0
    finally:
        clean.close()
        noisy.close()


def test_deepfilternet3_stays_bounded_over_a_long_run():
    """30 s of voice in noise, loud noise and full-scale DC: the output and
    the recurrent state stay finite and in range."""
    engine = _make_df3_engine_at(None)
    try:
        rng = np.random.default_rng(4)
        x = np.concatenate([_voice(10.0) + (rng.standard_normal(10 * SR) * 0.05).astype(np.float32),
                            (rng.standard_normal(10 * SR) * 0.3).astype(np.float32),
                            np.full(10 * SR, 0.9, np.float32)])
        out = _process(engine, x)
        assert np.all(np.isfinite(out))
        assert float(np.max(np.abs(out))) < 1.5
        for name in ("enc_hidden", "erb_dec_hidden", "df_dec_hidden"):
            assert np.all(np.isfinite(engine._states[name]))
            assert float(np.max(np.abs(engine._states[name]))) <= 1.0 + 1e-6
    finally:
        engine.close()


@pytest.mark.parametrize("file_name, tool, source_sha256", [
    ("denoiser_model_df3.onnx", "tools/optimize_df3.py",
     "b758c49d6708a5b7979e3de185705a8a4915076c862fb17b1b304d9a72b75cdc"),
    ("gtcrn.onnx", "tools/optimize_gtcrn.py",
     "f648b02f2d7ff96ebcb0eec2219688a08ed12fe7e3d50f248605a90eba8cad17"),
])
def test_vendored_models_are_their_build_scripts_output(file_name, tool, source_sha256):
    """The vendored models are rebuilt from upstream files by tools/ scripts,
    which stamp what they built from: a model swapped in by hand fails here."""
    import onnxruntime
    from stream_denoiser.engines.onnx_model import find_model_file

    try:
        path = find_model_file(file_name, file_name)
    except FileNotFoundError as e:
        pytest.skip(str(e))
    meta = onnxruntime.InferenceSession(path, providers=["CPUExecutionProvider"]).get_modelmeta()
    assert meta.producer_name == f"poise {tool}"
    assert meta.custom_metadata_map["source_sha256"] == source_sha256


def test_processor_uses_engine_frame_size_for_df3():
    engine = _make_df3_engine()
    try:
        proc = DenoiserAudioProcessor(
            engine,
            frame_size=engine.required_frame_size,
            enable_aad=False,
        )
        n = engine.required_frame_size
        rng = np.random.default_rng(0)
        frame = (rng.standard_normal(n) * 0.1).astype(np.float32)
        out = proc.process_chunk(frame)
        assert out is not None
        assert out.shape == (n,)
        assert proc.get_stats()["model"] == MODEL_DEEPFILTERNET3
        proc.close()
    finally:
        engine.close()


def _make_rnnoise_engine():
    if not RNNoiseEngine.is_available():
        pytest.skip("librnnoise not available")
    return RNNoiseEngine()


def test_rnnoise_output_shape_finite_range():
    engine = _make_rnnoise_engine()
    try:
        rng = np.random.default_rng(0)
        frame = (rng.standard_normal(DEFAULT_FRAME_SIZE) * 0.1).astype(np.float32)
        out = engine.process_frame(frame)
        assert out.shape == (DEFAULT_FRAME_SIZE,)
        assert out.dtype == np.float32
        assert np.all(np.isfinite(out))
        assert np.max(np.abs(out)) <= 1.0 + 1e-6
        assert engine.speech_prob is not None
        assert 0.0 <= float(engine.speech_prob) <= 1.0
    finally:
        engine.close()


def test_rnnoise_scaling_guard():
    """A 0.1-amplitude sine must not collapse to ~1/32768 (scaling bug)."""
    engine = _make_rnnoise_engine()
    try:
        t = np.arange(DEFAULT_FRAME_SIZE, dtype=np.float32) / 48000.0
        sine = (0.1 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
        # First frames are suppressed on cold state; let it settle.
        out = sine
        for _ in range(5):
            out = engine.process_frame(sine)
        rms = float(np.sqrt(np.mean(out.astype(np.float64) ** 2)))
        # If scaling were wrong, output would be ~3e-5 (missing x32768)
        # or clip at 1.0 (missing /32768). Settled sine RMS is ~0.07.
        assert rms > 1e-3, f"output collapsed, RMS={rms}"
        assert rms < 1.0, f"output exploded, RMS={rms}"
    finally:
        engine.close()


def test_rnnoise_reset_is_deterministic():
    engine = _make_rnnoise_engine()
    try:
        rng = np.random.default_rng(42)
        frame = (rng.standard_normal(DEFAULT_FRAME_SIZE) * 0.2).astype(np.float32)
        first = engine.process_frame(frame.copy()).copy()
        engine.reset()
        second = engine.process_frame(frame.copy()).copy()
        np.testing.assert_allclose(first, second, rtol=1e-5, atol=1e-6)
    finally:
        engine.close()


class _StubEngine:
    """Minimal stub satisfying the DenoiseEngine protocol (no ONNX needed)."""

    name = "stub"
    required_frame_size = DEFAULT_FRAME_SIZE
    speech_prob = None

    def process_frame(self, frame):
        return (frame * 0.5).astype(np.float32)

    def reset(self):
        pass

    def close(self):
        pass


def test_processor_works_with_stub_engine_without_onnx():
    from stream_denoiser.engines.base import DenoiseEngine

    assert isinstance(_StubEngine(), DenoiseEngine) is False  # stub is duck-typed
    # Processor requires DenoiseEngine instances; use a thin subclass instead.
    class StubEngine(DenoiseEngine):
        name = "stub"
        required_frame_size = DEFAULT_FRAME_SIZE

        def process_frame(self, frame):
            return (frame * 0.5).astype(np.float32)

        def reset(self):
            pass

    proc = DenoiserAudioProcessor(
        StubEngine(), enable_aad=False, atten_lim_db=-60.0
    )
    frame = np.ones(DEFAULT_FRAME_SIZE, dtype=np.float32) * 0.4
    out = proc.process_chunk(frame)
    assert out is not None
    assert out.shape == (DEFAULT_FRAME_SIZE,)
    stats = proc.get_stats()
    assert stats["frame_count"] == 1
    assert stats["model"] == "stub"
    proc.close()


# -- live attenuation changes ----------------------------------------------------
def test_mix_dry_ramps_to_the_new_mix():
    from stream_denoiser.engines.base import mix_dry

    wet = np.zeros(8, dtype=np.float32)
    dry = np.ones(8, dtype=np.float32)
    np.testing.assert_allclose(mix_dry(wet, dry, 0.25, 0.25), 0.25)
    ramp = mix_dry(wet, dry, 0.0, 0.8)
    assert np.all(np.diff(ramp) > 0)            # fades, no step
    assert ramp[0] == pytest.approx(0.1)        # first sample moves off start
    assert ramp[-1] == pytest.approx(0.8)       # last sample reaches end


@pytest.mark.parametrize("make", [
    lambda db: _make_rnnoise_engine_at(db),
    lambda db: _make_df3_engine_at(db),
    lambda db: _make_gtcrn_engine_at(db),
], ids=["rnnoise", "deepfilternet3", "gtcrn"])
def test_set_atten_lim_db_applies_live(make):
    """Changing the limit mid-stream ramps over one frame, then matches an
    engine built with that limit (model state ignores the dry mix)."""
    live, fresh = make(-50.0), make(-10.0)
    try:
        n = live.required_frame_size
        rng = np.random.default_rng(7)
        frames = [(rng.standard_normal(n) * 0.2).astype(np.float32)
                  for _ in range(3)]
        live.process_frame(frames[0].copy())
        fresh.process_frame(frames[0].copy())
        live.set_atten_lim_db(-10.0)
        assert live.atten_lim_db == -10.0
        ramped = live.process_frame(frames[1].copy()).copy()
        target = fresh.process_frame(frames[1].copy()).copy()
        assert not np.allclose(ramped, target, atol=1e-6)   # still ramping...
        assert ramped[-1] == pytest.approx(target[-1], abs=1e-5)  # ...lands
        np.testing.assert_allclose(live.process_frame(frames[2].copy()),
                                   fresh.process_frame(frames[2].copy()),
                                   rtol=1e-5, atol=1e-6)
    finally:
        live.close()
        fresh.close()


def _make_rnnoise_engine_at(db):
    if not RNNoiseEngine.is_available():
        pytest.skip("librnnoise not available")
    return RNNoiseEngine(atten_lim_db=db)


def _make_df3_engine_at(db):
    try:
        return create_engine(MODEL_DEEPFILTERNET3, atten_lim_db=db)
    except FileNotFoundError as e:
        pytest.skip(f"deepfilternet3 model files not found: {e}")


def _make_gtcrn_engine_at(db):
    try:
        return create_engine(MODEL_GTCRN, atten_lim_db=db)
    except FileNotFoundError as e:
        pytest.skip(f"gtcrn model file not found: {e}")
