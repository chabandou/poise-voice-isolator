"""
ctypes binding for poise_wasapi.dll, Poise's native audio path (Windows).

The native side (native/poise_wasapi/) captures CABLE Output and plays to
the speakers from one MMCSS thread and never waits on Python. As with the
PipeWire node, it hands frames to an inference thread through
``wait_frame()`` and takes them back through ``put_frame()``; ctypes
releases the GIL while the thread waits.

``ClockBridge`` is the capture-to-speakers clock bridge alone, driven by
hand; the tests use it to check drift handling exactly.
"""
import ctypes
import os
import sys
from typing import Dict, Optional

import numpy as np

from ..logging_config import get_logger
from .pipewire_node import (  # noqa: F401 (wait results re-exported)
    WAIT_STOPPED, WAIT_TIMEOUT, _CoreOps, bind, core_signatures)

_logger = get_logger(__name__)

LIB_NAME = "poise_wasapi.dll"

# Order of poise_wasapi_get_stats() (enum poise_win_stat in poise_wasapi.h).
IO_STAT_NAMES = (
    "capture_frames", "capture_packets", "capture_glitches",
    "render_frames", "render_events", "render_underruns", "render_late",
    "render_gap_max_us", "wake_timeouts", "fifo_safety", "fifo_target",
    "fifo_level", "fifo_headroom", "fifo_starved", "fifo_inserted",
    "fifo_resyncs", "fifo_dropped", "rate_ppb", "capture_period",
    "capture_buffer", "render_period", "render_buffer", "render_fill",
    "mmcss", "fifo_stalls", "render_queue", "capture_age_us",
    "capture_restarts",
)
# Order of poise_bridge_get_stats() (enum poise_bridge_stat).
BRIDGE_STAT_NAMES = ("safety", "target", "level", "headroom", "starved",
                     "inserted", "resyncs", "dropped", "rate_ppb", "stalls")
_SIGNED = {"rate_ppb", "headroom", "fifo_headroom", "render_queue",
           "capture_age_us"}


class WasapiUnavailable(RuntimeError):
    """poise_wasapi.dll could not be loaded."""


class WasapiError(RuntimeError):
    """The devices could not be opened, or the audio thread failed."""


_lib = None


def _candidate_paths():
    paths = []
    # PyInstaller: next to Poise.exe (one-dir), or the extraction dir.
    if getattr(sys, "frozen", False):
        paths.append(os.path.join(os.path.dirname(sys.executable), LIB_NAME))
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            paths.append(os.path.join(meipass, LIB_NAME))
    here = os.path.dirname(os.path.abspath(__file__))
    paths.append(os.path.join(here, "..", "native", LIB_NAME))
    return [os.path.normpath(p) for p in paths]


def _bind(lib) -> None:
    u32, u64 = ctypes.c_uint32, ctypes.c_uint64
    vp, fp, cp = ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p
    bind(lib, {
        **core_signatures(),
        "poise_wasapi_new": ([cp, cp, u32, u32, u32, u32, ctypes.c_float,
                              u32, u32, cp, ctypes.c_size_t], vp),
        "poise_wasapi_destroy": ([vp], None),
        "poise_wasapi_core": ([vp], vp),
        "poise_wasapi_status": ([vp, cp, ctypes.c_size_t], ctypes.c_int),
        "poise_wasapi_get_stats": ([vp, ctypes.POINTER(u64), u32], None),
        "poise_wasapi_stat_count": ([], u32),
        "poise_wasapi_io_latency": ([vp], u32),
        "poise_bridge_new": ([u32, u32], vp),
        "poise_bridge_free": ([vp], None),
        "poise_bridge_push": ([vp, fp, u32, ctypes.c_double], None),
        "poise_bridge_update": ([vp, ctypes.c_double], None),
        "poise_bridge_read": ([vp, fp, u32], None),
        "poise_bridge_get_stats": ([vp, ctypes.POINTER(u64), u32], None),
        "poise_bridge_delay": ([], u32),
    })


def load_library():
    """Load poise_wasapi.dll (cached). Raises WasapiUnavailable."""
    global _lib
    if _lib is not None:
        return _lib
    if sys.platform != "win32":
        raise WasapiUnavailable("Windows only")
    errors = []
    for path in _candidate_paths():
        if not os.path.exists(path):
            continue
        try:
            lib = ctypes.CDLL(path)
            _bind(lib)
        except (OSError, AttributeError) as e:
            errors.append(f"{path}: {e}")
            continue
        if lib.poise_wasapi_stat_count() != len(IO_STAT_NAMES):
            errors.append(f"{path}: built from other sources (stale build)")
            continue
        _lib = lib
        return lib
    raise WasapiUnavailable("; ".join(errors) or f"{LIB_NAME} not found")


def _stats(fn, handle, names) -> Dict[str, int]:
    buf = (ctypes.c_uint64 * len(names))()
    fn(handle, buf, len(names))
    out = {}
    for name, v in zip(names, buf):
        v = int(v)
        if name in _SIGNED and v >= 1 << 63:
            v -= 1 << 64
        out[name] = v
    return out


class WasapiNode(_CoreOps):
    """CABLE Output -> poise_core -> speakers, live in WASAPI.

    Created running: until a worker calls ``wait_frame`` the output is
    the unprocessed input, delayed like processed audio would be.
    """

    def __init__(self, *, capture: Optional[str], render: Optional[str],
                 frame: int, engine_latency: int, margin: int, fade: int,
                 dry_gain: float, fifo_safety: int, render_fill: int):
        self._lib = load_library()
        self.frame = int(frame)
        self.engine_latency = int(engine_latency)
        err = ctypes.create_string_buffer(512)
        self._handle = self._lib.poise_wasapi_new(
            capture.encode() if capture else None,
            render.encode() if render else None,
            self.frame, self.engine_latency, int(margin), int(fade),
            float(dry_gain), int(fifo_safety), int(render_fill),
            err, len(err))
        if not self._handle:
            raise WasapiError(
                err.value.decode(errors="replace") or "unknown error")
        self._core = self._lib.poise_wasapi_core(self._handle)

    @property
    def io_latency_samples(self) -> int:
        """Delay of the device side: clock bridge plus queued output."""
        return int(self._lib.poise_wasapi_io_latency(self._handle))

    @property
    def latency_samples(self) -> int:
        """Delay Poise adds from CABLE Output to the speakers' buffer:
        device side + fixed delay + the engine's own."""
        return (self.io_latency_samples + self.delay_samples
                + self.engine_latency)

    def io_stats(self) -> Dict[str, int]:
        return _stats(self._lib.poise_wasapi_get_stats, self._handle,
                      IO_STAT_NAMES)

    def error(self) -> Optional[str]:
        err = ctypes.create_string_buffer(512)
        if self._lib.poise_wasapi_status(self._handle, err, len(err)):
            return err.value.decode(errors="replace") or "unknown error"
        return None

    def close(self) -> None:
        """Stop the audio thread and close both devices. Idempotent."""
        if self._handle:
            self._lib.poise_wasapi_destroy(self._handle)
            self._handle = None
            self._core = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


class ClockBridge:
    """The clock bridge alone: push capture packets and read render
    cycles at chosen times (seconds), as the audio thread does.

    ``start_level``: fill when reading starts; ``safety``: headroom the
    rate control keeps at worst (samples).
    """

    def __init__(self, start_level: int, safety: int):
        self._lib = load_library()
        self._b = self._lib.poise_bridge_new(int(start_level), int(safety))
        if not self._b:
            raise ValueError("invalid bridge start level or safety")

    @property
    def delay(self) -> int:
        """Resampler lookahead (samples) included in the level."""
        return int(self._lib.poise_bridge_delay())

    def push(self, x: np.ndarray, now: float) -> None:
        x = np.ascontiguousarray(x, dtype=np.float32)
        self._lib.poise_bridge_push(self._b, x.ctypes.data, len(x),
                                    float(now))

    def update(self, now: float) -> None:
        self._lib.poise_bridge_update(self._b, float(now))

    def read(self, n: int) -> np.ndarray:
        out = np.empty(int(n), dtype=np.float32)
        self._lib.poise_bridge_read(self._b, out.ctypes.data, len(out))
        return out

    def stats(self) -> Dict[str, int]:
        return _stats(self._lib.poise_bridge_get_stats, self._b,
                      BRIDGE_STAT_NAMES)

    def close(self) -> None:
        if self._b:
            self._lib.poise_bridge_free(self._b)
            self._b = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
