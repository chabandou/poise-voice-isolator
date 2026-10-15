"""
The inference thread of a native node.

Both native nodes, the PipeWire node on Linux and the WASAPI node on
Windows, run poise_core's fixed-delay exchange (delay_core) on a thread
that never waits on Python. This loop takes each frame from the core,
runs it through the processor and hands it back; a frame that is not back
in time plays unprocessed and the delay stays put. Each backend adds its
own "sync:" lines through the log_sync / log_events hooks.
"""
import time

import numpy as np

from ..logging_config import get_logger
from ._loop_util import SYNC_LOG_INTERVAL_SEC, fast_gil_handoff, ms, \
    stop_requested
from .delay_core import WAIT_STOPPED

_logger = get_logger(__name__)

# How long the worker waits for a frame before checking for stop/errors.
WAIT_TIMEOUT_MS = 100
# How often counters are checked for events worth their own log line.
EVENT_CHECK_SEC = 0.5


class NodeError(RuntimeError):
    """A native node could not be created, or it reported an error."""


def log_core_events(node, seen: dict, gap_max: float,
                    busy_max: float) -> dict:
    """One log line per core event since the last check, so it can be
    matched to what else was happening. Returns the new counters."""
    st = node.stats()
    dry = st["frames_dry"] - seen["frames_dry"]
    if dry > 0:
        _logger.info(
            "sync: %d frames (%.0f ms) played unprocessed; longest gap "
            "between frames %.0f ms, longest frame %.0f ms",
            dry, ms(dry * node.frame), gap_max * 1000.0, busy_max * 1000.0)
    if st["delay_changes"] > seen["delay_changes"]:
        _logger.info(
            "sync: delay raised to %d samples (latency %.1fms) for a "
            "%d-sample cycle", node.delay_samples, ms(node.latency_samples),
            st["quantum_max"])
    for key, what in (("resyncs", "input arrived in a burst; output jumped "
                                  "ahead to keep the delay"),
                      ("input_gaps", "input fell short; gap played as "
                                     "silence")):
        if st[key] > seen[key]:
            _logger.info("sync: %s (%d)", what, st[key] - seen[key])
    return st


def worker_loop(node, processor, should_stop, on_stats,
                stats_interval_sec: float, start_time: float, *,
                log_sync, log_events=log_core_events,
                error=NodeError) -> None:
    """Inference for ``node``'s fixed-delay core until stopped.

    Args:
        log_sync: log_sync(node), the periodic "sync:" summary line.
        log_events: log_events(node, seen, gap_max, busy_max) -> counters,
            one line per event since the last check.
        error: Raised with the node's message when it reports an error.
    """
    buf = np.empty(node.frame, dtype=np.float32)
    last_stats = last_sync = last_event = time.time()
    seen = node.stats()
    # Longest wait between frames and longest frame since the last event
    # check: tells a stalled thread from slow inference when frames play
    # unprocessed.
    gap_max = busy_max = 0.0
    last_frame = None
    with fast_gil_handoff():
        while not stop_requested(should_stop):
            k = node.wait_frame(buf, WAIT_TIMEOUT_MS)
            if k == WAIT_STOPPED:
                break
            if k >= 0:
                t_frame = time.perf_counter()
                if last_frame is not None:
                    gap_max = max(gap_max, t_frame - last_frame)
                last_frame = t_frame
                # A copy: engines may keep a reference to their input.
                out = processor.process_chunk(buf.copy())
                if out is not None:
                    node.put_frame(k, out)
                busy_max = max(busy_max, time.perf_counter() - t_frame)
            now = time.time()
            if now - last_event >= EVENT_CHECK_SEC:
                seen = log_events(node, seen, gap_max, busy_max)
                gap_max = busy_max = 0.0
                last_event = now
            due = now - last_stats >= stats_interval_sec
            if k < 0 or due:
                message = node.error()
                if message:
                    raise error(message)
            if due:
                if on_stats is not None:
                    try:
                        on_stats(processor.get_stats(), now - start_time)
                    except Exception:
                        pass
                last_stats = now
            if now - last_sync >= SYNC_LOG_INTERVAL_SEC:
                log_sync(node)
                last_sync = now
