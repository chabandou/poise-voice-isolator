"""
Poise Voice Isolator - Phosphor Icons

Professionally drawn icons (Phosphor Icons, MIT — see assets/icons/LICENSE)
rendered from the vendored regular-weight SVGs with runtime tinting, so a
single asset serves every color state (active nav, muted, badge glyphs...).

Sizes follow the UI scale (see gui/scaling.py) and render at the screen's
device pixel ratio for crisp edges on HiDPI displays.
"""
import os

from PyQt6.QtWidgets import QApplication, QLabel
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QPainter, QColor, QImage, QPixmap
from PyQt6.QtSvg import QSvgRenderer

from ..scaling import isp
from ..themes import current as current_theme

ICONS_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "assets", "icons"))

#: Logical names used across the app -> vendored Phosphor file stems.
FILES = {
    "waveform": "waveform",
    "gear": "gear",
    "doc": "file-text",
    "info": "info",
    "monitor": "monitor",
    "speaker": "speaker-high",
    "percent": "percent",
    "clock": "clock",
    "pulse": "pulse",
    "buffer": "stack",
    "refresh": "arrow-clockwise",
    "folder": "folder",
    "palette": "palette",
    "cpu": "cpu",
    "sliders": "sliders-horizontal",
}

_renderers: dict = {}
_pixmaps: dict = {}


def clear_cache() -> None:
    """Drop cached pixmaps (call after a theme switch changes colors)."""
    _pixmaps.clear()


def _renderer(name: str) -> QSvgRenderer:
    """Cached SVG renderer for a logical icon name."""
    if name not in _renderers:
        path = os.path.join(ICONS_DIR, FILES[name] + ".svg")
        with open(path, "rb") as f:
            _renderers[name] = QSvgRenderer(f.read())
    return _renderers[name]


def _device_pixel_ratio() -> float:
    try:
        app = QApplication.instance()
        screen = app.primaryScreen() if app is not None else None
        if screen is not None:
            return float(screen.devicePixelRatio() or 1.0)
    except Exception:
        pass
    return 1.0


def _tinted_pixmap(name: str, size_px: int, color: str) -> QPixmap:
    """Render an icon tinted to a color (cached per name/size/color/DPR)."""
    dpr = _device_pixel_ratio()
    key = (name, size_px, color, dpr)
    pixmap = _pixmaps.get(key)
    if pixmap is not None:
        return pixmap

    render_px = max(1, int(round(size_px * dpr)))
    image = QImage(render_px, render_px, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    _renderer(name).render(painter)
    # Recolor every drawn pixel (Phosphor uses fill="currentColor").
    painter.setCompositionMode(
        QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(image.rect(), QColor(color))
    painter.end()

    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(dpr)
    _pixmaps[key] = pixmap
    return pixmap


class PhosphorIcon(QLabel):
    """A single-color Phosphor icon drawn by logical name.

    With color=None (default) the icon follows the active theme accent;
    pass an explicit color to pin it (e.g. the VAD badge glyph).
    """

    NAMES = tuple(FILES)

    def __init__(self, name: str = "waveform",
                 color: str = None, size: int = 22, parent=None):
        super().__init__(parent)
        if name not in FILES:
            name = "waveform"
        self._name = name
        self._color = color
        self._size = isp(size)
        # setFixedSize pins min and max alike, so layouts can never
        # squeeze the glyph below its painted size.
        self.setFixedSize(QSize(self._size, self._size))

    def set_icon(self, name: str) -> None:
        if name in FILES:
            self._name = name
            self.update()

    def set_color(self, color: str) -> None:
        self._color = color
        self.update()

    def paintEvent(self, event):  # noqa: N802 (Qt override)
        color = self._color or current_theme()["accent"]
        painter = QPainter(self)
        painter.drawPixmap(0, 0, _tinted_pixmap(
            self._name, self._size, color))
        painter.end()
