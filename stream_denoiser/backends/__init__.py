"""
Audio Backends Package

Contains implementations for different audio processing backends.
"""

import importlib

# Public names, resolved on first access. Importing any backend module
# imports this package first, and eager imports here loaded the PortAudio
# loop (sounddevice, the processor) into the PipeWire audio process,
# which never runs it.
_LAZY = {
    "run_portaudio_loop": ".sounddevice_backend",
    "run_pulse_loop": ".pulse_backend",
}


def __getattr__(name):
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module, __name__), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(_LAZY))


__all__ = ['run_portaudio_loop', 'run_pulse_loop']
