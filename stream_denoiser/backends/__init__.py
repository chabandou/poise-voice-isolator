"""
Audio Backends Package

Contains implementations for different audio processing backends.
"""

from .sounddevice_backend import process_with_sounddevice

__all__ = ['process_with_sounddevice']
