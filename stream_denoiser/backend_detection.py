"""
Backend Detection Module

Single source of truth for audio backend availability.
Consolidates library checks duplicated across cli.py, device_utils.py, worker.py.
"""

from typing import Optional

# Check for sounddevice
SOUNDDEVICE_ERROR = None
SOUNDDEVICE_INSTALL_HINT: Optional[str] = None
try:
    import sounddevice as sd
    USE_SOUNDDEVICE = True
except (ImportError, OSError) as e:
    sd = None
    USE_SOUNDDEVICE = False
    SOUNDDEVICE_ERROR = str(e)
    if "libportaudio.so.2" in SOUNDDEVICE_ERROR and "libsndio.so.7" in SOUNDDEVICE_ERROR:
        SOUNDDEVICE_INSTALL_HINT = (
            "Install PortAudio + sndio. Arch: sudo pacman -S sndio portaudio. "
            "Debian/Ubuntu: sudo apt install libsndio7 libportaudio2."
        )

# Check for PyAudioWPatch (preferred for WASAPI loopback)
USE_PYAUDIO = False
USE_PYAUDIOWPATCH = False
pyaudio = None

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
    return backends


def has_any_backend() -> bool:
    """Check if at least one audio backend is available."""
    return USE_PYAUDIO or USE_SOUNDDEVICE
