"""Tests for denoising engines (DeepFilterNet3 + RNNoise)."""
import numpy as np
import pytest

from stream_denoiser.constants import (
    DEFAULT_FRAME_SIZE,
    DEFAULT_MODEL,
    MODEL_DEEPFILTERNET3,
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


def test_processor_uses_engine_frame_size_for_df3():
    engine = _make_df3_engine()
    try:
        proc = DenoiserAudioProcessor(
            engine,
            frame_size=engine.required_frame_size,
            enable_vad=False,
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
        StubEngine(), enable_vad=False, atten_lim_db=-60.0
    )
    frame = np.ones(DEFAULT_FRAME_SIZE, dtype=np.float32) * 0.4
    out = proc.process_chunk(frame)
    assert out is not None
    assert out.shape == (DEFAULT_FRAME_SIZE,)
    stats = proc.get_stats()
    assert stats["frame_count"] == 1
    assert stats["model"] == "stub"
    proc.close()
