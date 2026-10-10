"""Backend Detection Module

Single source of truth for audio backend availability.
sounddevice (PortAudio) is the only audio backend. CABLE Output is
opened as a regular WASAPI capture device — no WASAPI-loopback
extension (PyAudioWPatch) required.
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

def get_available_backends() -> list[str]:
    """Return list of available audio backend names."""
    backends = []
    if USE_SOUNDDEVICE:
        backends.append("sounddevice")
    return backends


def has_any_backend() -> bool:
    """Check if at least one audio backend is available."""
    return USE_SOUNDDEVICE
