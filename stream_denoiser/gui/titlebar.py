"""
Poise Voice Isolator - Themed Windows title bar

Paints the native Windows title bar to match the current theme, keeping
the real system frame (snap layouts, Aero shake, min/max/close, drag
behaviour all stay native).

- Windows 11 (build 22000+): caption, caption text and window border take
  exact theme colours via DwmSetWindowAttribute.
- Windows 10 (1809+): custom caption colours are not supported, so the
  title bar is switched to the system dark style instead of staying white.
- Elsewhere: no-op.

Every call is best-effort: any failure leaves the default title bar.
"""
import sys

# DWM window attributes (dwmapi.h).
DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19   # Windows 10 1809 - 1909
DWMWA_USE_IMMERSIVE_DARK_MODE = 20       # Windows 10 2004+ / 11
DWMWA_BORDER_COLOR = 34                  # Windows 11 22000+
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36

WIN11_BUILD = 22000

# Palette keys used for the frame. The caption uses the sidebar colour so
# the title bar, sidebar and status bar read as one frame around the page.
CAPTION_KEY = "sidebar"
TEXT_KEY = "text"
BORDER_KEY = "sidebar"


def colorref(hex_color: str) -> int:
    """'#RRGGBB' -> Win32 COLORREF (0x00BBGGRR)."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (b << 16) | (g << 8) | r


def windows_build() -> int:
    """Windows build number (0 when not on Windows or unknown)."""
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
    return result == 0   # S_OK


def apply_titlebar(widget, palette: dict) -> bool:
    """Theme `widget`'s native title bar. Returns True if anything applied."""
    build = windows_build()
    if not build:
        return False
    try:
        hwnd = int(widget.winId())
        # Dark mode first: it also keeps the min/max/close glyphs light on
        # Windows 11, and is the whole effect on Windows 10.
        ok = _set_attr(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1)
        if not ok:
            ok = _set_attr(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE_OLD, 1)
        if build >= WIN11_BUILD:
            ok = _set_attr(hwnd, DWMWA_CAPTION_COLOR,
                           colorref(palette[CAPTION_KEY])) or ok
            ok = _set_attr(hwnd, DWMWA_TEXT_COLOR,
                           colorref(palette[TEXT_KEY])) or ok
            ok = _set_attr(hwnd, DWMWA_BORDER_COLOR,
                           colorref(palette[BORDER_KEY])) or ok
        return ok
    except Exception:
        return False
