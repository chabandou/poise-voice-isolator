"""
Which audio backend the user asked for

Small and free of the audio loops (and numpy): the UI process reads the
choice before handing the session to the audio process, and loading
wasapi_backend there would pull in the whole native loop.
"""
import os
from typing import Optional

from ..constants import BACKEND_ENV, MACOS_BACKENDS, WINDOWS_BACKENDS


def macos_backend_preference(requested: Optional[str] = None) -> str:
    """The requested macOS backend: CLI value, else POISE_BACKEND, else auto.

    "auto" is the Core Audio tap: macOS has no second audio path to choose
    between (no PortAudio capture of the system's own audio), so the value
    is resolved and checked in one place, as on Windows.
    """
    value = (requested or os.environ.get(BACKEND_ENV) or "auto").strip().lower()
    if value not in MACOS_BACKENDS:
        raise ValueError(
            f"Unknown backend {value!r} "
            f"(choose from {', '.join(MACOS_BACKENDS)})")
    return value


def windows_backend_preference(requested: Optional[str] = None) -> str:
    """The requested Windows backend: CLI value, else POISE_BACKEND, else auto."""
    value = (requested or os.environ.get(BACKEND_ENV) or "auto").strip().lower()
    if value not in WINDOWS_BACKENDS:
        raise ValueError(
            f"Unknown backend {value!r} "
            f"(choose from {', '.join(WINDOWS_BACKENDS)})")
    return value
