"""Regression tests for the minutes-long A/V desync (resampler backlog/drift).

Root cause: the audio loops read a fixed `frame_size` block from the input
device every iteration, but when the input device runs at a different rate
than the 48kHz engine target (common on Linux: PulseAudio/PipeWire monitors
at 44100Hz), each read resamples to MORE than one engine frame. The surplus
accumulated without bound (~45 samples/frame -> ~14s of delay after 3min),
so the processed audio lagged further and further behind the video.

The fix scales the input read size (`processor.input_block_size`) so each
read yields ~one engine frame, routes VAD-bypassed frames through the
output resampler too, and caps resampler backlogs so latency stays bounded.
"""
import numpy as np

from stream_denoiser.processor import DenoiserAudioProcessor
from stream_denoiser.engines.base import DenoiseEngine
from stream_denoiser.resampler import StreamingResampler

TARGET_SR = 48000
FRAME = 480


class _FakeEngine(DenoiseEngine):
    name = "fake"
    required_frame_size = FRAME

    def __init__(self):
        self.speech_prob = None

    def process_frame(self, frame):
        return frame

    def reset(self):
        pass

    def close(self):
        pass


class _FakeEngine512(DenoiseEngine):
    """512-sample frames like the DeepFilterNet3 engine (470.4 @44100Hz)."""
    name = "fake512"
    required_frame_size = 512

    def __init__(self):
        self.speech_prob = None

    def process_frame(self, frame):
        return frame

    def reset(self):
        pass

    def close(self):
        pass


def _make_processor(input_sr, output_sr=TARGET_SR, enable_vad=False):
    proc = DenoiserAudioProcessor(_FakeEngine(), target_sr=TARGET_SR,
                                 frame_size=FRAME, enable_vad=enable_vad)
    proc.setup_resampler(input_sr)
    proc.setup_output_resampler(output_sr)
    return proc


def _sine_frame(n, freq=440.0, sr=TARGET_SR, amp=0.5):
    t = np.arange(n, dtype=np.float32) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_input_block_size_scales_with_input_rate():
    proc = _make_processor(44100)
    assert proc.resampler is not None
    assert proc.input_block_size == round(FRAME * 44100 / TARGET_SR) == 441

    proc_same = _make_processor(TARGET_SR)
    assert proc_same.resampler is None
    assert proc_same.input_block_size == FRAME


def test_scaled_reads_keep_backlog_bounded():
    """New backend behavior: rate-scaled reads -> no backlog growth."""
    proc = _make_processor(44100)
    assert proc.input_block_size == 441

    produced = 0
    for _ in range(120):
        out = proc.process_chunk(_sine_frame(proc.input_block_size,
                                             sr=proc.input_sr))
        if out is not None:
            produced += 1
            assert len(out) == FRAME

    assert produced >= 100  # ~one frame per read, no starvation
    assert proc.resampler.buffered_samples() < 2 * FRAME
    assert proc.resampler.dropped_samples == 0


def test_unscaled_reads_overflow_and_drop():
    """Old backend behavior (fixed frame_size reads at 44100Hz) over-feeds
    the resampler: the backlog hits the safety cap and samples are dropped
    instead of accumulating into a minutes-long delay."""
    proc = _make_processor(44100)
    for _ in range(120):
        proc.process_chunk(_sine_frame(FRAME, sr=proc.input_sr))

    assert proc.resampler.buffered_samples() <= 4 * FRAME
    assert proc.resampler.dropped_samples > 0


def test_resampler_cap_bounds_latency_directly():
    r = StreamingResampler(44100, TARGET_SR, channels=1)
    for _ in range(200):
        r.process(_sine_frame(FRAME, sr=44100), FRAME)
    assert r.buffered_samples() <= 4 * FRAME
    assert r.dropped_samples > 0


def test_vad_bypass_applies_output_resampling():
    """Silence (VAD bypass) frames must come out at the output device rate,
    otherwise bypassed frames have the wrong length/timing vs processed ones."""
    proc = _make_processor(TARGET_SR, output_sr=44100, enable_vad=True)
    # Threshold above any content of a silent frame -> always bypass.
    proc.vad.set_threshold(10.0)
    assert proc.output_resample_size == 441

    lengths = []
    for _ in range(10):
        out = proc.process_chunk(np.zeros(FRAME, dtype=np.float32))
        if out is not None:
            lengths.append(len(out))

    assert lengths, "output resampler starved: no frames produced"
    assert all(n == proc.output_resample_size for n in lengths)


def test_next_input_block_size_averages_exact():
    """Per-iteration reads must average the exact fractional size (470.4 for
    a 512-frame @44100Hz): fixed rounding starves one frame every ~100 reads
    (a periodic ~10ms output gap / sync wobble)."""
    from stream_denoiser.processor import DenoiserAudioProcessor
    proc = DenoiserAudioProcessor(_FakeEngine(), target_sr=TARGET_SR,
                                  frame_size=FRAME, enable_vad=False)
    # 44100Hz input with the default 480-frame: exact size is whole (441).
    proc.setup_resampler(44100)
    assert proc.input_block_size == 441
    assert all(proc.next_input_block_size() == 441 for _ in range(50))

    proc512 = DenoiserAudioProcessor(_FakeEngine512(), target_sr=TARGET_SR,
                                     frame_size=512, enable_vad=False)
    proc512.setup_resampler(44100)
    assert proc512.input_block_size == 470  # round(470.4)
    sizes = [proc512.next_input_block_size() for _ in range(1000)]
    assert set(sizes) <= {470, 471}
    assert abs(sum(sizes) / len(sizes) - 512 * 44100 / TARGET_SR) < 0.01

    # No resampling -> constant frame size, and reset() clears the dither.
    proc_same = _make_processor(TARGET_SR)
    assert all(proc_same.next_input_block_size() == FRAME for _ in range(10))


def test_next_output_block_size_averages_exact():
    """Output takes must average the exact fractional size too, otherwise
    the output backlog grows ~0.4 samples/frame until the safety cap drops
    (periodic output gaps / sync wobble on non-48kHz outputs)."""
    proc = _make_processor(44100, output_sr=44100)
    assert proc.output_resample_size == 441  # 480 * 44100/48000 is exactly 441
    assert all(proc.next_output_block_size() == 441 for _ in range(50))

    from stream_denoiser.processor import DenoiserAudioProcessor
    proc512 = DenoiserAudioProcessor(_FakeEngine512(), target_sr=TARGET_SR,
                                    frame_size=512, enable_vad=False)
    proc512.setup_resampler(TARGET_SR)
    proc512.setup_output_resampler(44100)
    assert proc512.output_resample_size == 470  # round(470.4)
    sizes = [proc512.next_output_block_size() for _ in range(1000)]
    assert set(sizes) <= {470, 471}
    assert abs(sum(sizes) / len(sizes) - 512 * 44100 / TARGET_SR) < 0.01
