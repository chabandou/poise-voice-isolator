"""Tests for the fixed output makeup gain (no system changes)."""
import numpy as np
import pytest

from stream_denoiser.processor import DenoiserAudioProcessor
from stream_denoiser.engines.base import DenoiseEngine
from stream_denoiser.constants import OUTPUT_GAIN_DB


class _PassthroughEngine(DenoiseEngine):
    name = "fake"
    required_frame_size = 480

    def __init__(self):
        self.speech_prob = None

    def process_frame(self, frame):
        return frame

    def reset(self):
        pass

    def close(self):
        pass


def _sine(peak, freq=440.0, n=480, sr=48000):
    return (peak * np.sin(2 * np.pi * freq * np.arange(n) / sr)).astype(np.float32)


def test_gain_is_plus_6db_by_default():
    assert OUTPUT_GAIN_DB == 6.0
    proc = DenoiserAudioProcessor(_PassthroughEngine(), frame_size=480, enable_aad=False)
    assert proc.output_gain == pytest.approx(10.0 ** (6.0 / 20.0))
    out = proc.process_chunk(_sine(0.25))
    # 0.25 * ~2, modulo DC-removal recentering on a non-integer cycle count.
    assert abs(out).max() == pytest.approx(0.5, abs=0.05)


def test_hot_signal_never_clips():
    proc = DenoiserAudioProcessor(_PassthroughEngine(), frame_size=480, enable_aad=False)
    for peak in (0.5, 0.9, 1.0):
        out = proc.process_chunk(_sine(peak))
        assert (out <= 1.0).all() and (out >= -1.0).all()
        assert np.isfinite(out).all()


def test_bypass_path_gets_same_gain():
    proc = DenoiserAudioProcessor(
        _PassthroughEngine(), frame_size=480,
        enable_aad=True, aad_threshold_db=-40.0,
    )
    # 0.005 peak sine ~= -49 dB RMS, below the -40 dB threshold -> bypass.
    quiet = _sine(0.005)
    out = proc.process_chunk(quiet.copy())
    assert proc.frame_count == 0  # engine never ran: this was a bypass
    assert abs(out).max() == pytest.approx(0.005 * proc.output_gain, abs=0.002)
    assert (out <= 1.0).all() and (out >= -1.0).all()
