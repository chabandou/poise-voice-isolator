"""
ctypes face of poise_core, the native fixed-delay exchange both native
nodes run (native/poise_pw/poise_core.c): the PipeWire node on Linux
(libpoise_pw.so, pipewire_node) and the WASAPI node on Windows
(poise_wasapi.dll, wasapi_node). Each library exports the same
poise_core_* functions.

The node's realtime thread never waits on Python. It hands frames to an
inference thread (node_loop) through ``wait_frame()`` and takes them back
through ``put_frame()``; ctypes releases the GIL while the thread waits.

``DelayCore`` is the exchange alone, driven by hand; the tests use it to
check timing exactly.
"""
import ctypes
from typing import Dict, Optional

import numpy as np

# Order of poise_core_get_stats() (enum poise_stat in poise_core.h).
STAT_NAMES = (
    "cycles", "in_pos", "out_pos", "delay", "quantum", "quantum_max",
    "frames_wet", "frames_dry", "frames_skipped", "frames_late",
    "delay_changes", "resyncs", "input_gaps", "trigger_fails",
)

# wait_frame() results besides a frame index.
WAIT_TIMEOUT = -1
WAIT_STOPPED = -2


def core_signatures() -> dict:
    """ctypes signatures of poise_core (exported by both node libraries)."""
    u32, i64, u64 = ctypes.c_uint32, ctypes.c_int64, ctypes.c_uint64
    vp, fp = ctypes.c_void_p, ctypes.c_void_p
    return {
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
    }


def bind(lib, sigs: dict) -> None:
    for name, (args, res) in sigs.items():
        fn = getattr(lib, name)
        fn.argtypes = args
        fn.restype = res


def _f32(a: np.ndarray, n: int) -> np.ndarray:
    a = np.ascontiguousarray(a, dtype=np.float32)
    if a.ndim != 1 or a.shape[0] != n:
        raise ValueError(f"expected {n} float32 samples, got shape {a.shape}")
    return a


class CoreOps:
    """Worker-side calls shared by DelayCore and the native nodes."""

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


class DelayCore(CoreOps):
    """The fixed-delay exchange alone, cycles driven by the caller.

    ``lib``: a loaded library exporting poise_core (default
    libpoise_pw.so; on Windows, wasapi_node.load_library()).
    """

    def __init__(self, frame: int, engine_latency: int = 0,
                 quantum: int = 512, margin: int = 1024, fade: int = 64,
                 dry_gain: float = 1.0, lib=None):
        if lib is None:
            from .pipewire_node import load_library
            lib = load_library()
        self._lib = lib
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
