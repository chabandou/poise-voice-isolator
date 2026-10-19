"""
Poise Setup - brand tokens, assets and stylesheet.

Standalone on purpose. Importing stream_denoiser.gui would execute
gui/__init__.py, which imports MainWindow and drags the entire
application (audio backends, models, Qt Quick) into a 40 MB setup
window. PALETTE therefore repeats gui/themes.py's "abyss" entry verbatim;
tests/test_installer_ui.py asserts the two stay identical.

Colours that are not palette tokens (washes, hairlines, the dark ink on
an accent fill) are derived there too, so the setup window can never
drift into a palette of its own.
"""
from __future__ import annotations

import os
import re
import sys

#: gui/themes.py, THEMES["abyss"] - the signature palette.
PALETTE = {
    "label": "Abyss",
    "blurb": "Signature cyan on deep navy.",
    "bg": "#0a111e", "sidebar": "#080e18",
    "card": "#0f1828", "pill": "#111c30", "groove": "#1d2a3b",
    "text": "#f8fafc", "muted": "#8b94a3",
    "device_title": "#9aa3b2",
    "nav_active": "#a5f3fc", "nav_muted": "#9aa3b2",
    "accent": "#5fd5eb", "accent_light": "#a5f3fc",
    "accent_rgb": "95, 213, 235",
    "secondary": "#E8C468", "secondary_rgb": "232, 196, 104",
    "border_rgb": "165, 200, 255", "border_alpha": 0.22,
    "divider_rgb": "150, 185, 225", "divider_alpha": 0.32,
    "badge_bg": "#182437", "badge_fg": "#4aa8b8",
    "success": "#4ade80", "warning": "#facc15", "error": "#f87171",
}

# Derived surfaces and hairlines (see module docstring).
WINDOW = PALETTE["bg"]
RAIL_TOP = "#0c1626"
RAIL_BOTTOM = "#070b14"
LOG_BG = "#070d16"
INK = "#04141b"                       # text on an accent fill
ACCENT_DIM = "#3aa8bd"                # pressed
ACCENT_FAINT = "rgba(95, 213, 235, 0.07)"
ACCENT_WASH = "rgba(95, 213, 235, 0.13)"
ACCENT_BORDER = "rgba(95, 213, 235, 0.32)"
ACCENT_GLOW = (95, 213, 235)
BORDER = "rgba(165, 200, 255, 0.14)"
BORDER_STRONG = "rgba(165, 200, 255, 0.26)"
DIVIDER = "rgba(150, 185, 225, 0.18)"

HEADING_FALLBACK = "Segoe UI"
FONT_FILES = ("fonts/Rajdhani-Bold.ttf", "fonts/Rajdhani-SemiBold.ttf")

_heading_family = None
_version = None


# --------------------------------------------------------------------------
# Fonts and assets
# --------------------------------------------------------------------------

def repo_root() -> str:
    """Repository root in a source checkout (the installer's dev mode)."""
    here = os.path.dirname(os.path.abspath(__file__))          # .../bootstrapper
    return os.path.dirname(os.path.dirname(here))              # .../poise-...


def asset_root() -> str:
    """Directory holding icon.png, icon.ico and fonts/."""
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return os.path.join(bundled, "assets")
    return os.path.join(repo_root(), "stream_denoiser", "gui", "assets")


def asset(name: str) -> str:
    """Absolute path of an asset ('icon.png', 'fonts/Rajdhani-Bold.ttf')."""
    return os.path.join(asset_root(), *name.split("/"))


def load_fonts() -> str:
    """Register Rajdhani once; return the heading family to use."""
    global _heading_family
    if _heading_family is not None:
        return _heading_family
    family = None
    try:
        from PyQt6.QtGui import QFontDatabase, QGuiApplication
        if QGuiApplication.instance() is None:
            # QFontDatabase aborts without an application; leave the
            # fallback uncached so a later call can still register.
            return HEADING_FALLBACK
        for name in FONT_FILES:
            path = asset(name)
            if not os.path.isfile(path):
                continue
            font_id = QFontDatabase.addApplicationFont(path)
            if font_id < 0:
                continue
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families and family is None:
                family = families[0]
    except Exception:
        family = None
    _heading_family = family or HEADING_FALLBACK
    return _heading_family


def heading_family() -> str:
    """Bundled heading face, or the platform fallback."""
    return _heading_family or load_fonts()


def heading_css() -> str:
    """font-family value for the stylesheet."""
    return f"'{heading_family()}', 'Segoe UI', 'Inter', sans-serif"


def version() -> str:
    """Release version: bundled version.txt, else pyproject.toml."""
    global _version
    if _version is not None:
        return _version
    candidates = []
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        candidates.append(os.path.join(bundled, "version.txt"))
    candidates.append(os.path.join(repo_root(), "pyproject.toml"))
    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            continue
        match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
        if match:
            _version = match.group(1)
            return _version
        # The build writes version.txt as a bare number ("1.1.0").
        plain = text.strip()
        if re.fullmatch(r"\d+(?:\.\d+)+", plain):
            _version = plain
            return _version
    _version = "dev"
    return _version


# --------------------------------------------------------------------------
# Stylesheet
# --------------------------------------------------------------------------

_QSS = """
QWidget#shell {
    background-color: @bg@;
    color: @text@;
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 13px;
}

/* Labels carry colour only: their fonts are set in code, where the
   heading face's letter spacing can be set too (QSS has no equivalent). */
QWidget#panel { background-color: @bg@; }

QLabel { background: transparent; color: @text@; }
QLabel#eyebrow { color: @muted@; }
QLabel#display { color: @text@; }
QLabel#sub { color: @muted@; }
QLabel#small { color: @muted@; }
QLabel#card-title { color: @text@; }
QLabel#card-sub { color: @muted@; }
QLabel#notice-title { color: @accent_light@; }
QLabel#notice-sub { color: @muted@; }
QLabel#warn-title { color: @warning@; }
QLabel#warning { color: @warning@; }
QLabel#error-title { color: @error@; }
QLabel#wordmark { color: @text@; }
QLabel#wordsub { color: @accent@; }
QLabel#tagline { color: @muted@; }
QLabel#version { color: @muted@; }

QFrame#card {
    background-color: @card@;
    border: 1px solid @border@;
    border-radius: 12px;
}
QFrame#notice {
    background-color: @accent_faint@;
    border: 1px solid @accent_border@;
    border-radius: 12px;
}
QFrame#warn {
    background-color: rgba(250, 204, 21, 0.07);
    border: 1px solid rgba(250, 204, 21, 0.26);
    border-radius: 12px;
}
QFrame#rule {
    background-color: @border@;
    border: none;
    min-height: 1px;
    max-height: 1px;
}

QPushButton#primary {
    background-color: @accent@;
    color: @ink@;
    border: none;
    border-radius: 9px;
    padding: 0 26px;
    min-height: 42px;
    font-size: 13px;
    font-weight: 600;
}
QPushButton#primary:hover { background-color: @accent_light@; }
QPushButton#primary:pressed { background-color: @accent_dim@; }
QPushButton#primary:disabled {
    background-color: rgba(95, 213, 235, 0.20);
    color: @muted@;
}

QPushButton#ghost {
    background-color: transparent;
    color: @device_title@;
    border: 1px solid @border_strong@;
    border-radius: 9px;
    padding: 0 20px;
    min-height: 42px;
    font-size: 13px;
}
QPushButton#ghost:hover {
    color: @text@;
    border-color: @accent_border@;
    background-color: @accent_faint@;
}
QPushButton#ghost:pressed { background-color: @accent_wash@; }
QPushButton#ghost:disabled { color: @muted@; border-color: @border@; }

QPushButton#tool {
    background: transparent;
    border: none;
    color: @accent@;
    font-size: 12px;
    padding: 4px 2px;
}
QPushButton#tool:hover { color: @accent_light@; }
QPushButton#tool:disabled { color: @muted@; }

QPlainTextEdit#log {
    background-color: @log@;
    border: 1px solid @border@;
    border-radius: 8px;
    color: @muted@;
    font-family: 'Consolas', 'Cascadia Mono', monospace;
    font-size: 11px;
    padding: 8px;
}

QScrollBar:vertical {
    background: transparent;
    width: 9px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: @border_strong@;
    border-radius: 4px;
    min-height: 24px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
"""

_TOKENS = {
    "bg": WINDOW,
    "card": PALETTE["card"],
    "text": PALETTE["text"],
    "muted": PALETTE["muted"],
    "device_title": PALETTE["device_title"],
    "warning": PALETTE["warning"],
    "error": PALETTE["error"],
    "accent": PALETTE["accent"],
    "accent_light": PALETTE["accent_light"],
    "accent_dim": ACCENT_DIM,
    "accent_faint": ACCENT_FAINT,
    "accent_wash": ACCENT_WASH,
    "accent_border": ACCENT_BORDER,
    "border": BORDER,
    "border_strong": BORDER_STRONG,
    "ink": INK,
    "log": LOG_BG,
}


def stylesheet() -> str:
    """The setup window's QSS, with the palette resolved in."""
    css = _QSS
    for key, value in _TOKENS.items():
        css = css.replace(f"@{key}@", value)
    return css.replace("@heading@", heading_css())
