"""
Poise Voice Isolator - OS cursor theme bootstrap.

Qt resolves link/hand cursors from the system cursor theme, but on
X11/XWayland that only works when XCURSOR_THEME names an installed
theme. When it is unset Qt falls back to its built-in bitmaps (the ugly
hand). Hyprland setups commonly export XCURSOR_SIZE but no
XCURSOR_THEME, which is exactly the fallback-glyph situation.

cursor_env_fixes()/ensure_cursor_env() fill the missing pieces without
ever overriding explicit user env, and must run before QApplication is
constructed (see gui/__init__.run_gui).

apply_link_cursor() picks the working mechanism per platform (verified
against the live compositor):

- native Wayland: plain Qt.PointingHandCursor. The compositor draws the
  named "pointer" shape from its own theme (correct Adwaita hand);
  client pixmap uploads misbehave there (hollow ghost).
- xcb/XWayland (this app's conda Qt ships no Wayland plugin and no
  XCursor support — libXcursor is never even loaded): upload the theme
  pixels as a pixmap cursor via XFixes, which is rock solid there.
  Falls back to the named cursor if anything fails.

Pure stdlib at module level on purpose (like gui/scaling.py) so the
parsing and selection stay unit-testable without Qt; Qt is only ever
touched through lazy imports inside functions.
"""
import os
import shutil
import struct
import subprocess

FALLBACK_THEME = "Adwaita"
FALLBACK_SIZE = "24"

#: Cursor names tried in order for the "link select" (hand) cursor.
LINK_NAMES = ("hand2", "pointer", "hand1", "link")

_XCUR_MAGIC = 0x72756358
_XCUR_IMAGE_TYPE = 0xFFFD0002

_GSETTINGS_SCHEMA = "org.gnome.desktop.interface"
_GSETTINGS_KEY = "cursor-theme"


def _theme_installed(name: str, home: str | None = None) -> bool:
    """True when a cursor theme ships a non-empty cursors/ directory."""
    if not name or "/" in name or name.startswith("."):
        return False
    if home is None:
        home = os.path.expanduser("~")
    candidates = (
        os.path.join(home, ".icons", name, "cursors"),
        os.path.join(home, ".local", "share", "icons", name, "cursors"),
        os.path.join("/usr", "share", "icons", name, "cursors"),
    )
    for directory in candidates:
        try:
            if os.path.isdir(directory) and os.listdir(directory):
                return True
        except OSError:
            continue
    return False


def _gsettings_theme() -> str | None:
    """Desktop cursor theme via gsettings, if the tool + key exist."""
    if shutil.which("gsettings") is None:
        return None
    try:
        out = subprocess.run(
            ["gsettings", "get", _GSETTINGS_SCHEMA, _GSETTINGS_KEY],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return None
    if out.returncode != 0:
        return None
    value = out.stdout.strip().strip("'\"")
    return value or None


def cursor_env_fixes(env=None) -> dict:
    """Env vars the app should set for OS-themed cursors (missing only).

    Never overrides explicit user configuration: anything already
    present in env is left alone.
    """
    env = os.environ if env is None else env
    fixes: dict = {}

    theme = (env.get("XCURSOR_THEME") or "").strip()
    if not theme:
        candidate = _gsettings_theme()
        if candidate and candidate != "default" \
                and _theme_installed(candidate):
            fixes["XCURSOR_THEME"] = candidate
        elif _theme_installed(FALLBACK_THEME):
            fixes["XCURSOR_THEME"] = FALLBACK_THEME

    if not (env.get("XCURSOR_SIZE") or "").strip():
        fixes["XCURSOR_SIZE"] = FALLBACK_SIZE

    return fixes


def ensure_cursor_env() -> dict:
    """Apply cursor_env_fixes() to os.environ. Returns what was set."""
    fixes = cursor_env_fixes()
    for key, value in fixes.items():
        os.environ.setdefault(key, value)
    return fixes


# -- XCursor parsing (theme pixels for the xcb path) --------------------------
def parse_xcursor(data: bytes, size: int):
    """Parse an XCursor file, returning (w, h, xhot, yhot, pixels|None).

    pixels is raw premultiplied ARGB32 bytes (w*h*4), matching QImage
    Format_ARGB32_Premultiplied. Picks the exact nominal size when
    present, else the smallest size >= requested, else the largest.
    Returns None for garbage/short/empty input. Pure stdlib.
    """
    try:
        if not data or len(data) < 16:
            return None
        magic, _hlen, _ver, ntoc = struct.unpack("<4I", data[:16])
        if magic != _XCUR_MAGIC or ntoc <= 0 or ntoc > 64:
            return None
        best = None  # (subtype, pos)
        larger = None  # smallest subtype >= size
        largest = None  # biggest subtype overall (fallback)
        for i in range(ntoc):
            off = 16 + i * 12
            typ, subtype, pos = struct.unpack("<3I", data[off:off + 12])
            if typ != _XCUR_IMAGE_TYPE or subtype <= 0:
                continue
            if pos + 36 > len(data):
                continue
            if subtype == size:
                best = (subtype, pos)
                break
            if subtype > size and (larger is None or subtype < larger[0]):
                larger = (subtype, pos)
            if largest is None or subtype > largest[0]:
                largest = (subtype, pos)
        if best is None:
            best = larger if larger is not None else largest
        if best is None:
            return None
        _subtype, pos = best
        (_hlen2, _typ2, _sub2, _ver2, width, height, xhot, yhot,
         _delay) = struct.unpack("<9I", data[pos:pos + 36])
        if width <= 0 or height <= 0 or width > 256 or height > 256:
            return None
        if xhot < 0 or yhot < 0 or xhot >= width or yhot >= height:
            return None
        need = width * height * 4
        pixels = data[pos + 36:pos + 36 + need]
        if len(pixels) != need:
            return None
        return (width, height, xhot, yhot, pixels)
    except Exception:
        return None


def theme_cursor_path(name: str, theme: str,
                      home: str | None = None) -> str | None:
    """Filesystem path of a cursor file inside a theme (follows symlinks)."""
    if home is None:
        home = os.path.expanduser("~")
    for directory in (
            os.path.join(home, ".icons", theme, "cursors"),
            os.path.join(home, ".local", "share", "icons",
                         theme, "cursors"),
            os.path.join("/usr", "share", "icons", theme, "cursors")):
        path = os.path.join(directory, name)
        try:
            if os.path.isfile(path):
                return path
        except OSError:
            continue
    return None


def active_theme(env=None) -> str | None:
    """Cursor theme name the app should draw from (env, then desktop)."""
    env = os.environ if env is None else env
    theme = (env.get("XCURSOR_THEME") or "").strip()
    if theme and _theme_installed(theme):
        return theme
    candidate = _gsettings_theme()
    if candidate and candidate != "default" and _theme_installed(candidate):
        return candidate
    if _theme_installed(FALLBACK_THEME):
        return FALLBACK_THEME
    return None


def find_theme_cursor(names=LINK_NAMES, size: int = 24,
                      env=None, home: str | None = None):
    """Parse the link cursor from the active theme.

    Returns (theme, width, height, xhot, yhot, pixels) or None.
    """
    theme = active_theme(env)
    if theme is None:
        return None
    try:
        size = int(size)
    except (TypeError, ValueError):
        size = 24
    for name in names:
        path = theme_cursor_path(name, theme, home)
        if path is None:
            continue
        try:
            with open(path, "rb") as f:
                parsed = parse_xcursor(f.read(), size)
        except OSError:
            continue
        if parsed is not None:
            width, height, xhot, yhot, pixels = parsed
            return (theme, width, height, xhot, yhot, pixels)
    return None


_CURSORS: dict = {}


def make_link_cursor():
    """QCursor with the OS theme's link pixels (cached, xcb path).

    Falls back to Qt's PointingHandCursor when the theme is missing or
    unparsable. Lazy Qt import keeps this module importable without Qt.
    """
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QCursor, QImage, QPixmap

    size = 24
    try:
        size = int((os.environ.get("XCURSOR_SIZE") or "24").strip() or "24")
    except ValueError:
        size = 24
    theme = active_theme()
    key = (theme, size)
    if key in _CURSORS:
        return _CURSORS[key][0]
    try:
        found = find_theme_cursor(size=size)
        if found is None:
            raise ValueError("no theme cursor")
        _theme, w, h, xhot, yhot, pixels = found
        # QImage(uchar*, ...) does NOT copy the buffer, and QPixmap
        # conversion may not fully detach on every platform — keep the
        # bytes AND the image alive in the cache for the app lifetime
        # (a stack-local buffer once rendered rainbow static).
        raw = bytes(pixels)
        image = QImage(raw, w, h, w * 4,
                       QImage.Format.Format_ARGB32_Premultiplied)
        if image.isNull():
            raise ValueError("bad cursor image")
        pixmap = QPixmap.fromImage(image)
        if pixmap.isNull():
            raise ValueError("bad cursor pixmap")
        cursor = QCursor(pixmap, xhot, yhot)
        _CURSORS[key] = (cursor, raw, image)
    except Exception:
        cursor = QCursor(Qt.CursorShape.PointingHandCursor)
        _CURSORS[key] = (cursor, None, None)
    return cursor


def prefer_named_cursor(platform_name) -> bool:
    """True when the platform draws named cursor shapes correctly itself.

    Native Wayland: the compositor renders the "pointer" shape from its
    own theme (verified on-screen); client pixmap uploads misbehave
    there. Everywhere else (xcb/XWayland especially, where Qt may lack
    XCursor support entirely) upload theme pixels directly instead.
    Pure function so it stays unit-testable.
    """
    try:
        return (platform_name or "").strip().lower() == "wayland"
    except Exception:
        return False


def apply_link_cursor(widget) -> None:
    """Give a clickable widget the working link cursor (never raises)."""
    try:
        from PyQt6.QtCore import Qt
        try:
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance()
            platform = app.platformName() if app is not None else ""
        except Exception:
            platform = ""
        if prefer_named_cursor(platform):
            widget.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            widget.setCursor(make_link_cursor())
    except Exception:
        try:
            from PyQt6.QtCore import Qt
            widget.setCursor(Qt.CursorShape.PointingHandCursor)
        except Exception:
            pass
