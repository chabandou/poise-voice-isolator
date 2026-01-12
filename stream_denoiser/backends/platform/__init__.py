"""
Platform-specific audio backends.

This package contains platform-specific audio implementations:
- windows.py: WASAPI loopback, VB Cable switching (Windows only)
- linux.py: PulseAudio/ALSA monitor sources (Linux only)

These modules are excluded at build time via PyInstaller spec files
for cross-platform builds.
"""
