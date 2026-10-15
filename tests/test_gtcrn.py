"""Tests for the GTCRN engine: 16 kHz model inside 48 kHz frames."""
import numpy as np
import pytest

from stream_denoiser.constants import ALL_MODELS, MODEL_GTCRN, MODEL_INFO
from stream_denoiser.engines import (
    GTCRNEngine,
    available_models,
    create_engine,
    model_unavailable_reason,
)
from stream_denoiser.engines.gtcrn import FRAME, lowpass_fir
from stream_denoiser.processor import DenoiserAudioProcessor

SR = 48000


def _make(atten_lim_db=-60.0):
    try:
        return create_engine(MODEL_GTCRN, atten_lim_db=atten_lim_db)
    except FileNotFoundError as e:
        pytest.skip(f"gtcrn model file not found: {e}")


class _IdentitySession:
    """Stands in for the model: enhanced spectrum = input spectrum, caches
    passed through. Isolates the engine's resampling + STFT plumbing."""

    def __init__(self, real):
        self._real = real

    def get_inputs(self):
        return self._real.get_inputs()

    def get_outputs(self):
        return self._real.get_outputs()

    def run(self, names, feeds):
        return [feeds[i.name].copy() for i in self._real.get_inputs()]


def _process(engine, x):
    n = engine.required_frame_size
    return np.concatenate([engine.process_frame(x[i:i + n].copy()).copy()
                           for i in range(0, len(x) // n * n, n)])


def _tones(seconds, *freqs):
    t = np.arange(int(seconds * SR)) / SR
    return sum(0.1 * np.sin(2 * np.pi * f * t + i)
               for i, f in enumerate(freqs)).astype(np.float32)


def _rms(x):
    return float(np.sqrt(np.mean(np.asarray(x, np.float64) ** 2)))


# -- registry --------------------------------------------------------------------
def test_gtcrn_is_registered_and_available():
    assert MODEL_GTCRN in ALL_MODELS
    assert MODEL_GTCRN in available_models()
    assert model_unavailable_reason(MODEL_GTCRN) is None


def test_every_model_has_display_info():
    """The TUI picker, GUI cards and stats panels all read MODEL_INFO."""
    for model in ALL_MODELS:
        info = MODEL_INFO[model]
        for key in ("label", "picker_blurb", "card_blurb", "blurb"):
            assert info.get(key), (model, key)


def test_factory_gtcrn_type_and_frame():
    engine = _make()
    try:
        assert isinstance(engine, GTCRNEngine)
        assert engine.name == MODEL_GTCRN
        assert engine.required_frame_size == FRAME == 768
        assert engine.latency_samples == 864          # 18 ms
        assert engine.speech_prob is None
    finally:
        engine.close()


# -- model -----------------------------------------------------------------------
def test_gtcrn_output_shape_finite():
    engine = _make()
    try:
        rng = np.random.default_rng(0)
        for _ in range(3):
            frame = (rng.standard_normal(FRAME) * 0.1).astype(np.float32)
            out = engine.process_frame(frame)
            assert out.shape == (FRAME,)
            assert out.dtype == np.float32
            assert np.all(np.isfinite(out))
    finally:
        engine.close()


def test_gtcrn_silence_stays_silent():
    engine = _make()
    try:
        for _ in range(5):
            out = engine.process_frame(np.zeros(FRAME, dtype=np.float32))
        assert float(np.max(np.abs(out))) < 1e-3
    finally:
        engine.close()


def test_gtcrn_rejects_wrong_frame_size():
    engine = _make()
    try:
        with pytest.raises(ValueError):
            engine.process_frame(np.zeros(512, dtype=np.float32))
    finally:
        engine.close()


def test_gtcrn_reset_is_deterministic():
    engine = _make()
    try:
        rng = np.random.default_rng(42)
        x = (rng.standard_normal(4 * FRAME) * 0.2).astype(np.float32)
        first = _process(engine, x)
        engine.reset()
        second = _process(engine, x)
        np.testing.assert_allclose(first, second, rtol=1e-5, atol=1e-6)
    finally:
        engine.close()


def test_gtcrn_removes_white_noise():
    """Stationary noise alone is what the model is trained to remove."""
    engine = _make(atten_lim_db=None)
    try:
        rng = np.random.default_rng(1)
        noise = (rng.standard_normal(SR * 2) * 0.05).astype(np.float32)
        out = _process(engine, noise)
        tail = out[SR:]                                  # past the warm-up
        assert 20 * np.log10(_rms(tail) / _rms(noise)) < -15.0
    finally:
        engine.close()


def test_processor_runs_gtcrn_frames():
    engine = _make()
    proc = DenoiserAudioProcessor(engine, frame_size=engine.required_frame_size,
                                  enable_aad=True)
    try:
        rng = np.random.default_rng(0)
        for _ in range(3):
            out = proc.process_chunk(
                (rng.standard_normal(FRAME) * 0.1).astype(np.float32))
            assert out is not None and out.shape == (FRAME,)
        assert proc.get_stats()["model"] == MODEL_GTCRN
    finally:
        proc.close()


# -- resampling + STFT plumbing (model replaced by identity) ---------------------
def _identity_engine():
    real = _make(atten_lim_db=None)
    return real, GTCRNEngine(_IdentitySession(real.onnx_session),
                             atten_lim_db=None)


def test_round_trip_is_a_pure_delay_in_band():
    """Down to 16 kHz, STFT, iSTFT, back up: in-band audio comes out
    unchanged, exactly latency_samples late."""
    real, engine = _identity_engine()
    try:
        x = _tones(1.0, 440.0, 3100.0, 6000.0)
        y = _process(engine, x)
        L = engine.latency_samples
        settled = slice(L + 2000, len(y))
        err = y[settled] - x[settled.start - L:len(y) - L]
        assert float(np.max(np.abs(err))) < 1e-3          # FIR ripple only
    finally:
        engine.close()
        real.close()


def test_round_trip_lag_matches_latency_samples():
    real, engine = _identity_engine()
    try:
        rng = np.random.default_rng(2)
        x = (rng.standard_normal(SR) * 0.1).astype(np.float32)
        y = _process(engine, x)
        n = len(x) + len(y)
        c = np.fft.irfft(np.fft.rfft(y, n) * np.conj(np.fft.rfft(x, n)), n)
        assert int(np.argmax(np.abs(c[:4 * FRAME]))) == engine.latency_samples
    finally:
        engine.close()
        real.close()


@pytest.mark.parametrize("freq", [9000.0, 12000.0, 20000.0])
def test_out_of_band_input_does_not_alias(freq):
    """Above the model's band, input must neither alias into it nor come
    back out (a plain take-every-3rd-sample decimator folds 12 kHz to
    4 kHz)."""
    real, engine = _identity_engine()
    try:
        x = _tones(0.5, freq) * 3.0
        y = _process(engine, x)[2 * FRAME:]
        assert 20 * np.log10(_rms(y) / _rms(x)) < -50.0
    finally:
        engine.close()
        real.close()


def test_lowpass_fir_response():
    h = lowpass_fir().astype(np.float64)
    assert len(h) % 2 == 1
    np.testing.assert_allclose(h, h[::-1])               # linear phase
    H = np.abs(np.fft.rfft(h, 48000))                    # 1 Hz bins at 48 kHz
    db = 20 * np.log10(H + 1e-12)
    assert abs(db[0]) < 1e-6                             # unity at DC
    assert np.max(np.abs(db[:6500])) < 0.05              # flat to 6.5 kHz
    assert db[7000] > -0.5
    assert np.max(db[8500:]) < -55.0                     # stopband
