"""
Poise Setup - frameless window chrome.

The setup window draws its own frame (no title bar, no controls), so this
asks DWM for the two things a borderless window still wants: round corners
on Windows 11 and the standard drop shadow. Everything is best effort -
any failure just leaves a plain borderless window.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMWCP_ROUND = 2
WIN11_BUILD = 22000

#: The hairline DWM draws around the frame, matched to the rail.
FRAME_COLOR = "#16233a"


class _Margins(ctypes.Structure):
    _fields_ = [
        ("cxLeftWidth", ctypes.c_int),
        ("cxRightWidth", ctypes.c_int),
        ("cyTopHeight", ctypes.c_int),
        ("cyBottomHeight", ctypes.c_int),
    ]


def colorref(hex_color: str) -> int:
    """'#RRGGBB' -> Win32 COLORREF (0x00BBGGRR)."""
    value = hex_color.lstrip("#")
    red, green, blue = (int(value[0:2], 16), int(value[2:4], 16),
                        int(value[4:6], 16))
    return (blue << 16) | (green << 8) | red


def _set_attr(hwnd: int, attr: int, value: int) -> bool:
    data = wintypes.DWORD(value)
    result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
        wintypes.HWND(hwnd), wintypes.DWORD(attr),
        ctypes.byref(data), ctypes.sizeof(data))
    return result == 0


def _extend_frame(hwnd: int) -> bool:
    """One-pixel frame: what gives a borderless window its shadow."""
    margins = _Margins(1, 1, 1, 1)
    result = ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(
        wintypes.HWND(hwnd), ctypes.byref(margins))
    return result == 0


def windows_build() -> int:
    if sys.platform != "win32":
        return 0
    try:
        return int(sys.getwindowsversion().build)
    except Exception:
        return 0


def apply_window_chrome(widget) -> None:
    """Dark, rounded, shadowed - as far as the OS allows."""
    if sys.platform != "win32":
        return
    try:
        hwnd = int(widget.winId())
    except Exception:
        return
    try:
        _set_attr(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1)
        if windows_build() >= WIN11_BUILD:
            _set_attr(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND)
            _set_attr(hwnd, DWMWA_BORDER_COLOR, colorref(FRAME_COLOR))
            # Windows 10 has no border colour to match, and its extended
            # frame shows up as a light hairline: only ask for the shadow
            # where it can be tinted.
            _extend_frame(hwnd)
    except Exception:
        pass
