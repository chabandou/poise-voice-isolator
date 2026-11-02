"""
ctypes binding for libpoise_coreaudio.dylib, Poise's native audio path
(macOS).

The native side (native/poise_coreaudio/) taps every app's audio with a
global Core Audio process tap, runs poise_core's fixed-delay exchange
(delay_core) from the aggregate's IOProc and plays the result back
through the same output device; it never waits on Python. node_loop runs
inference for it, as for the PipeWire node on Linux and the WASAPI node
on Windows.

The tap silences the apps it is read from (plan C1), so ``close()`` —
which destroys the tap — is what gives the Mac its audio back.
``_destroy_live_nodes`` runs it for a node still alive at exit.
"""
import atexit
import ctypes
import os
import sys
import threading
from typing import Dict, Optional

from ..logging_config import get_logger
from .delay_core import STAT_NAMES, CoreOps, bind, core_signatures
from .node_loop import NodeError

_logger = get_logger(__name__)

LIB_NAME = "libpoise_coreaudio.dylib"

# Order of poise_ca_get_stats() (enum poise_ca_stat in poise_coreaudio.h).
CA_STAT_NAMES = (
    "callbacks", "input_frames", "output_frames", "frames_wet",
    "frames_dry", "frames_skipped", "frames_late", "delay_changes",
    "resyncs", "input_gaps", "quantum_max", "delay_samples", "dropped",
    "overloads", "quiet_frames", "saw_signal", "drift_samples",
    "time_delta_min", "time_delta_max", "rt_policy", "restarts",
    "tap_alive",
)
_SIGNED = {"drift_samples", "time_delta_min", "time_delta_max"}

# The rate the node's streams carry unless asked for another one. Plan C2:
# the node refuses a device whose aggregate streams it cannot give this
# rate, so a running node's streams always carry the requested rate.
NODE_RATE = 48000


class CoreAudioUnavailable(RuntimeError):
    """libpoise_coreaudio.dylib could not be loaded.

    A RuntimeError (not a NodeError) because nothing failed to run: this
    host cannot run the path at all.
    """


class CoreAudioError(NodeError):
    """The tap, the aggregate or a device failed."""


_lib = None


def _candidate_paths():
    paths = []
    # PyInstaller: next to the app's executable, or the extraction dir.
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
    vp, cp = ctypes.c_void_p, ctypes.c_char_p
    bind(lib, {
        **core_signatures(),
        "poise_ca_new": ([cp, u32, u32, u32, u32, u32, ctypes.c_float, u32,
                          ctypes.c_int, cp, ctypes.c_size_t], vp),
        "poise_ca_destroy": ([vp], None),
        "poise_ca_core": ([vp], vp),
        "poise_ca_frame": ([vp], u32),
        "poise_ca_delay_samples": ([vp], u64),
        "poise_ca_io_latency_samples": ([vp], u64),
        "poise_ca_status": ([vp, cp, ctypes.c_size_t], ctypes.c_int),
        "poise_ca_get_stats": ([vp, ctypes.POINTER(u64), u32], None),
        "poise_ca_stat_count": ([], u32),
    })


def load_library():
    """Load libpoise_coreaudio.dylib (cached). Raises CoreAudioUnavailable."""
    global _lib
    if _lib is not None:
        return _lib
    if sys.platform != "darwin":
        raise CoreAudioUnavailable("macOS only")
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
        if lib.poise_ca_stat_count() != len(CA_STAT_NAMES):
            errors.append(f"{path}: built from other sources (stale build)")
            continue
        if lib.poise_core_stat_count() != len(STAT_NAMES):
            errors.append(f"{path}: built from other sources (stale core)")
            continue
        _lib = lib
        return lib
    detail = "; ".join(errors) or (
        f"{LIB_NAME} not found (build it: make -C native/poise_coreaudio)")
    raise CoreAudioUnavailable(detail)


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


# Every live node. A tap that outlives its reader mutes the whole Mac, so
# an exit route that never reached close() still destroys it (plan C1);
# the library registers the same net natively, for exits ctypes cannot see.
_live = set()
_live_lock = threading.Lock()


def _destroy_live_nodes() -> None:
    with _live_lock:
        nodes = list(_live)
        _live.clear()
    for node in nodes:
        try:
            node.close()
        except Exception:  # an exit route: nothing left to report to
            pass


atexit.register(_destroy_live_nodes)


class CoreAudioNode(CoreOps):
    """Every app's audio -> poise_core -> the output device, live in Core
    Audio.

    Created running, with the tap muting the apps it is read from (plan
    C1: ``tap_mute``; the shipping value). Until a worker calls
    ``wait_frame`` the output is the unprocessed input, delayed like
    processed audio would be.
    """

    def __init__(self, *, output: Optional[str], frame: int,
                 engine_latency: int, quantum: int, margin: int, fade: int,
                 dry_gain: float, rate: int = NODE_RATE, tap_mute: bool = True,
                 lib=None):
        self._lib = lib if lib is not None else load_library()
        self.frame = int(frame)
        self.engine_latency = int(engine_latency)
        # The rate the streams carry. The native node reads it back from
        # the aggregate and refuses a device it cannot give it (C2), so
        # this is the device's rate, not an assumption: it has no getter
        # of its own.
        self.rate = int(rate or NODE_RATE)
        err = ctypes.create_string_buffer(512)
        self._handle = self._lib.poise_ca_new(
            output.encode() if output else None, self.frame,
            self.engine_latency, int(quantum), int(margin), int(fade),
            float(dry_gain), self.rate, int(bool(tap_mute)), err, len(err))
        if not self._handle:
            raise CoreAudioError(
                err.value.decode(errors="replace") or "unknown error")
        self._core = self._lib.poise_ca_core(self._handle)
        with _live_lock:
            _live.add(self)

    @property
    def io_latency_samples(self) -> int:
        """Delay of the device side, from the IOProc's time stamps."""
        return int(self._lib.poise_ca_io_latency_samples(self._handle))

    @property
    def latency_samples(self) -> int:
        """Delay Poise adds from the tapped audio to the speakers' buffer:
        device side + fixed delay + the engine's own."""
        return (self.io_latency_samples + self.delay_samples
                + self.engine_latency)

    def node_stats(self) -> Dict[str, int]:
        """The node's counters: the core's own (copied natively) plus the
        device side's — overloads, the tap's capture health (C2b), the clock
        drift and time-stamp deltas (C3) and C4's restarts and tap_alive,
        which the native side answers with placeholders until T5's property
        listeners fill them in."""
        return _stats(self._lib.poise_ca_get_stats, self._handle,
                      CA_STAT_NAMES)

    def error(self) -> Optional[str]:
        err = ctypes.create_string_buffer(512)
        if self._lib.poise_ca_status(self._handle, err, len(err)):
            return err.value.decode(errors="replace") or "unknown error"
        return None

    def close(self) -> None:
        """Stop the device, destroy the IOProc, the aggregate and the tap
        (which is what unmutes the Mac).

        ``poise_ca_destroy()`` takes the handle once and is not idempotent
        (the header says so: a second call is a double free), so the handle
        is dropped here — call it as often as you like. It must not run
        while a worker is parked inside ``wait_frame``: the free path
        destroys the semaphore a parked waiter sits on, so the inference
        thread has to have returned first (plan C1).
        """
        with _live_lock:
            _live.discard(self)
        if self._handle:
            self._lib.poise_ca_destroy(self._handle)
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
