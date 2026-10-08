"""
PulseAudio Simple API backend (Linux).

Talks to a Pulse-compatible server (PulseAudio, or PipeWire with
``pipewire-pulse``) directly via ``libpulse-simple`` using ctypes.

Fixed format: 48 kHz float32. The server handles rate and format
conversion, so there is no resampler on Linux.

Always names, never indices: capture takes a source name, playback a
sink name.
"""
import ctypes
import ctypes.util
from typing import Optional

import numpy as np

from ..logging_config import get_logger

_logger = get_logger(__name__)

# Fixed Linux sample rate (server converts as needed).
PULSE_SAMPLE_RATE = 48000

# pa_sample_format_t: float32 little-endian.
PA_SAMPLE_FLOAT32LE = 5
# pa_stream_direction_t.
PA_STREAM_PLAYBACK = 1
PA_STREAM_RECORD = 2
# "Unset" buffer-attr value (uint32)-1.
PA_ATTR_UNSET = 0xFFFFFFFF


class PulseError(OSError):
    """Runtime PulseAudio simple-API error (message from pa_strerror)."""


class PulseUnavailable(RuntimeError):
    """libpulse-simple could not be loaded."""


class pa_sample_spec(ctypes.Structure):
    _fields_ = [
        ("format", ctypes.c_int),
        ("rate", ctypes.c_uint32),
        ("channels", ctypes.c_uint8),
    ]


class pa_buffer_attr(ctypes.Structure):
    _fields_ = [
        ("maxlength", ctypes.c_uint32),
        ("tlength", ctypes.c_uint32),
        ("prebuf", ctypes.c_uint32),
        ("minreq", ctypes.c_uint32),
        ("fragsize", ctypes.c_uint32),
    ]


_lib = None


def _load_library():
    """Load libpulse-simple, caching the handle."""
    global _lib
    if _lib is not None:
        return _lib
    hint = (
        "Install libpulse. Arch: sudo pacman -S libpulse. "
        "Debian/Ubuntu: sudo apt install libpulse0."
    )
    candidates = []
    found = ctypes.util.find_library("pulse-simple")
    if found:
        candidates.append(found)
    candidates.append("libpulse-simple.so.0")
    last_err: Optional[Exception] = None
    for name in candidates:
        try:
            lib = ctypes.CDLL(name)
            break
        except OSError as e:
            last_err = e
            continue
    else:
        raise PulseUnavailable(
            f"Could not load libpulse-simple ({last_err}). {hint}"
        )
    # Bind signatures.
    lib.pa_simple_new.argtypes = [
        ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int,
        ctypes.c_char_p, ctypes.c_char_p,
        ctypes.POINTER(pa_sample_spec),
        ctypes.c_void_p,
        ctypes.POINTER(pa_buffer_attr),
        ctypes.POINTER(ctypes.c_int),
    ]
    lib.pa_simple_new.restype = ctypes.c_void_p
    lib.pa_simple_read.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_size_t, ctypes.POINTER(ctypes.c_int),
    ]
    lib.pa_simple_read.restype = ctypes.c_int
    lib.pa_simple_write.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_size_t, ctypes.POINTER(ctypes.c_int),
    ]
    lib.pa_simple_write.restype = ctypes.c_int
    lib.pa_simple_flush.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
    lib.pa_simple_flush.restype = ctypes.c_int
    lib.pa_simple_get_latency.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
    lib.pa_simple_get_latency.restype = ctypes.c_uint64
    lib.pa_simple_free.argtypes = [ctypes.c_void_p]
    lib.pa_simple_free.restype = None
    lib.pa_strerror.argtypes = [ctypes.c_int]
    lib.pa_strerror.restype = ctypes.c_char_p
    _lib = lib
    return lib


def _strerror(lib, code: int) -> str:
    try:
        msg = lib.pa_strerror(code)
        if msg:
            return msg.decode("utf-8", errors="replace")
    except Exception:
        pass
    return f"PulseAudio error {code}"


class _PulseStreamBase:
    """Shared lifecycle: idempotent close() + context manager + latency."""

    def __init__(self):
        self._lib = None
        self._handle: Optional[int] = None
        self._closed = False

    def _raise(self, code: int, op: str) -> None:
        raise PulseError(f"{op} failed: {_strerror(self._lib, code)}")

    def latency_ms(self) -> float:
        """Current stream latency in milliseconds (-1 if unknown)."""
        if not self._handle or self._closed:
            return -1.0
        err = ctypes.c_int(0)
        usec = self._lib.pa_simple_get_latency(
            ctypes.c_void_p(self._handle), ctypes.byref(err))
        if err.value != 0:
            return -1.0
        return float(usec) / 1000.0

    def close(self) -> None:
        """Idempotent close. Flushes (never blocking drain) then frees."""
        if self._closed or not self._handle:
            self._closed = True
            return
        try:
            err = ctypes.c_int(0)
            # Flush discards buffered audio without blocking, unlike drain.
            self._lib.pa_simple_flush(
                ctypes.c_void_p(self._handle), ctypes.byref(err))
        except Exception:
            pass
        try:
            self._lib.pa_simple_free(ctypes.c_void_p(self._handle))
        except Exception:
            pass
        self._handle = None
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def __del__(self):  # best effort; streams are closed explicitly
        try:
            self.close()
        except Exception:
            pass


class PulseCapture(_PulseStreamBase):
    """Blocking PulseAudio capture stream.

    ``read()`` returns ``(n, 1)`` float32 C-contiguous audio plus
    ``overflowed=False`` (the simple API has no overrun indicator),
    matching the sounddevice mono contract the app already uses.

    Stereo is captured and downmixed in numpy as (L+R)/2 for level
    parity with the previous path; server-side remix is not relied on.
    """

    def __init__(self, source: str, frames: int,
                 sample_rate: int = PULSE_SAMPLE_RATE,
                 channels: int = 2,
                 stream_name: str = "poise-capture",
                 app_name: str = "poise"):
        super().__init__()
        if frames <= 0:
            raise ValueError("frames must be > 0")
        if channels not in (1, 2):
            raise ValueError("channels must be 1 or 2")
        lib = _load_library()
        self._lib = lib
        self.source = source
        self.frames = int(frames)
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        ss = pa_sample_spec(PA_SAMPLE_FLOAT32LE, self.sample_rate,
                            self.channels)
        # Starting values from the prototype: fragsize = 1 block.
        block_bytes = self.frames * self.channels * 4
        attr = pa_buffer_attr(
            PA_ATTR_UNSET, PA_ATTR_UNSET, PA_ATTR_UNSET,
            PA_ATTR_UNSET, block_bytes,
        )
        err = ctypes.c_int(0)
        handle = lib.pa_simple_new(
            None, app_name.encode("utf-8"), PA_STREAM_RECORD,
            source.encode("utf-8"), stream_name.encode("utf-8"),
            ctypes.byref(ss), None, ctypes.byref(attr),
            ctypes.byref(err),
        )
        if not handle:
            self._raise(err.value, f"pa_simple_new(record {source!r})")
        self._handle = handle
        # Preallocated staging buffer; no per-sample Python loops.
        self._buf = np.empty(self.frames * self.channels, dtype=np.float32)
        _logger.debug("PulseCapture opened: source=%s frames=%s ch=%s",
                      source, self.frames, self.channels)

    def read(self, n: Optional[int] = None):
        """Read one block. Returns (audio, overflowed).

        ``audio`` is a ``(frames, 1)`` float32 C-contiguous array.
        ``overflowed`` is always False (pa_simple cannot report overruns).
        """
        want = self.frames if n is None else int(n)
        if want != self.frames:
            raise ValueError(
                f"PulseCapture reads fixed blocks of {self.frames} "
                f"(got {want})")
        err = ctypes.c_int(0)
        nbytes = self._buf.nbytes
        rc = self._lib.pa_simple_read(
            ctypes.c_void_p(self._handle),
            self._buf.ctypes.data_as(ctypes.c_void_p),
            nbytes, ctypes.byref(err),
        )
        if rc < 0:
            self._raise(err.value, "pa_simple_read")
        if self.channels == 2:
            stereo = self._buf.reshape(self.frames, 2)
            mono = np.empty((self.frames, 1), dtype=np.float32)
            # (L+R)/2 downmix, vectorised.
            np.mean(stereo, axis=1, out=mono[:, 0])
        else:
            mono = self._buf.reshape(self.frames, 1).copy()
        return np.ascontiguousarray(mono, dtype=np.float32), False


class PulsePlayback(_PulseStreamBase):
    """Blocking PulseAudio playback stream."""

    def __init__(self, sink: str, frames: int,
                 sample_rate: int = PULSE_SAMPLE_RATE,
                 channels: int = 2,
                 stream_name: str = "poise-playback",
                 app_name: str = "poise"):
        super().__init__()
        if frames <= 0:
            raise ValueError("frames must be > 0")
        if channels not in (1, 2):
            raise ValueError("channels must be 1 or 2")
        lib = _load_library()
        self._lib = lib
        self.sink = sink
        self.frames = int(frames)
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        ss = pa_sample_spec(PA_SAMPLE_FLOAT32LE, self.sample_rate,
                            self.channels)
        # Starting values from the prototype: tlength = 3 blocks,
        # prebuf = 1 block.
        block_bytes = self.frames * self.channels * 4
        attr = pa_buffer_attr(
            PA_ATTR_UNSET, 3 * block_bytes, 1 * block_bytes,
            PA_ATTR_UNSET, PA_ATTR_UNSET,
        )
        err = ctypes.c_int(0)
        handle = lib.pa_simple_new(
            None, app_name.encode("utf-8"), PA_STREAM_PLAYBACK,
            sink.encode("utf-8"), stream_name.encode("utf-8"),
            ctypes.byref(ss), None, ctypes.byref(attr),
            ctypes.byref(err),
        )
        if not handle:
            self._raise(err.value, f"pa_simple_new(playback {sink!r})")
        self._handle = handle
        _logger.debug("PulsePlayback opened: sink=%s frames=%s ch=%s",
                      sink, self.frames, self.channels)

    def write(self, arr: np.ndarray) -> None:
        """Write one block of interleaved float32 audio."""
        data = np.ascontiguousarray(arr, dtype=np.float32)
        if data.ndim == 1:
            # Mono vector -> duplicate to stereo when needed.
            if self.channels == 2:
                data = np.column_stack([data, data])
            else:
                data = data.reshape(-1, 1)
        elif data.ndim == 2 and data.shape[1] == 1 and self.channels == 2:
            data = np.column_stack([data[:, 0], data[:, 0]])
        expected = self.frames * self.channels
        if data.size != expected:
            raise ValueError(
                f"PulsePlayback.write expects {expected} samples "
                f"({self.frames}x{self.channels}), got {data.size}")
        data = np.ascontiguousarray(data.reshape(-1), dtype=np.float32)
        err = ctypes.c_int(0)
        rc = self._lib.pa_simple_write(
            ctypes.c_void_p(self._handle),
            data.ctypes.data_as(ctypes.c_void_p),
            data.nbytes, ctypes.byref(err),
        )
        if rc < 0:
            self._raise(err.value, "pa_simple_write")
