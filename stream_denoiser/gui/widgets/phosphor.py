"""
Poise Voice Isolator - Phosphor Icons

Professionally drawn icons (Phosphor Icons, MIT — see assets/icons/LICENSE)
rendered from the vendored regular-weight SVGs with runtime tinting, so a
single asset serves every color state (active nav, muted, badge glyphs...).

Sizes follow the UI scale (see gui/scaling.py) and render at the screen's
device pixel ratio for crisp edges on HiDPI displays.
"""
import os
import time

from PyQt6.QtWidgets import QApplication, QLabel
from PyQt6.QtCore import (
    QEasingCurve, QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation,
)
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
    "heart": "heart",
    "copy": "copy",
    "save": "floppy-disk",
    "reset": "arrow-counter-clockwise",
    "download": "download-simple",
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
    pass an explicit color to pin it (e.g. the AAD badge glyph).
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


# -- icons with moving parts ----------------------------------------------------
#: Glyphs split into parts (Phosphor's 256-unit box) so a hover can move a
#: piece. Parts scale about their own centre; LEFT_PIVOT ones grow from
#: their left edge.
PARTS = {
    "waveform": (
        ("b0", '<rect x="40" y="88" width="16" height="80" rx="8"/>'),
        ("b1", '<rect x="80" y="24" width="16" height="208" rx="8"/>'),
        ("b2", '<rect x="120" y="56" width="16" height="144" rx="8"/>'),
        ("b3", '<rect x="160" y="88" width="16" height="80" rx="8"/>'),
        ("b4", '<rect x="200" y="72" width="16" height="112" rx="8"/>'),
    ),
    "doc": (
        ("page", '<path d="M213.66,82.34l-56-56A8,8,0,0,0,152,24H56A16,16,0,0,'
                 '0,40,40V216a16,16,0,0,0,16,16H200a16,16,0,0,0,16-16V88A8,8,0,'
                 '0,0,213.66,82.34ZM160,51.31,188.69,80H160ZM200,216H56V40h88V'
                 '88a8,8,0,0,0,8,8h48V216Z"/>'),
        ("l0", '<rect x="88" y="128" width="80" height="16" rx="8"/>'),
        ("l1", '<rect x="88" y="160" width="80" height="16" rx="8"/>'),
    ),
    "info": (
        ("ring", '<path d="M128,24A104,104,0,1,0,232,128,104.11,104.11,0,0,0,'
                 '128,24Zm0,192a88,88,0,1,1,88-88A88.1,88.1,0,0,1,128,216Zm16'
                 '-40a8,8,0,0,1-8,8,16,16,0,0,1-16-16V128a8,8,0,0,1,0-16,16,16,'
                 '0,0,1,16,16v40A8,8,0,0,1,144,176Z"/>'),
        ("dot", '<circle cx="124" cy="84" r="12"/>'),
    ),
    "speaker": (
        ("body", '<path d="M155.51,24.81a8,8,0,0,0-8.42.88L77.25,80H32A16,16,'
                 '0,0,0,16,96v64a16,16,0,0,0,16,16H77.25l69.84,54.31A8,8,0,0,'
                 '0,160,224V32A8,8,0,0,0,155.51,24.81ZM32,96H72v64H32ZM144,'
                 '207.64,88,164.09V91.91l56-43.55Z"/>'),
        ("w0", '<path d="M198,101.56a40,40,0,0,1,0,52.88,8,8,0,0,1-12-10.58,'
               '24,24,0,0,0,0-31.72,8,8,0,0,1,12-10.58Z"/>'),
        ("w1", '<path d="M248,128a79.9,79.9,0,0,1-20.37,53.34,8,8,0,0,1-11.92'
               '-10.67,64,64,0,0,0,0-85.33,8,8,0,1,1,11.92-10.67A79.83,79.83,'
               '0,0,1,248,128Z"/>'),
    ),
    "cpu": (
        ("die", '<path d="M152,96H104a8,8,0,0,0-8,8v48a8,8,0,0,0,8,8h48a8,8,0,'
                '0,0,8-8V104A8,8,0,0,0,152,96Zm-8,48H112V112h32Z"/>'),
        ("body", '<path d="M232,144H216V112h16a8,8,0,0,0,0-16H216V56a16,16,0,'
                 '0,0-16-16H160V24a8,8,0,0,0-16,0V40H112V24a8,8,0,0,0-16,0V40'
                 'H56A16,16,0,0,0,40,56V96H24a8,8,0,0,0,0,16H40v32H24a8,8,0,0,'
                 '0,0,16H40v40a16,16,0,0,0,16,16H96v16a8,8,0,0,0,16,0V216h32v'
                 '16a8,8,0,0,0,16,0V216h40a16,16,0,0,0,16-16V160h16a8,8,0,0,0,'
                 '0-16Zm-32,56H56V56H200v95.87s0,.09,0,.13,0,.09,0,.13V200Z"/>'),
    ),
}
LEFT_PIVOT = ("l0", "l1")
#: How long each icon's hover motion runs (ms).
MOTION_MS = {"waveform": 880, "doc": 510, "info": 520, "speaker": 1260,
             "cpu": 900}

_part_renderers: dict = {}


def _parts_renderer(name: str) -> QSvgRenderer:
    if name not in _part_renderers:
        body = "".join(element.replace("/>", f' id="{pid}"/>', 1)
                       for pid, element in PARTS[name])
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" '
               f'fill="#ffffff">{body}</svg>')
        _part_renderers[name] = QSvgRenderer(svg.encode("utf-8"))
    return _part_renderers[name]


def part_pose(name: str, part: str, t: float):
    """(opacity, x scale, y scale, lift in glyph units) of one part of
    an icon `t` ms into its hover motion."""
    from ..animations import ease_back, ease_out
    if name == "waveform":             # the bars bob, left to right
        u = (t - int(part[1:]) * 60) / 640.0
        if 0 <= u < 1:
            y = (1 - 0.6 * ease_out(u / 0.35) if u < 0.35
                 else 0.4 + 0.6 * ease_out((u - 0.35) / 0.65))
            return 1.0, 1.0, y, 0.0
    elif name == "doc" and part in LEFT_PIVOT:   # the lines draw in
        u = (t - (90 if part == "l1" else 0)) / 420.0
        return 1.0, ease_out(u), 1.0, 0.0
    elif name == "info" and part == "dot":       # the dot hops
        u = t / 520.0
        if 0 <= u < 1:
            lift = (-34 * ease_out(u / 0.4) if u < 0.4
                    else -34 * (1 - ease_back((u - 0.4) / 0.6, 2.4)))
            return 1.0, 1.0, 1.0, lift
    elif name == "speaker" and part != "body":   # the waves emit
        u = (t - (160 if part == "w1" else 0)) / 1100.0
        return 0.1 + 0.9 * ease_out(u / 0.45), 1.0, 1.0, 0.0
    elif name == "cpu" and part == "die":        # the die squeezes
        u = t / 900.0
        if 0 <= u < 1:
            s = (1 - 0.45 * ease_out(u / 0.3) if u < 0.3
                 else 0.55 + 0.45 * ease_back((u - 0.3) / 0.7, 2.2))
            return 1.0, s, s, 0.0
    return 1.0, 1.0, 1.0, 0.0


class MotionIcon(PhosphorIcon):
    """A PhosphorIcon whose pieces can move.

    play() runs the glyph's hover motion when it has parts (bars bob,
    lines draw in, the dot hops, waves emit, the die squeezes); turn()
    and spin() rotate the whole glyph (the gear on hover, refresh on
    click). At rest it paints the cached pixmap like any PhosphorIcon.
    Reduced motion keeps it still.
    """

    FRAME_MS = 16

    def __init__(self, name: str = "waveform",
                 color: str = None, size: int = 22, parent=None):
        super().__init__(name, color, size, parent)
        self._played_at = None
        self._angle = 0.0
        self._aim = 0.0
        self._turner = QVariantAnimation(self)
        self._turner.valueChanged.connect(self._set_angle)
        self._turner.finished.connect(self._settle_angle)
        self._frames = QTimer(self)
        self._frames.setInterval(self.FRAME_MS)
        self._frames.timeout.connect(self._frame)

    def hover(self, on: bool) -> None:
        """Pointer over the icon's owner: the gear turns, others play."""
        if self._name == "gear":
            self.turn(60.0 if on else 0.0)
        elif on:
            self.play()

    def play(self) -> None:
        from ..animations import motion_ok
        if not motion_ok() or self._name not in PARTS:
            return
        self._played_at = time.monotonic()
        self._frames.start()

    def turn(self, degrees: float, ms: int = 620,
             overshoot: float = 1.56) -> None:
        """Rotate the glyph to `degrees` with a spring."""
        from ..animations import motion_ok
        self._aim = float(degrees)
        if not motion_ok():
            self._set_angle(self._aim)
            self._settle_angle()
            return
        curve = QEasingCurve(QEasingCurve.Type.OutBack)
        curve.setOvershoot(overshoot)
        self._turner.stop()
        self._turner.setDuration(ms)
        self._turner.setEasingCurve(curve)
        self._turner.setStartValue(self._angle)
        self._turner.setEndValue(self._aim)
        self._turner.start()

    def spin(self) -> None:
        """One full turn (e.g. a rescan)."""
        self.turn(self._aim + 360.0, ms=780, overshoot=1.35)

    def _set_angle(self, value) -> None:
        self._angle = float(value)
        self.update()

    def _settle_angle(self) -> None:
        # Whole turns look the same: keep the numbers small.
        self._aim %= 360.0
        self._angle = self._aim
        self.update()

    def _moving_ms(self):
        """Milliseconds into the hover motion, or None when at rest."""
        if self._played_at is None:
            return None
        t = (time.monotonic() - self._played_at) * 1000.0
        return t if t < MOTION_MS.get(self._name, 0) else None

    def _frame(self) -> None:
        if self._moving_ms() is None:
            self._frames.stop()
            self._played_at = None
        self.update()

    def paintEvent(self, event):  # noqa: N802 (Qt override)
        t = self._moving_ms()
        if t is None and abs(self._angle) < 0.01:
            super().paintEvent(event)
            return
        color = self._color or current_theme()["accent"]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        half = self._size / 2.0
        painter.translate(half, half)
        painter.rotate(self._angle)
        painter.translate(-half, -half)
        if t is None:
            painter.drawPixmap(0, 0, _tinted_pixmap(
                self._name, self._size, color))
        else:
            painter.drawImage(0, 0, self._parts_image(color, t))
        painter.end()

    def _parts_image(self, color: str, t: float) -> QImage:
        dpr = _device_pixel_ratio()
        px = max(1, int(round(self._size * dpr)))
        image = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(dpr)
        image.fill(Qt.GlobalColor.transparent)
        renderer = _parts_renderer(self._name)
        scale = self._size / 256.0
        p = QPainter(image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for part, _ in PARTS[self._name]:
            opacity, sx, sy, lift = part_pose(self._name, part, t)
            if opacity <= 0.0 or sx <= 0.0 or sy <= 0.0:
                continue
            b = renderer.boundsOnElement(part)
            rect = QRectF(b.x() * scale, b.y() * scale,
                          b.width() * scale, b.height() * scale)
            pivot = (QPointF(rect.left(), rect.center().y())
                     if part in LEFT_PIVOT else rect.center())
            p.save()
            p.setOpacity(opacity)
            p.translate(pivot.x(), pivot.y() + lift * scale)
            p.scale(sx, sy)
            p.translate(-pivot.x(), -pivot.y())
            renderer.render(p, part, rect)
            p.restore()
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        p.fillRect(QRectF(0, 0, self._size, self._size), QColor(color))
        p.end()
        return image


def icon(name: str, size: int = 16, color: str = None):
    """QIcon of a Phosphor glyph (for buttons), tinted and scaled like
    PhosphorIcon. Re-create it after a theme switch to re-tint."""
    from PyQt6.QtGui import QIcon
    if name not in FILES:
        name = "waveform"
    return QIcon(_tinted_pixmap(
        name, isp(size), color or current_theme()["accent"]))
