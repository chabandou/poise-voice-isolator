"""
Stream Denoiser Package

Real-time audio denoising using ONNX model inference with support for
WASAPI loopback capture, Audio Activity detection, and VB Cable switching.

Features:
- Direct time-domain processing (no STFT/ISTFT)
- Engine-native frames at 48kHz (deepfilternet3: 512 samples / 10.67ms)
- Audio Activity detection (AAD) for 2-3x performance boost
- Streaming state management for continuous processing
"""

import importlib
import os
import re

_DIST_NAME = "poise-voice-isolator"


def _read_version() -> str:
    """The version from pyproject.toml, the only place it is written.

    A pyproject.toml next to the package (source checkout; frozen builds
    bundle it at the payload root) wins over installed metadata, which
    goes stale in editable installs until they are reinstalled. Wheels
    carry no pyproject.toml, so they fall through to their metadata.
    """
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "pyproject.toml")
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        text = ""
    # The [project] table only, and only if it is ours
    project = re.search(r"^\[project\]\s*$(.*?)(?=^\[|\Z)", text, re.M | re.S)
    if project:
        body = project.group(1)
        name = re.search(r'^name\s*=\s*"([^"]+)"', body, re.M)
        ver = re.search(r'^version\s*=\s*"([^"]+)"', body, re.M)
        if name and ver and name.group(1) == _DIST_NAME:
            return ver.group(1)
    try:
        from importlib.metadata import PackageNotFoundError, version
        return version(_DIST_NAME)
    except PackageNotFoundError:
        return "0+unknown"


__version__ = _read_version()

# Public names, resolved on first access. Importing the package must stay
# cheap: the audio process (audio_host, started with spawn) re-imports it,
# and eager imports here used to pull sounddevice, the CLI and the whole
# PyQt6 GUI into that process.
_LAZY = {
    "DEFAULT_SAMPLE_RATE": ".constants",
    "DEFAULT_FRAME_SIZE": ".constants",
    "DEFAULT_AAD_THRESHOLD_DB": ".constants",
    "AudioActivityDetector": ".aad",
    "StreamingResampler": ".resampler",
    "DenoiserAudioProcessor": ".processor",
    "VB_CableSwitcher": ".backends.platform.windows",
    "list_audio_devices": ".device_utils",
    "find_loopback_device": ".device_utils",
    "get_output_device_id": ".device_utils",
    "validate_output_device": ".device_utils",
    "process_system_audio_realtime": ".cli",
    "main": ".cli",
    "run_gui": ".gui",
}


def __getattr__(name):
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    try:
        value = getattr(importlib.import_module(module, __name__), name)
    except ImportError:
        # GUI is optional - None when PyQt6 is not installed
        if name != "run_gui":
            raise
        value = None
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(_LAZY))


__all__ = [
    # Constants
    "DEFAULT_SAMPLE_RATE",
    "DEFAULT_FRAME_SIZE",
    "DEFAULT_AAD_THRESHOLD_DB",
    # Classes
    "AudioActivityDetector",
    "StreamingResampler",
    "DenoiserAudioProcessor",
    "VB_CableSwitcher",
    # Functions
    "list_audio_devices",
    "find_loopback_device",
    "get_output_device_id",
    "validate_output_device",
    "process_system_audio_realtime",
    "main",
    "run_gui",
]

