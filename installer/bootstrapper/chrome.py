"""
Poise Setup - native window chrome.

A trimmed mirror of stream_denoiser/gui/titlebar.py: the setup window
keeps the real system frame (drag, snap, close) and only recolours it, so
a dark installer never opens with a white title bar. Best effort
everywhere - any failure simply leaves the default frame.
"""
from __future__ import annotations

import sys

from . import brand

DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36

WIN11_BUILD = 22000


def colorref(hex_color: str) -> int:
    """'#RRGGBB' -> Win32 COLORREF (0x00BBGGRR)."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (b << 16) | (g << 8) | r


def windows_build() -> int:
    if sys.platform != "win32":
        return 0
    try:
        return int(sys.getwindowsversion().build)
    except Exception:
        return 0


def _set_attr(hwnd: int, attr: int, value: int) -> bool:
    import ctypes
    from ctypes import wintypes
    data = wintypes.DWORD(value)
    result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
        wintypes.HWND(hwnd), wintypes.DWORD(attr),
        ctypes.byref(data), ctypes.sizeof(data))
    return result == 0


def apply_titlebar(widget, palette: dict = None) -> bool:
    """Paint `widget`'s native title bar in the brand palette."""
    palette = palette or brand.PALETTE
    build = windows_build()
    if not build:
        return False
    try:
        hwnd = int(widget.winId())
        ok = _set_attr(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1)
        if not ok:
            ok = _set_attr(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE_OLD, 1)
        if build >= WIN11_BUILD:
            ok = _set_attr(hwnd, DWMWA_CAPTION_COLOR,
                           colorref(brand.RAIL_BOTTOM)) or ok
            ok = _set_attr(hwnd, DWMWA_TEXT_COLOR,
                           colorref(palette["text"])) or ok
            ok = _set_attr(hwnd, DWMWA_BORDER_COLOR,
                           colorref(brand.RAIL_BOTTOM)) or ok
        return ok
    except Exception:
        return False
