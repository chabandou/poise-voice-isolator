"""
PulseAudio backend (Linux).

Single shared processing loop used by both the CLI
(:func:`process_with_pulse`) and the TUI, so the two paths cannot
diverge. I/O is via libpulse-simple at a fixed 48 kHz float32; the
server handles rate/format conversion, so no resampler is configured.
"""
import time
from typing import Callable, Dict, Optional, Tuple, Union

import numpy as np

from ..constants import PULSE_TARGET_SR, STATS_PRINT_INTERVAL_SEC
from ..device_utils import print_stats, print_final_stats
from ..logging_config import get_logger, get_log_file_path
from .pulse_simple import PulseCapture, PulsePlayback

_logger = get_logger(__name__)

# should_stop may be a threading.Event, a zero-arg callable, or None (run
# until KeyboardInterrupt).
StopLike = Union[object, Callable[[], bool], None]


def _should_stop(stop) -> bool:
    if stop is None:
        return False
    if callable(stop):
        try:
            return bool(stop())
        except Exception:
            return False
    is_set = getattr(stop, "is_set", None)
    if callable(is_set):
        try:
            return bool(is_set())
        except Exception:
            return False
    return False


def run_pulse_loop(processor,
                   source: str,
                   sink: str,
                   should_stop: StopLike = None,
                   on_stats: Optional[Callable[[dict, float], None]] = None,
                   stats_interval_sec: float = STATS_PRINT_INTERVAL_SEC
                   ) -> Tuple[dict, int]:
    """Run the capture -> process -> playback loop.

    Args:
        processor: Configured DenoiserAudioProcessor (engine already set).
        source: Pulse source name for capture (e.g. Poise_Capture.monitor).
        sink: Pulse sink name for playback (real hardware sink).
        should_stop: threading.Event, callable, or None.
        on_stats: Optional callback(stats, elapsed_sec) every interval.
        stats_interval_sec: Stats callback cadence.

    Returns:
        (final_stats, empty_reads). There is no overflow counter:
        pa_simple cannot report overruns (overflowed is always False).
    """
    from .platform.linux import get_pulse_server_info

    # Fixed 48 kHz on Linux: these calls disable both resamplers.
    processor.setup_resampler(PULSE_TARGET_SR)
    processor.setup_output_resampler(PULSE_TARGET_SR)

    block_size = processor.frame_size
    server_name, server_version = get_pulse_server_info()
    _run_logger = _logger
    _run_logger.info(
        "run start: model=%s frame_size=%s target_sr=%s source=%s sink=%s "
        "backend=pulse-simple server=%s version=%s log=%s",
        getattr(getattr(processor, "engine", None), "name", "?"),
        block_size, PULSE_TARGET_SR, source, sink,
        server_name, server_version, get_log_file_path(),
    )

    empty_reads = 0
    start_time = time.time()
    last_stats = start_time
    with PulseCapture(source, block_size) as cap, \
            PulsePlayback(sink, block_size) as play:
        while not _should_stop(should_stop):
            chunk, _overflowed = cap.read()
            if chunk is None or len(chunk) == 0:
                empty_reads += 1
                continue
            audio_output = processor.process_chunk(chunk.flatten())
            if audio_output is not None:
                # PulsePlayback.write duplicates mono to stereo as needed;
                # write exactly what the pipeline produced (no zero padding,
                # which would insert silence and shift A/V sync).
                play.write(np.ascontiguousarray(audio_output, dtype=np.float32))
            now = time.time()
            if on_stats is not None and (now - last_stats) >= stats_interval_sec:
                try:
                    on_stats(processor.get_stats(), now - start_time)
                except Exception:
                    pass
                last_stats = now
    elapsed = time.time() - start_time
    final = processor.get_stats()
    _run_logger.info(
        "run stop: frames=%s empty_reads=%s elapsed=%.1fs",
        final.get("frame_count"), empty_reads, elapsed,
    )
    return final, empty_reads


def process_with_pulse(processor,
                       source: str,
                       sink: str) -> None:
    """Blocking CLI entry point: capture -> process -> playback until Ctrl+C.

    Args:
        processor: DenoiserAudioProcessor instance.
        source: Pulse source name for capture.
        sink: Pulse sink name for playback.
    """
    _logger.info("Using pulse-simple backend")
    print("\nStarting real-time system audio processing...")
    print(f"Source: {source}")
    print(f"Sink: {sink}")
    print("Press Ctrl+C to stop...\n")

    start_time = time.time()
    last_stats_time = start_time

    def _on_stats(stats: Dict, elapsed: float) -> None:
        nonlocal last_stats_time
        print_stats(stats, elapsed)
        last_stats_time = time.time()

    try:
        final_stats, _ = run_pulse_loop(
            processor, source, sink,
            should_stop=None, on_stats=_on_stats,
        )
    except KeyboardInterrupt:
        print("\n\nStopping...")
        final_stats = processor.get_stats()

    print_final_stats(final_stats)
