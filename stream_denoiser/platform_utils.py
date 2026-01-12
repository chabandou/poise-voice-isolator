"""
Platform Utilities

Runtime platform detection and safe imports for platform-specific modules.
In dev mode, all code is present but unused paths are not executed.
In build mode, PyInstaller excludes platform-specific modules via spec files.
"""
import sys
from typing import Optional, Type

def is_windows() -> bool:
    """Check if running on Windows."""
    return sys.platform == 'win32'

def is_linux() -> bool:
    """Check if running on Linux."""
    return sys.platform.startswith('linux')

def is_macos() -> bool:
    """Check if running on macOS."""
    return sys.platform == 'darwin'


def get_vb_cable_switcher() -> Optional[Type]:
    """
    Safely import VBCableSwitcher class.
    Returns None on non-Windows platforms or if module unavailable.
    """
    if not is_windows():
        return None
    try:
        from .backends.platform.windows import VBCableSwitcher
        return VBCableSwitcher
    except ImportError:
        # Fallback to old location during migration
        try:
            from .vb_cable import VB_CableSwitcher
            return VB_CableSwitcher
        except ImportError:
            return None


def get_linux_audio_router() -> Optional[Type]:
    """
    Safely import LinuxAudioRouter class.
    Returns None on non-Linux platforms or if module unavailable.
    """
    if not is_linux():
        return None
    try:
        from .backends.platform.linux import LinuxAudioRouter
        return LinuxAudioRouter
    except ImportError:
        return None


def get_preferred_host_apis() -> list[str]:
    """
    Get list of preferred host API names for the current platform.
    Used for filtering audio devices.
    """
    if is_windows():
        return ['WASAPI', 'Windows WASAPI']
    elif is_linux():
        return ['ALSA', 'PulseAudio', 'JACK Audio Connection Kit', 'PipeWire']
    elif is_macos():
        return ['Core Audio']
    else:
        return []  # Accept all


def is_acceptable_host_api(host_api_name: str) -> bool:
    """
    Check if a host API is acceptable for the current platform.
    Returns True if no filtering needed (empty preferred list).
    """
    preferred = get_preferred_host_apis()
    if not preferred:
        return True
    return any(pref.lower() in host_api_name.lower() for pref in preferred)
