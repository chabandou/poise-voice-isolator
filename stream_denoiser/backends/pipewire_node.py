"""
ctypes binding for libpoise_pw.so, the in-graph PipeWire node (Linux).

The native side (native/poise_pw/) runs in PipeWire's realtime cycle and
never waits on Python. It hands frames to an inference thread through
``wait_frame()`` and takes them back through ``put_frame()``; ctypes
releases the GIL while the thread waits.

``DelayCore`` is the same fixed-delay exchange without PipeWire, driven
by hand; the tests use it to check timing exactly.
"""
import ctypes
import os
import sys
from typing import Dict, Optional, Tuple

import numpy as np

from ..logging_config import get_logger

_logger = get_logger(__name__)

LIB_NAME = "libpoise_pw.so"

# Order of poise_core_get_stats() (enum poise_stat in poise_core.h).
STAT_NAMES = (
    "cycles", "in_pos", "out_pos", "delay", "quantum", "quantum_max",
    "frames_wet", "frames_dry", "frames_skipped", "frames_late",
    "delay_changes", "resyncs", "input_gaps", "trigger_fails",
)

# pw_stream_state values.
STREAM_STATES = {-1: "error", 0: "unconnected", 1: "connecting",
                 2: "paused", 3: "streaming"}

# wait_frame() results besides a frame index.
WAIT_TIMEOUT = -1
WAIT_STOPPED = -2


class PipeWireNodeUnavailable(RuntimeError):
    """libpoise_pw.so (or libpipewire) could not be loaded."""


class PipeWireNodeError(RuntimeError):
    """The node could not be created, or PipeWire reported an error."""


_lib = None


def _candidate_paths():
    here = os.path.dirname(os.path.abspath(__file__))
    paths = [os.path.join(here, "..", "native", LIB_NAME)]
    # Nuitka onefile: data files sit next to the running binary.
    if sys.platform.startswith("linux"):
        try:
            exe_dir = os.path.dirname(os.path.realpath("/proc/self/exe"))
            paths.append(os.path.join(exe_dir, "stream_denoiser", "native",
                                      LIB_NAME))
        except OSError:
            pass
    return [os.path.normpath(p) for p in paths]


def _bind(lib) -> None:
    u32, i64, u64 = ctypes.c_uint32, ctypes.c_int64, ctypes.c_uint64
    vp, fp = ctypes.c_void_p, ctypes.c_void_p
    sigs = {
        "poise_core_new": ([u32, u32, u32, u32, u32, ctypes.c_float], vp),
        "poise_core_free": ([vp], None),
        "poise_core_cycle_mono": ([vp, fp, u32, fp, u32], ctypes.c_int),
        "poise_core_wait_frame": ([vp, fp, ctypes.c_int], i64),
        "poise_core_put_frame": ([vp, i64, fp], None),
        "poise_core_stop": ([vp], None),
        "poise_core_get_stats": ([vp, ctypes.POINTER(u64), u32], None),
        "poise_core_delay": ([vp], u64),
        "poise_core_frame": ([vp], u32),
        "poise_core_stat_count": ([], u32),
        "poise_pw_new": ([ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
                          u32, u32, u32, u32, u32, ctypes.c_float,
                          ctypes.c_char_p, ctypes.c_size_t], vp),
        "poise_pw_destroy": ([vp], None),
        "poise_pw_core": ([vp], vp),
        "poise_pw_status": ([vp, ctypes.POINTER(ctypes.c_int),
                             ctypes.POINTER(ctypes.c_int),
                             ctypes.c_char_p, ctypes.c_size_t], ctypes.c_int),
        "poise_pw_library_version": ([], ctypes.c_char_p),
    }
    for name, (args, res) in sigs.items():
        fn = getattr(lib, name)
        fn.argtypes = args
        fn.restype = res


def load_library():
    """Load libpoise_pw.so (cached). Raises PipeWireNodeUnavailable."""
    global _lib
    if _lib is not None:
        return _lib
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
        if lib.poise_core_stat_count() != len(STAT_NAMES):
            errors.append(f"{path}: built from other sources (stale build)")
            continue
        _lib = lib
        return lib
    detail = "; ".join(errors) or (
        f"{LIB_NAME} not found (build it: make -C native/poise_pw)")
    raise PipeWireNodeUnavailable(detail)


def pipewire_library_version() -> Optional[str]:
    """Version of the libpipewire the node links against, or None."""
    try:
        v = load_library().poise_pw_library_version()
        return v.decode() if v else None
    except Exception:
        return None


def _f32(a: np.ndarray, n: int) -> np.ndarray:
    a = np.ascontiguousarray(a, dtype=np.float32)
    if a.ndim != 1 or a.shape[0] != n:
        raise ValueError(f"expected {n} float32 samples, got shape {a.shape}")
    return a


class _CoreOps:
    """Worker-side calls shared by DelayCore and PipeWireNode."""

    _lib = None
    _core = None
    frame = 0

    def wait_frame(self, out: np.ndarray, timeout_ms: int) -> int:
        """Copy the next frame to process into ``out`` (float32, C order).

        Returns its index, WAIT_TIMEOUT, or WAIT_STOPPED.
        """
        if out.dtype != np.float32 or not out.flags.c_contiguous \
                or out.shape != (self.frame,):
            raise ValueError("out must be a C-contiguous float32 frame")
        return int(self._lib.poise_core_wait_frame(
            self._core, out.ctypes.data, int(timeout_ms)))

    def put_frame(self, k: int, frame: np.ndarray) -> None:
        """Hand back processed frame ``k``."""
        data = _f32(frame, self.frame)
        self._lib.poise_core_put_frame(self._core, int(k), data.ctypes.data)

    def stats(self) -> Dict[str, int]:
        buf = (ctypes.c_uint64 * len(STAT_NAMES))()
        self._lib.poise_core_get_stats(self._core, buf, len(STAT_NAMES))
        return dict(zip(STAT_NAMES, (int(v) for v in buf)))

    @property
    def delay_samples(self) -> int:
        """Fixed delay between input and output, excluding the engine's."""
        return int(self._lib.poise_core_delay(self._core))

    def stop(self) -> None:
        """Wake and stop a waiting worker (wait_frame returns WAIT_STOPPED)."""
        self._lib.poise_core_stop(self._core)


class DelayCore(_CoreOps):
    """The fixed-delay exchange alone, cycles driven by the caller."""

    def __init__(self, frame: int, engine_latency: int = 0,
                 quantum: int = 512, margin: int = 1024, fade: int = 64,
                 dry_gain: float = 1.0):
        self._lib = load_library()
        self.frame = int(frame)
        self._core = self._lib.poise_core_new(
            self.frame, int(engine_latency), int(quantum), int(margin),
            int(fade), float(dry_gain))
        if not self._core:
            raise ValueError("invalid core parameters")

    def cycle(self, inp: Optional[np.ndarray], n_out: int) -> np.ndarray:
        """One cycle: append ``inp`` (mono, may be None), output n_out."""
        out = np.zeros(int(n_out), dtype=np.float32)
        if inp is None:
            in_ptr, n_in = None, 0
        else:
            inp = np.ascontiguousarray(inp, dtype=np.float32)
            in_ptr, n_in = inp.ctypes.data, len(inp)
        self._lib.poise_core_cycle_mono(self._core, in_ptr, n_in,
                                        out.ctypes.data, len(out))
        return out

    def close(self) -> None:
        if self._core:
            self._lib.poise_core_free(self._core)
            self._core = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


class PipeWireNode(_CoreOps):
    """Poise's virtual sink and its output stream, live in PipeWire.

    Created streaming: the sink appears as ``node_name`` and plays to
    ``target`` (a sink name; None = default). Until a worker calls
    ``wait_frame`` the output is the unprocessed input.
    """

    def __init__(self, *, frame: int, engine_latency: int, quantum: int,
                 margin: int, fade: int, dry_gain: float, node_name: str,
                 description: str, target: Optional[str] = None):
        self._lib = load_library()
        self.frame = int(frame)
        self.engine_latency = int(engine_latency)
        self.node_name = node_name
        err = ctypes.create_string_buffer(512)
        self._handle = self._lib.poise_pw_new(
            node_name.encode(), description.encode(),
            target.encode() if target else None,
            self.frame, self.engine_latency, int(quantum), int(margin),
            int(fade), float(dry_gain), err, len(err))
        if not self._handle:
            raise PipeWireNodeError(
                err.value.decode(errors="replace") or "unknown error")
        self._core = self._lib.poise_pw_core(self._handle)

    @property
    def latency_samples(self) -> int:
        """Total delay the node adds: fixed delay + the engine's own."""
        return self.delay_samples + self.engine_latency

    def status(self) -> Tuple[str, str, Optional[str]]:
        """(sink state, output state, error message or None)."""
        cap, play = ctypes.c_int(0), ctypes.c_int(0)
        err = ctypes.create_string_buffer(256)
        failed = self._lib.poise_pw_status(
            self._handle, ctypes.byref(cap), ctypes.byref(play), err, len(err))
        return (STREAM_STATES.get(cap.value, str(cap.value)),
                STREAM_STATES.get(play.value, str(play.value)),
                err.value.decode(errors="replace") if failed else None)

    def error(self) -> Optional[str]:
        return self.status()[2]

    def close(self) -> None:
        """Remove the node from PipeWire. Idempotent."""
        if self._handle:
            self._lib.poise_pw_destroy(self._handle)
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
