"""
RNNoise library loading

Finds and loads librnnoise (Linux) or the vendored rnnoise.dll (Windows)
through ctypes. Kept apart from the engine (and numpy) so the UI can ask
whether RNNoise runs here without loading the audio code.
"""
import ctypes
import ctypes.util
import os
import sys
from typing import List, Optional

from ..constants import (
    MSG_RNNOISE_NOT_FOUND,
    MSG_RNNOISE_WINDOWS_NOT_FOUND,
    MSG_RNNOISE_LINUX_ONLY,
)

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
