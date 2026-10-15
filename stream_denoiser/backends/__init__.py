"""
Audio Backends Package

Contains implementations for different audio processing backends.
"""

from .sounddevice_backend import run_portaudio_loop
from .pulse_backend import run_pulse_loop

__all__ = ['run_portaudio_loop', 'run_pulse_loop']
