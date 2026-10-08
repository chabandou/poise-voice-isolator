"""
Audio Backends Package

Contains implementations for different audio processing backends.
"""

from .pyaudio_backend import process_with_pyaudiowpatch
from .sounddevice_backend import process_with_sounddevice
from .pulse_backend import process_with_pulse, run_pulse_loop

__all__ = ['process_with_pyaudiowpatch', 'process_with_sounddevice',
           'process_with_pulse', 'run_pulse_loop']
