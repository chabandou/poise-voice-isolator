"""
Audio Backends Package

Contains implementations for different audio processing backends.
"""

from .pyaudio_backend import process_with_pyaudiowpatch
from .sounddevice_backend import process_with_sounddevice

__all__ = ['process_with_pyaudiowpatch', 'process_with_sounddevice']
