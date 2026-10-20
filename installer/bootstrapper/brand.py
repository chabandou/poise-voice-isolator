"""
Poise Setup - brand tokens, assets and stylesheet.

Standalone on purpose. Importing stream_denoiser.gui would execute
gui/__init__.py, which imports MainWindow and drags the entire
application (audio backends, models, Qt Quick) into a 40 MB setup
window. PALETTE therefore repeats gui/themes.py's "halcyon" entry verbatim;
tests/test_installer_core.py asserts the two stay identical.

Every other colour is one the app itself uses for the same element
(gui/styles.py, gui/titlebar.py), built from PALETTE or from the app's
own fixed neutrals (its slate hairlines, its checkbox grey). Nothing
here is a colour of the installer's own.
"""
from __future__ import annotations

import os
import re
import sys

#: gui/themes.py, THEMES["halcyon"] - the signature palette.
PALETTE = {
    "label": "Halcyon",
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

# Derived values, each named after the app rule it copies.


def _rgba(rgb: str, alpha: float) -> str:
    return f"rgba({rgb}, {alpha})"


#: The app's fixed slate neutral (148, 163, 184): sidebar edge, ghost
#: buttons, log and scrollbar hairlines, at the app's own alphas.
SLATE_RGB = "148, 163, 184"
#: styles.py ACCENT_WASH_ALPHA (themes.py): hover/pressed accent washes.
ACCENT_WASH_ALPHA = 0.12

WINDOW = PALETTE["bg"]                       # QMainWindow / page fill
RAIL = PALETTE["sidebar"]                    # QFrame#sidebar
RAIL_EDGE = _rgba(SLATE_RGB, 0.12)           # its border-right
FRAME = PALETTE["sidebar"]                   # titlebar.py BORDER_KEY
INK = PALETTE["bg"]                          # text on an accent fill
CARD_BORDER = _rgba(PALETTE["border_rgb"], PALETTE["border_alpha"])
ACCENT_WASH = _rgba(PALETTE["accent_rgb"], ACCENT_WASH_ALPHA)
ACCENT_DISABLED = _rgba(PALETTE["accent_rgb"], 0.3)
GHOST_FILL = _rgba(SLATE_RGB, 0.08)
GHOST_BORDER = _rgba(SLATE_RGB, 0.18)
LOG_BORDER = _rgba(SLATE_RGB, 0.14)
SCROLL = _rgba(SLATE_RGB, 0.25)
SCROLL_HOVER = _rgba(SLATE_RGB, 0.45)
CHIP = _rgba(PALETTE["secondary_rgb"], 0.16)    # QFrame#chip
CHECK_BORDER = "#475569"                     # QCheckBox::indicator


def hex_rgb(colour: str) -> str:
    """'#RRGGBB' -> 'r, g, b'."""
    value = colour.lstrip("#")
    return ", ".join(str(int(value[i:i + 2], 16)) for i in (0, 2, 4))


#: The app's status chips are their colour at 14% (QFrame#err-chip).
SUCCESS_CHIP = _rgba(hex_rgb(PALETTE["success"]), 0.14)
WARNING_FILL = _rgba(hex_rgb(PALETTE["warning"]), 0.07)
WARNING_BORDER = _rgba(hex_rgb(PALETTE["warning"]), 0.26)

#: Who makes Poise, as credited in the rail and the exe's details.
PUBLISHER = "chabandou"

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
    """Directory holding icon.svg, icon-setup.ico and fonts/."""
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return os.path.join(bundled, "assets")
    return os.path.join(repo_root(), "stream_denoiser", "gui", "assets")


def asset(name: str) -> str:
    """Absolute path of an asset ('icon.svg', 'icon-setup.ico', a font)."""
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
QLabel#notice-title { color: @text@; }
QLabel#notice-sub { color: @muted@; }
QLabel#warn-title { color: @warning@; }
QLabel#warning { color: @warning@; }
QLabel#error-title { color: @error@; }
QLabel#wordmark { color: @text@; }
QLabel#wordsub { color: @accent@; }
QLabel#tagline { color: @muted@; }
QLabel#version { color: @muted@; }

/* QFrame#card in the app; the driver notice is a card too. */
QFrame#card, QFrame#notice {
    background-color: @card@;
    border: 1px solid @card_border@;
    border-radius: 16px;
}
/* QFrame#chip: the secondary-tinted icon chip on the app's cards. */
QLabel#chip {
    color: @secondary@;
    background-color: @chip@;
    border-radius: 11px;
    font-size: 11px;
    font-weight: 700;
}
QFrame#warn {
    background-color: @warning_fill@;
    border: 1px solid @warning_border@;
    border-radius: 16px;
}

QPushButton#primary {
    background-color: @accent@;
    color: @ink@;
    border: none;
    border-radius: 10px;
    padding: 0 26px;
    min-height: 42px;
    font-size: 13px;
    font-weight: 700;
}
QPushButton#primary:hover { background-color: @accent_light@; }
QPushButton#primary:disabled {
    background-color: @accent_disabled@;
    color: @muted@;
}

QPushButton#ghost {
    background-color: @ghost_fill@;
    color: @text@;
    border: 1px solid @ghost_border@;
    border-radius: 10px;
    padding: 0 20px;
    min-height: 42px;
    font-size: 13px;
    font-weight: 600;
}
QPushButton#ghost:hover { border-color: @secondary@; }
QPushButton#ghost:pressed { background-color: @accent_wash@; }
QPushButton#ghost:disabled { color: @muted@; }

QPushButton#tool {
    background: transparent;
    border: none;
    color: @accent@;
    font-size: 12px;
    padding: 4px 2px;
}
QPushButton#tool:hover { color: @accent_light@; }
QPushButton#tool:disabled { color: @muted@; }

/* QPlainTextEdit#logs */
QPlainTextEdit#log {
    background-color: @sidebar@;
    border: 1px solid @log_border@;
    border-radius: 12px;
    color: @text@;
    font-family: 'Consolas', 'Cascadia Mono', monospace;
    font-size: 11px;
    padding: 8px;
}

QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: @scroll@;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: @scroll_hover@; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
"""

_TOKENS = {
    "bg": WINDOW,
    "sidebar": PALETTE["sidebar"],
    "card": PALETTE["card"],
    "text": PALETTE["text"],
    "muted": PALETTE["muted"],
    "warning": PALETTE["warning"],
    "error": PALETTE["error"],
    "accent": PALETTE["accent"],
    "accent_light": PALETTE["accent_light"],
    "secondary": PALETTE["secondary"],
    "accent_wash": ACCENT_WASH,
    "accent_disabled": ACCENT_DISABLED,
    "card_border": CARD_BORDER,
    "chip": CHIP,
    "ghost_fill": GHOST_FILL,
    "ghost_border": GHOST_BORDER,
    "log_border": LOG_BORDER,
    "scroll": SCROLL,
    "scroll_hover": SCROLL_HOVER,
    "warning_fill": WARNING_FILL,
    "warning_border": WARNING_BORDER,
    "ink": INK,
}


def stylesheet() -> str:
    """The setup window's QSS, with the palette resolved in."""
    css = _QSS
    for key, value in _TOKENS.items():
        css = css.replace(f"@{key}@", value)
    return css.replace("@heading@", heading_css())
