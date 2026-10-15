"""
Helpers the audio loops share: the native nodes' inference thread
(node_loop), pulse-simple and PortAudio.
"""
import os
import sys
from contextlib import contextmanager
from typing import Callable, Union

from ..constants import DEFAULT_SAMPLE_RATE
from ..logging_config import get_logger

_logger = get_logger(__name__)

# Cadence of the "sync:" file-log line.
SYNC_LOG_INTERVAL_SEC = 30.0

# How soon a waiting thread gets the GIL while a loop runs (Python's
# default is 5 ms).
SWITCH_INTERVAL_SEC = 0.0005

# should_stop may be a threading.Event, a zero-arg callable, or None (run
# until KeyboardInterrupt).
StopLike = Union[object, Callable[[], bool], None]


def stop_requested(stop: StopLike) -> bool:
    """Whether a loop's ``should_stop`` asks it to end."""
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


@contextmanager
def fast_gil_handoff():
    """Shorten the GIL switch interval while a loop runs.

    The pulse-simple and PortAudio loops reacquire the GIL after every
    read, inference and write. When a UI thread is busy (Textual
    redrawing after its terminal is shown again, e.g. switching to its
    workspace), each reacquire waited up to the default 5 ms: measured
    ~50 ms of lost audio time per switch, which stays behind as A/V lag.
    At 0.5 ms the loss is ~2-4 ms. A node's inference thread likewise
    gets the GIL back within 0.5 ms, so frames make their slot.
    """
    previous = sys.getswitchinterval()
    sys.setswitchinterval(SWITCH_INTERVAL_SEC)
    try:
        yield
    finally:
        sys.setswitchinterval(previous)


def ms(samples: int, rate: int = DEFAULT_SAMPLE_RATE) -> float:
    return samples * 1000.0 / rate


def margin_samples(env: str, default: int,
                   rate: int = DEFAULT_SAMPLE_RATE) -> int:
    """A node's worker margin in samples: ``env`` (milliseconds) overrides
    ``default``."""
    value = os.environ.get(env)
    if value:
        try:
            return max(0, int(float(value) * rate / 1000.0))
        except ValueError:
            _logger.warning("Ignoring %s=%r (not a number)", env, value)
    return int(default)
