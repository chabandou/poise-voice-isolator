"""
Backend Detection Module

Single source of truth for audio backend availability.

Windows: sounddevice and PyAudioWPatch (WASAPI loopback).
Linux: pulse-simple via libpulse-simple (no PortAudio runtime).
"""

import sys
from typing import Optional

_IS_WIN32 = sys.platform == "win32"

# Check for sounddevice (Windows-only runtime)
SOUNDDEVICE_ERROR = None
SOUNDDEVICE_INSTALL_HINT: Optional[str] = None
if _IS_WIN32:
    try:
        import sounddevice as sd
        USE_SOUNDDEVICE = True
    except (ImportError, OSError) as e:
        sd = None
        USE_SOUNDDEVICE = False
        SOUNDDEVICE_ERROR = str(e)
else:
    sd = None
    USE_SOUNDDEVICE = False

# Check for PyAudioWPatch (Windows-only, preferred for WASAPI loopback)
USE_PYAUDIO = False
USE_PYAUDIOWPATCH = False
pyaudio = None

if _IS_WIN32:
    try:
        import pyaudiowpatch as _pyaudio
        pyaudio = _pyaudio
        USE_PYAUDIOWPATCH = True
        USE_PYAUDIO = True
    except ImportError:
        try:
            import pyaudio as _pyaudio
            pyaudio = _pyaudio
            USE_PYAUDIO = True
            USE_PYAUDIOWPATCH = False
        except ImportError:
            USE_PYAUDIO = False
            USE_PYAUDIOWPATCH = False


def get_available_backends() -> list[str]:
    """Return list of available audio backend names."""
    backends = []
    if USE_PYAUDIOWPATCH:
        backends.append("pyaudiowpatch")
    elif USE_PYAUDIO:
        backends.append("pyaudio")
    if USE_SOUNDDEVICE:
        backends.append("sounddevice")
    if sys.platform.startswith("linux"):
        backends.append("pulse-simple")
    return backends


def has_any_backend() -> bool:
    """Check if at least one audio backend is available."""
    if sys.platform.startswith("linux"):
        return True  # pulse-simple loads lazily via libpulse-simple
    return USE_PYAUDIO or USE_SOUNDDEVICE
