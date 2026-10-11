"""
Poise Voice Isolator - fonts

Bundles Rajdhani (SIL OFL, see assets/fonts/OFL.txt) for headings, the dial
label and big numerals. Body text stays on the platform UI font. Loading
is best-effort: when the files or Qt are unavailable everything falls back
to Segoe UI, so a missing font can never break the app (or the Qt-free
stylesheet tests).
"""
import os

FONTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "assets", "fonts")
FONT_FILES = ("Rajdhani-SemiBold.ttf", "Rajdhani-Bold.ttf")
HEADING_FALLBACK = "Segoe UI"

_heading_family = None


def load_fonts() -> str:
    """Register the bundled fonts once; return the heading family name."""
    global _heading_family
    if _heading_family is not None:
        return _heading_family
    family = None
    try:
        from PyQt6.QtGui import QFontDatabase, QGuiApplication
        if QGuiApplication.instance() is None:
            # QFontDatabase aborts without an application; stay on the
            # fallback (uncached) so a later call can still register.
            return HEADING_FALLBACK
        for name in FONT_FILES:
            path = os.path.join(FONTS_DIR, name)
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
    """Family used for headings (bundled font when it registered)."""
    return _heading_family or load_fonts()


def heading_css() -> str:
    """font-family value for stylesheets."""
    return f"'{heading_family()}', 'Segoe UI', 'Inter', sans-serif"
