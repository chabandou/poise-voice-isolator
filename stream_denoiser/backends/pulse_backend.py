"""
PulseAudio backend (Linux).

Single shared processing loop used by both the CLI
(:func:`process_with_pulse`) and the TUI, so the two paths cannot
diverge. I/O is via libpulse-simple at a fixed 48 kHz float32; the
server handles rate/format conversion, so no resampler is configured.
"""
import sys
import time
from contextlib import contextmanager
from typing import Callable, Dict, Optional, Tuple, Union

import numpy as np

from ..audio_gc import gc_paused
from ..constants import PULSE_TARGET_SR, STATS_PRINT_INTERVAL_SEC
from ..device_utils import print_stats, print_final_stats
from ..logging_config import get_logger, get_log_file_path
from ..sync import CaptureBacklogGuard, StallCounter
from .pulse_simple import NODE_GROUP, PulseCapture, PulsePlayback

_logger = get_logger(__name__)

# Cadence of the "sync:" file-log line (capture backlog diagnostics).
SYNC_LOG_INTERVAL_SEC = 30.0

# How soon a waiting thread gets the GIL (Python's default is 5 ms).
AUDIO_SWITCH_INTERVAL_SEC = 0.0005


@contextmanager
def _fast_gil_handoff():
    """Shorten the GIL switch interval while the audio loop runs.

    The loop reacquires the GIL after every read, inference and write.
    When a UI thread is busy (Textual redrawing after its terminal is
    shown again, e.g. switching to its workspace), each reacquire waited
    up to the default 5 ms: measured ~50 ms of lost audio time per switch,
    which stays behind as A/V lag. At 0.5 ms the loss is ~2-4 ms.
    """
    previous = sys.getswitchinterval()
    sys.setswitchinterval(AUDIO_SWITCH_INTERVAL_SEC)
    try:
        yield
    finally:
        sys.setswitchinterval(previous)


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
                   stats_interval_sec: float = STATS_PRINT_INTERVAL_SEC,
                   pause_gc: bool = False,
                   ) -> Tuple[dict, int]:
    """Run the capture -> process -> playback loop.

    Args:
        processor: Configured DenoiserAudioProcessor (engine already set).
        source: Pulse source name for capture (e.g. Poise_Capture.monitor).
        sink: Pulse sink name for playback (real hardware sink).
        should_stop: threading.Event, callable, or None.
        on_stats: Optional callback(stats, elapsed_sec) every interval.
        stats_interval_sec: Stats callback cadence.
        pause_gc: Keep the garbage collector off while the streams are
            open (only in a process that does nothing else; see audio_gc).

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

    # Time the loop loses stays behind as capture backlog for good; the
    # guard discards it (see sync.py). Clock drift is prevented by the
    # PipeWire node group the streams join (see pulse_simple.NODE_GROUP).
    block_ms = block_size * 1000.0 / PULSE_TARGET_SR
    guard = CaptureBacklogGuard(block_ms)
    # Audio time lost to slow iterations (what becomes that backlog); each
    # stall is also logged so its timestamp can be matched to what else
    # was going on.
    stalls = StallCounter(block_ms)

    empty_reads = 0
    start_time = time.time()
    last_stats = start_time
    last_sync_log = start_time
    # The collection before the loop runs before the streams open: once
    # capture runs, any time spent stays behind as backlog.
    with gc_paused(pause_gc), _fast_gil_handoff(), \
            PulseCapture(source, block_size) as cap, \
            PulsePlayback(sink, block_size) as play:
        _run_logger.info("sync: node.group=%s", NODE_GROUP)
        while not _should_stop(should_stop):
            chunk, _overflowed = cap.read()
            now_mono = time.monotonic()
            stall_ms = stalls.observe(now_mono)
            if stall_ms:
                _run_logger.info("sync: stall %.0f ms (loop iteration)",
                                 stall_ms)
            raises = guard.offset_raises
            drop = guard.observe(cap.latency_ms(), now_mono)
            if guard.offset_raises != raises:
                _run_logger.warning(
                    "sync: dropping audio did not lower the capture latency; "
                    "taking %.0f ms as this server's minimum",
                    guard.offset_ms)
            if drop:
                # Already buffered, so these reads return immediately.
                for _ in range(drop):
                    cap.read()
                _run_logger.info(
                    "sync: dropped %d blocks (%.0f ms) of capture backlog "
                    "(capture latency %.0f ms)", drop, drop * block_ms,
                    guard.window_min_ms)
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
            if now - last_sync_log >= SYNC_LOG_INTERVAL_SEC:
                _run_logger.info(
                    "sync: excess=%.1fms offset=%.1fms dropped=%.0fms "
                    "lost=%.0fms stalls=%d max_stall=%.0fms "
                    "capture_latency=%.1fms play_latency=%.1fms",
                    guard.excess_ms, guard.offset_ms, guard.dropped_ms,
                    stalls.lost_ms, stalls.count, stalls.max_ms,
                    cap.latency_ms(), play.latency_ms())
                last_sync_log = now
    elapsed = time.time() - start_time
    final = processor.get_stats()
    _run_logger.info(
        "run stop: frames=%s empty_reads=%s elapsed=%.1fs "
        "sync_drops=%s sync_dropped=%.0fms lost=%.0fms stalls=%s "
        "max_stall=%.0fms",
        final.get("frame_count"), empty_reads, elapsed,
        guard.drop_events, guard.dropped_ms, stalls.lost_ms, stalls.count,
        stalls.max_ms,
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
            should_stop=None, on_stats=_on_stats, pause_gc=True,
        )
    except KeyboardInterrupt:
        print("\n\nStopping...")
        final_stats = processor.get_stats()

    print_final_stats(final_stats)
