"""
Garbage collection policy for the audio loop.

CPython's cyclic garbage collector starts a pass whenever enough
container objects have been allocated, on whichever thread allocates
next, and holds the GIL until the pass is done: it can land between any
two frames. The hot path creates no reference cycles (tests/test_audio_gc.py
guards that), so reference counting frees everything it allocates and
the collector can stay off for a whole run.
"""
import gc
import time
from contextlib import contextmanager

from .logging_config import get_logger

_logger = get_logger(__name__)


@contextmanager
def gc_paused(enabled: bool = True):
    """Collect once, then keep the collector off until the block ends.

    Survivors of the first collection are frozen, so the collection at
    the end only scans what the run allocated. It is logged and should
    find nothing: whatever it finds was a cycle that leaked for the
    whole run. The setting is process-wide, so only for a process that
    does nothing but audio (the audio process, the CLI).
    """
    if not enabled:
        yield
        return
    was_enabled = gc.isenabled()
    t0 = time.perf_counter()
    gc.collect()
    gc.freeze()
    gc.disable()
    start_ms = (time.perf_counter() - t0) * 1000.0
    try:
        yield
    finally:
        # All older objects are frozen and nothing was collected since,
        # so the youngest generation is what the run allocated and kept
        # (it should not grow with the run's length).
        kept = len(gc.get_objects(0))
        t0 = time.perf_counter()
        found = gc.collect()
        stop_ms = (time.perf_counter() - t0) * 1000.0
        gc.unfreeze()
        if was_enabled:
            gc.enable()
        _logger.info(
            "gc: off for the run (collect %.1f ms at start, %.1f ms at "
            "stop); the run left %d objects, %d of them unreachable",
            start_ms, stop_ms, kept, found)
