"""
Which audio backend the user asked for

Small and free of the audio loops (and numpy): the UI process reads the
choice before handing the session to the audio process, and loading
wasapi_backend there would pull in the whole native loop.
"""
import os
from typing import Optional

from ..constants import BACKEND_ENV, WINDOWS_BACKENDS


def windows_backend_preference(requested: Optional[str] = None) -> str:
    """The requested Windows backend: CLI value, else POISE_BACKEND, else auto."""
    value = (requested or os.environ.get(BACKEND_ENV) or "auto").strip().lower()
    if value not in WINDOWS_BACKENDS:
        raise ValueError(
            f"Unknown backend {value!r} "
            f"(choose from {', '.join(WINDOWS_BACKENDS)})")
    return value
