"""
RNNoise Engine

Real-time noise suppression using the xiph/rnnoise library (the same model
EasyEffects uses), loaded from the system's librnnoise through ctypes on
Linux, or from the vendored rnnoise.dll bundled next to the app on Windows.

RNNoise works on 480-sample frames at 48 kHz (mono) and expects float samples
in the 16-bit range, so frames are scaled in and out of [-1.0, 1.0] here.
The library is loaded lazily, never at import time.
"""
import ctypes
import ctypes.util
import os
import sys
from typing import List, Optional

import numpy as np

from .base import DenoiseEngine
from ..constants import (
    MODEL_RNNOISE,
    RNNOISE_SCALE,
    MSG_RNNOISE_NOT_FOUND,
    MSG_RNNOISE_WINDOWS_NOT_FOUND,
    MSG_RNNOISE_LINUX_ONLY,
)
from ..logging_config import get_logger

_logger = get_logger(__name__)

_lib: Optional[ctypes.CDLL] = None

#: File name of the vendored Windows build (see build-rnnoise-dll.sh).
WINDOWS_DLL_NAME = "rnnoise.dll"


def _windows_dll_candidates() -> List[str]:
    """Where to look for the vendored rnnoise.dll on Windows.

    Order matters: next to the frozen executable first (PyInstaller
    one-dir layout), then the one-file extraction dir, then the dev
    checkout (stream_denoiser/native/), then plain PATH lookup.
    """
    candidates = []
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        candidates.append(os.path.join(exe_dir, WINDOWS_DLL_NAME))
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(os.path.join(meipass, WINDOWS_DLL_NAME))
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(
        os.path.normpath(os.path.join(here, "..", "native", WINDOWS_DLL_NAME))
    )
    candidates.append(WINDOWS_DLL_NAME)
    return candidates


def _load_library() -> ctypes.CDLL:
    """Load and configure librnnoise (cached after the first success)."""
    global _lib
    if _lib is not None:
        return _lib

    if sys.platform.startswith("linux"):
        candidates = ["librnnoise.so.0", "librnnoise.so"]
        found = ctypes.util.find_library("rnnoise")
        if found and found not in candidates:
            candidates.append(found)
    elif sys.platform == "win32":
        candidates = _windows_dll_candidates()
    else:
        raise RuntimeError(MSG_RNNOISE_LINUX_ONLY)

    lib = None
    last_error: Optional[Exception] = None
    for candidate in candidates:
        try:
            lib = ctypes.CDLL(candidate)
            break
        except OSError as e:
            last_error = e
    if lib is None:
        if sys.platform == "win32":
            raise RuntimeError(
                MSG_RNNOISE_WINDOWS_NOT_FOUND.format(last_error))
        raise RuntimeError(MSG_RNNOISE_NOT_FOUND.format(last_error))

    lib.rnnoise_get_frame_size.restype = ctypes.c_int
    lib.rnnoise_get_frame_size.argtypes = []
    lib.rnnoise_create.restype = ctypes.c_void_p
    lib.rnnoise_create.argtypes = [ctypes.c_void_p]
    lib.rnnoise_destroy.restype = None
    lib.rnnoise_destroy.argtypes = [ctypes.c_void_p]
    lib.rnnoise_process_frame.restype = ctypes.c_float
    lib.rnnoise_process_frame.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_float),
        ctypes.POINTER(ctypes.c_float),
    ]

    _lib = lib
    return _lib


class RNNoiseEngine(DenoiseEngine):
    """RNNoise denoiser (built-in model) via librnnoise."""

    name = MODEL_RNNOISE

    def __init__(self, atten_lim_db: float = -60.0):
        """
        Args:
            atten_lim_db: Emulated attenuation limit in dB. RNNoise has no such
                parameter, so a fraction of the dry input is mixed back in:
                y = (1 - f) * wet + f * dry, with f = 10 ** (atten_lim_db / 20).
                This approximates, but does not exactly match, DeepFilterNet's
                behaviour.
        """
        self._lib = _load_library()
        self.required_frame_size = int(self._lib.rnnoise_get_frame_size())
        self.atten_lim_db = atten_lim_db
        self._dry_mix = float(10.0 ** (atten_lim_db / 20.0))
        self.speech_prob = 0.0

        n = self.required_frame_size
        self._in = np.zeros(n, dtype=np.float32)
        self._out = np.zeros(n, dtype=np.float32)
        self._in_ptr = self._in.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
        self._out_ptr = self._out.ctypes.data_as(ctypes.POINTER(ctypes.c_float))

        self._state = None
        self._create_state()
        _logger.info(f"RNNoise engine ready (frame size: {n})")

    @classmethod
    def is_available(cls) -> bool:
        """True if librnnoise can be loaded on this machine."""
        try:
            _load_library()
            return True
        except RuntimeError:
            return False

    def _create_state(self) -> None:
        state = self._lib.rnnoise_create(None)  # None = built-in model
        if not state:
            raise RuntimeError("rnnoise_create() failed")
        self._state = state

    def _destroy_state(self) -> None:
        if self._state:
            self._lib.rnnoise_destroy(self._state)
            self._state = None

    def process_frame(self, frame: np.ndarray) -> np.ndarray:
        n = self.required_frame_size
        if frame.shape[0] != n:
            raise ValueError(f"RNNoise requires {n}-sample frames, got {frame.shape[0]}")

        np.multiply(frame, RNNOISE_SCALE, out=self._in, casting='same_kind')
        self.speech_prob = float(
            self._lib.rnnoise_process_frame(self._state, self._out_ptr, self._in_ptr)
        )
        wet = self._out / RNNOISE_SCALE

        if self._dry_mix > 0.0:
            wet = (1.0 - self._dry_mix) * wet + self._dry_mix * frame
        return wet.astype(np.float32, copy=False)

    def reset(self) -> None:
        self._destroy_state()
        self._create_state()
        self.speech_prob = 0.0

    def close(self) -> None:
        self._destroy_state()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
