"""Backend Detection Module

Single source of truth for audio backend availability.

Windows: sounddevice (PortAudio) only. CABLE Output is opened as a
regular WASAPI capture device — no WASAPI-loopback extension
(PyAudioWPatch) required.
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
