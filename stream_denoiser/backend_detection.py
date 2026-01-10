"""
Backend Detection Module

Single source of truth for audio backend availability.
Consolidates library checks duplicated across cli.py, device_utils.py, worker.py.
"""

# Check for sounddevice
try:
    import sounddevice as sd
    USE_SOUNDDEVICE = True
except ImportError:
    sd = None
    USE_SOUNDDEVICE = False

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
