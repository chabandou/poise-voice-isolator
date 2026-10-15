"""
ctypes binding for libpoise_pw.so, the in-graph PipeWire node (Linux).

The native side (native/poise_pw/) runs poise_core's fixed-delay exchange
(delay_core) in PipeWire's realtime cycle and never waits on Python;
node_loop runs inference for it. The Windows audio path (wasapi_node)
runs the same core.
"""
import ctypes
import os
import sys
from typing import Optional, Tuple

from ..logging_config import get_logger
from .delay_core import STAT_NAMES, CoreOps, bind, core_signatures
from .node_loop import NodeError

_logger = get_logger(__name__)

LIB_NAME = "libpoise_pw.so"

# pw_stream_state values.
STREAM_STATES = {-1: "error", 0: "unconnected", 1: "connecting",
                 2: "paused", 3: "streaming"}


class PipeWireNodeUnavailable(RuntimeError):
    """libpoise_pw.so (or libpipewire) could not be loaded."""


class PipeWireNodeError(NodeError):
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
    u32 = ctypes.c_uint32
    vp = ctypes.c_void_p
    sigs = {
        **core_signatures(),
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
    bind(lib, sigs)


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


class PipeWireNode(CoreOps):
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
