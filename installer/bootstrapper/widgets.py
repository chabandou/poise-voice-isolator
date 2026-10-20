"""
Poise Setup - painted pieces of the setup window.

Nothing here is stock Qt chrome: the rail, step rows, progress track,
checkbox and status badge all draw themselves from brand.PALETTE, which
is why the setup window can look like Poise without loading any of the
application's widgets.
"""
from __future__ import annotations

import math
import sys

from PyQt6.QtCore import (
    QEasingCurve, QElapsedTimer, QPointF, QRectF, QSize, Qt, QTimer,
    QVariantAnimation,
)
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QFontMetrics, QImage, QLinearGradient, QPainter,
    QPainterPath, QPen, QPixmap, QRadialGradient, QTransform,
)
from PyQt6.QtWidgets import QAbstractButton, QLabel, QSizePolicy, QWidget

from . import brand

ACCENT = QColor(95, 213, 235)
ACCENT_LIGHT = QColor(165, 243, 252)
TEXT = QColor(248, 250, 252)
MUTED = QColor(139, 148, 163)
DEVICE_TITLE = QColor(154, 163, 178)
BORDER_RGB = (165, 200, 255)
SUCCESS = QColor(74, 222, 128)
ERROR = QColor(248, 113, 113)
WARNING = QColor(250, 204, 21)


def rgba(colour, alpha: int) -> QColor:
    """A colour at a given 0-255 alpha.

    Accepts either an (r, g, b) tuple or an existing QColor, so call sites
    can pass the module's colour constants directly.
    """
    if isinstance(colour, QColor):
        return QColor(colour.red(), colour.green(), colour.blue(), alpha)
    return QColor(colour[0], colour[1], colour[2], alpha)


def motion_enabled() -> bool:
    """False when Windows' "Show animations in Windows" is off.

    The setup window runs before Poise's own Reduce motion setting exists,
    so it follows the system switch (SPI_GETCLIENTAREAANIMATION) instead.
    """
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        enabled = ctypes.c_int(1)
        ok = ctypes.windll.user32.SystemParametersInfoW(
            0x1042, 0, ctypes.byref(enabled), 0)
        return bool(enabled.value) if ok else True
    except Exception:
        return True


def _ease_out(t: float) -> float:
    """Cubic ease-out on 0..1, clamped."""
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3


def _span(t: float, start: float, end: float) -> float:
    """Where t falls inside [start, end], as 0..1."""
    return max(0.0, min(1.0, (t - start) / (end - start)))


def ui_font(px: float, weight: QFont.Weight = QFont.Weight.Normal,
            spacing: float = 0.0, family: str = "Segoe UI") -> QFont:
    font = QFont(family)
    font.setPixelSize(max(1, int(round(px))))
    font.setWeight(weight)
    if spacing:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return font


def heading_font(px: float, weight: QFont.Weight = QFont.Weight.Bold,
                 spacing: float = 0.0) -> QFont:
    return ui_font(px, weight, spacing, family=brand.heading_family())


# --------------------------------------------------------------------------
# The Home card's lattice, reproduced from gui/widgets/pattern_card.py:
# a 64px tile of a square, its 45-degree twin, spokes to the tile edges and
# a centre dot, in the theme's secondary colour. The numbers are the
# design's own (tile 64, offset -14/-6, stroke 1, dot r 2.5, opacity .2).
# --------------------------------------------------------------------------

LATTICE_TILE = 64.0
LATTICE_OFFSET = (-14.0, -6.0)
LATTICE_STROKE = 1.0
LATTICE_DOT_RADIUS = 2.5
LATTICE_OPACITY = 0.20
#: The rail is narrower than the Home card, so its tile is drawn a little
#: smaller than the design's 64px; the line weight stays at 1px.
LATTICE_SCALE = 0.8
#: Radial mask over the lattice, in box units: (centre x, centre y,
#: radius, clear stop). The Home card keeps its lattice off the dial this
#: way; here the centre sits low on the left-aligned text block, so the
#: pattern opens up earlier towards the rail's right edge and its top.
#: None paints the pattern everywhere.
LATTICE_MASK = (0.22, 0.43, 0.57, 0.32)


def _lattice_tile() -> QPainterPath:
    """Line work of one 64x64 tile, in design units."""
    path = QPainterPath()
    path.addRect(QRectF(21, 21, 22, 22))
    diamond = QTransform().translate(32, 32).rotate(45).translate(-32, -32)
    square = QPainterPath()
    square.addRect(QRectF(21, 21, 22, 22))
    path.addPath(diamond.map(square))
    for x1, y1, x2, y2 in ((32, 0, 32, 16.4), (32, 47.6, 32, 64),
                           (0, 32, 16.4, 32), (47.6, 32, 64, 32),
                           (0, 0, 21, 21), (64, 0, 43, 21),
                           (0, 64, 21, 43), (64, 64, 43, 43)):
        path.moveTo(x1, y1)
        path.lineTo(x2, y2)
    return path


_TILE_PATH = _lattice_tile()


class Rail(QWidget):
    """The brand rail: lattice texture, emblem, wordmark, tagline."""

    WIDTH = 322

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(self.WIDTH)
        self.setObjectName("rail")
        self._lattice = None
        self._lattice_key = None

        from PyQt6.QtWidgets import QVBoxLayout

        outer = QVBoxLayout(self)
        outer.setContentsMargins(36, 40, 36, 30)
        outer.setSpacing(0)

        emblem = QLabel()
        emblem.setFixedSize(108, 108)
        # The About page's mark: the vector waveform (gui/utils.py prefers
        # icon.svg over the raster app icon). No tile behind it - the glow
        # is part of the artwork.
        pixmap = QPixmap(brand.asset("icon.svg"))
        if pixmap.isNull():
            pixmap = QPixmap(brand.asset("icon.png"))
        if not pixmap.isNull():
            emblem.setPixmap(pixmap.scaled(
                108, 108, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        outer.addWidget(emblem)

        outer.addSpacing(18)
        wordmark = QLabel("POISE")
        wordmark.setObjectName("wordmark")
        wordmark.setFont(heading_font(42, spacing=7.0))
        outer.addWidget(wordmark)

        wordsub = QLabel("VOICE ISOLATOR")
        wordsub.setObjectName("wordsub")
        wordsub.setFont(ui_font(10.5, QFont.Weight.DemiBold, spacing=3.4))
        outer.addWidget(wordsub)

        outer.addSpacing(16)
        outer.addWidget(Ornament())
        outer.addSpacing(14)

        tagline = QLabel("Take back control.")
        tagline.setObjectName("tagline")
        tagline.setFont(ui_font(14.5, QFont.Weight.Medium))
        outer.addWidget(tagline)

        blurb = QLabel("Everything your PC plays,\nwith the noise taken out.")
        blurb.setObjectName("tagline")
        blurb.setFont(ui_font(12.5))
        blurb.setContentsMargins(0, 6, 0, 0)
        outer.addWidget(blurb)

        outer.addStretch(1)

        version = QLabel(f"Version {brand.version()}")
        version.setObjectName("version")
        version.setFont(ui_font(11))
        outer.addWidget(version)

        fine = QLabel("Runs locally  ·  MIT licensed")
        fine.setObjectName("version")
        fine.setFont(ui_font(10.5))
        fine.setContentsMargins(0, 4, 0, 0)
        outer.addWidget(fine)

    def _lattice_image(self) -> QImage:
        """The tile lattice, tinted in the theme's gold, cached per size."""
        width, height = self.width(), self.height()
        ratio = self.devicePixelRatioF() or 1.0
        key = (width, height, ratio)
        if key == self._lattice_key:
            return self._lattice

        image = QImage(int(width * ratio), int(height * ratio),
                       QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(ratio)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.scale(ratio, ratio)
        scale = LATTICE_SCALE
        tile = LATTICE_TILE * scale
        pen = QPen(QColor(255, 255, 255), LATTICE_STROKE / scale)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        origin_x, origin_y = (v * scale for v in LATTICE_OFFSET)
        # One extra row/column so the pattern bleeds past both edges.
        columns = int(width / tile) + 2
        rows = int(height / tile) + 2
        for column in range(columns):
            for row in range(rows):
                painter.save()
                painter.translate(origin_x + column * tile,
                                  origin_y + row * tile)
                painter.scale(scale, scale)
                painter.setClipRect(QRectF(0, 0, LATTICE_TILE, LATTICE_TILE),
                                    Qt.ClipOperation.IntersectClip)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(_TILE_PATH)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(255, 255, 255))
                painter.drawEllipse(QPointF(32, 32), LATTICE_DOT_RADIUS,
                                    LATTICE_DOT_RADIUS)
                painter.restore()

        if LATTICE_MASK is not None:
            centre_x, centre_y, radius, clear = LATTICE_MASK
            gradient = QRadialGradient(QPointF(0, 0), 1.0)
            gradient.setColorAt(clear, QColor(255, 255, 255, 0))
            gradient.setColorAt(1.0, QColor(255, 255, 255, 255))
            gradient.setSpread(QRadialGradient.Spread.PadSpread)
            brush = QBrush(gradient)
            # Stretched to the rail (elliptical), as the card's SVG mask is
            # stretched to its box.
            brush.setTransform(
                QTransform().scale(radius * width, radius * height)
                * QTransform().translate(centre_x * width, centre_y * height))
            painter.setClipping(False)
            painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_DestinationIn)
            painter.fillRect(QRectF(0, 0, width, height), brush)
        painter.end()

        tinted = image.copy()
        tint = QPainter(tinted)
        tint.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_SourceIn)
        tint.fillRect(QRectF(0, 0, width, height),
                      QColor(brand.PALETTE["secondary"]))
        tint.end()
        self._lattice_key, self._lattice = key, tinted
        return tinted

    def paintEvent(self, event):  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())

        background = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        background.setColorAt(0.0, QColor(brand.RAIL_TOP))
        background.setColorAt(1.0, QColor(brand.RAIL_BOTTOM))
        painter.fillRect(rect, background)

        glow = QRadialGradient(rect.width() / 2, 132, 250)
        glow.setColorAt(0.0, QColor(95, 213, 235, 26))
        glow.setColorAt(1.0, QColor(95, 213, 235, 0))
        painter.fillRect(rect, glow)

        # The Home card's lattice, at the design's 20% over the whole rail.
        painter.setOpacity(LATTICE_OPACITY)
        painter.drawImage(0, 0, self._lattice_image())
        painter.setOpacity(1.0)

        painter.setPen(QPen(rgba(BORDER_RGB, 24), 1))
        painter.drawLine(int(rect.width()) - 1, 0,
                         int(rect.width()) - 1, int(rect.height()))


class Ornament(QWidget):
    """A gold hairline with the banner's diamond at its centre."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(10)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedWidth(132)

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        mid = self.height() / 2
        painter.setPen(QPen(rgba((232, 196, 104), 70), 1))
        painter.drawLine(0, int(mid), self.width(), int(mid))
        centre = self.width() / 2
        diamond = QPainterPath()
        diamond.moveTo(centre, mid - 4.2)
        diamond.lineTo(centre + 4.2, mid)
        diamond.lineTo(centre, mid + 4.2)
        diamond.lineTo(centre - 4.2, mid)
        diamond.closeSubpath()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(rgba((232, 196, 104), 190))
        painter.drawPath(diamond)


class Check(QAbstractButton):
    """A themed checkbox: painted box, painted label, keyboard friendly."""

    BOX = 18
    #: Room for the focus ring, so the widget's own edge cannot clip it.
    RING = 2.4
    INSET = 3

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedHeight(26)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:  # noqa: N802
        metrics = QFontMetrics(self.font())
        return QSize(self.INSET + self.BOX + 12
                     + metrics.horizontalAdvance(self.text()) + 4,
                     self.height())

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(self.INSET, (self.height() - self.BOX) / 2,
                     self.BOX, self.BOX)
        checked = self.isChecked()
        hovered = self.underMouse()

        if checked:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ACCENT)
            painter.drawRoundedRect(box, 5, 5)
            pen = QPen(QColor(brand.INK), 2.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            tick = QPainterPath()
            tick.moveTo(box.left() + 4.6, box.top() + 9.2)
            tick.lineTo(box.left() + 7.6, box.top() + 12.4)
            tick.lineTo(box.left() + 13.6, box.top() + 5.4)
            painter.drawPath(tick)
        else:
            painter.setPen(QPen(rgba(BORDER_RGB, 96 if hovered else 62), 1.2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(box.adjusted(0.6, 0.6, -0.6, -0.6), 5, 5)

        if self.hasFocus():
            painter.setPen(QPen(rgba((95, 213, 235), 120), 1.2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(
                box.adjusted(-self.RING, -self.RING,
                             self.RING, self.RING), 7, 7)

        painter.setFont(self.font())
        painter.setPen(TEXT if (checked or hovered) else DEVICE_TITLE)
        painter.drawText(
            QRectF(self.INSET + self.BOX + 10, 0,
                   self.width() - self.INSET - self.BOX - 10, self.height()),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            self.text())


class WindowButton(QAbstractButton):
    """The frameless window's only control: a close glyph."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(30, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip("Close")
        self.setAccessibleName("Close")

    def enterEvent(self, event):  # noqa: N802
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        enabled = self.isEnabled()
        hovered = self.underMouse() and enabled
        if hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(rgba(BORDER_RGB, 26))
            painter.drawEllipse(QRectF(1, 1, self.width() - 2,
                                       self.height() - 2))
        if not enabled:
            colour = rgba(TEXT, 70)
        else:
            colour = TEXT if hovered else DEVICE_TITLE
        pen = QPen(colour, 1.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        centre = QRectF(self.rect()).center()
        arm = 4.6
        painter.drawLine(QPointF(centre.x() - arm, centre.y() - arm),
                         QPointF(centre.x() + arm, centre.y() + arm))
        painter.drawLine(QPointF(centre.x() - arm, centre.y() + arm),
                         QPointF(centre.x() + arm, centre.y() - arm))


class Progress(QWidget):
    """Thin progress track with an accent fill and a soft head glow."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(18)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._value = 0.0

    def set_value(self, value: float) -> None:
        value = max(0.0, min(100.0, float(value)))
        if abs(value - self._value) > 0.01:
            self._value = value
            self.update()

    def value(self) -> float:
        return self._value

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(0, (self.height() - 6) / 2, self.width(), 6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(rgba(BORDER_RGB, 26))
        painter.drawRoundedRect(track, 3, 3)
        if self._value <= 0:
            return
        width = max(6.0, track.width() * self._value / 100.0)
        fill = QRectF(track.left(), track.top(), width, track.height())
        # The head's halo sits behind the fill, so it reads as a soft edge
        # rather than a grey smudge over the empty track.
        head = QRadialGradient(fill.right(), fill.center().y(), 12)
        head.setColorAt(0.0, QColor(165, 243, 252, 45))
        head.setColorAt(1.0, QColor(165, 243, 252, 0))
        painter.setBrush(head)
        painter.drawEllipse(
            QRectF(fill.right() - 12, fill.center().y() - 12, 24, 24))
        wash = QLinearGradient(fill.topLeft(), fill.topRight())
        wash.setColorAt(0.0, QColor(95, 213, 235, 190))
        wash.setColorAt(1.0, ACCENT_LIGHT)
        painter.setBrush(wash)
        painter.drawRoundedRect(fill, 3, 3)


class StepRow(QWidget):
    """One install phase: a state dot, its label, and a right-hand note."""

    PENDING, ACTIVE, DONE, SKIPPED = "pending", "active", "done", "skipped"

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self._label = label
        self._detail = ""
        self._state = self.PENDING
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self.update)
        self.setFixedHeight(34)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_state(self, state: str, detail: str = "") -> None:
        self._state = state
        self._detail = detail
        if state != self.ACTIVE:
            self._clock.invalidate()
        elif not self._clock.isValid():
            self._clock.start()
        if (state == self.ACTIVE and not self._timer.isActive()
                and motion_enabled()):
            self._timer.start()
        elif state != self.ACTIVE:
            self._timer.stop()
        self.update()

    def state(self) -> str:
        return self._state

    def detail(self) -> str:
        return self._detail

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        mid = self.height() / 2
        centre = QRectF(2, mid - 4, 8, 8)

        if self._state == self.ACTIVE:
            self._paint_spinner(painter, centre.center())
        elif self._state == self.DONE:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ACCENT)
            painter.drawEllipse(centre)
            pen = QPen(QColor(brand.INK), 1.4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            tick = QPainterPath()
            tick.moveTo(centre.left() + 2.0, mid)
            tick.lineTo(centre.left() + 3.6, mid + 1.8)
            tick.lineTo(centre.left() + 6.2, mid - 2.0)
            painter.drawPath(tick)
        else:
            colour = rgba(BORDER_RGB, 70)
            if self._state == self.SKIPPED:
                colour = rgba((95, 213, 235), 90)
            painter.setPen(QPen(colour, 1.2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(centre)

        painter.setFont(ui_font(12.5, QFont.Weight.Medium))
        painter.setPen(TEXT if self._state == self.ACTIVE else
                      (DEVICE_TITLE if self._state == self.DONE else MUTED))
        painter.drawText(QRectF(22, 0, self.width() - 140, self.height()),
                         int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                         self._label)

        if self._detail:
            painter.setFont(ui_font(11))
            painter.setPen(MUTED)
            painter.drawText(
                QRectF(self.width() - 150, 0, 150, self.height()),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight),
                self._detail)


    #: Spinner geometry and timing: one turn per ROTATE_MS while the arc
    #: breathes between ARC_MIN and ARC_MAX degrees every BREATH_MS.
    SPIN_RADIUS = 6.0
    ROTATE_MS = 1100.0
    BREATH_MS = 1700.0
    ARC_MIN, ARC_MAX = 50.0, 230.0

    def _paint_spinner(self, painter: QPainter, centre: QPointF) -> None:
        """The running phase: a soft halo, a faint track, a turning arc."""
        running = self._clock.isValid() and self._timer.isActive()
        elapsed = float(self._clock.elapsed()) if running else 0.0
        radius = self.SPIN_RADIUS

        halo = QRadialGradient(centre, 13)
        halo.setColorAt(0.0, QColor(95, 213, 235, 46))
        halo.setColorAt(1.0, QColor(95, 213, 235, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(centre, 13, 13)

        ring = QRectF(centre.x() - radius, centre.y() - radius,
                      radius * 2, radius * 2)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(rgba(ACCENT, 46), 1.6))
        painter.drawEllipse(ring)

        # The arc's length eases in and out while the whole thing turns,
        # so it reads as work in progress rather than a ticking clock.
        breath = 0.5 - 0.5 * math.cos(2 * math.pi * elapsed / self.BREATH_MS)
        length = self.ARC_MIN + (self.ARC_MAX - self.ARC_MIN) * breath
        head = (90.0 - 360.0 * elapsed / self.ROTATE_MS) % 360.0
        pen = QPen(ACCENT, 1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(ring, int(head * 16), int(-length * 16))


class Badge(QWidget):
    """Round outcome glyph: success tick, error mark or warning mark.

    The widget is larger than the glyph by BLEED on every side so the halo
    and the success ripple are never clipped; pages give it that room in
    the margin they keep for it (see pages.Page.hero).
    """

    SIZE = 80
    BLEED = 16
    #: The success reveal (ring, tick, then one ripple), in ms.
    REVEAL_MS = 1150

    def __init__(self, kind: str = "success", parent=None):
        super().__init__(parent)
        self.kind = kind
        side = self.SIZE + 2 * self.BLEED
        self.setFixedSize(side, side)
        self._t = 1.0
        self._animation = None

    def progress(self) -> float:
        """Where the reveal is, 0..1 (1 when drawn in full)."""
        return self._t

    def play(self) -> None:
        """Draw the glyph in. Shown complete at once without motion."""
        if self._animation is not None:
            self._animation.stop()
        if not motion_enabled():
            self._set_t(1.0)
            return
        animation = QVariantAnimation(self)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setDuration(self.REVEAL_MS)
        animation.valueChanged.connect(self._set_t)
        self._animation = animation
        self._set_t(0.0)
        animation.start()

    def _set_t(self, value) -> None:
        self._t = float(value)
        self.update()

    @staticmethod
    def _tick_path(centre: QPointF) -> QPainterPath:
        """The tick: a short leg and a long one, meeting below centre."""
        path = QPainterPath()
        path.moveTo(centre.x() - 13.0, centre.y() + 0.5)
        path.lineTo(centre.x() - 4.0, centre.y() + 9.5)
        path.lineTo(centre.x() + 14.0, centre.y() - 9.0)
        return path

    @staticmethod
    def _trim(path: QPainterPath, amount: float) -> QPainterPath:
        """The first `amount` (0..1) of a polyline path, by length."""
        if amount >= 1.0:
            return path
        points = []
        for index in range(path.elementCount()):
            element = path.elementAt(index)
            points.append(QPointF(element.x, element.y))
        lengths = [math.hypot(b.x() - a.x(), b.y() - a.y())
                   for a, b in zip(points, points[1:])]
        remaining = sum(lengths) * max(0.0, amount)
        out = QPainterPath(points[0])
        for (a, b), length in zip(zip(points, points[1:]), lengths):
            if remaining >= length:
                out.lineTo(b)
                remaining -= length
                continue
            if remaining > 0 and length > 0:
                f = remaining / length
                out.lineTo(QPointF(a.x() + (b.x() - a.x()) * f,
                                   a.y() + (b.y() - a.y()) * f))
            break
        return out

    def paintEvent(self, event):  # noqa: N802
        colour = {"success": SUCCESS, "error": ERROR,
                  "warning": WARNING}.get(self.kind, ACCENT)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bleed = self.BLEED
        rect = QRectF(bleed, bleed, self.SIZE, self.SIZE)
        centre = rect.center()
        radius = self.SIZE / 2.0
        t = self._t if self.kind == "success" else 1.0

        # Timeline, as fractions of REVEAL_MS: the ring sweeps round, the
        # fill and halo settle under it, the tick strokes in as the ring
        # closes, and one ripple leaves as the tick lands.
        ring = _ease_out(_span(t, 0.0, 0.40))
        fill = _ease_out(_span(t, 0.12, 0.55))
        tick = _ease_out(_span(t, 0.34, 0.66))
        ripple = _span(t, 0.56, 1.0)
        pop = 1.0 + 0.05 * math.sin(math.pi * _span(t, 0.50, 0.80))

        painter.translate(centre)
        painter.scale(pop, pop)
        painter.translate(-centre)

        halo = QRadialGradient(centre, radius + bleed)
        halo.setColorAt(0.0, rgba(colour, int(58 * fill)))
        halo.setColorAt(0.62, rgba(colour, int(22 * fill)))
        halo.setColorAt(1.0, rgba(colour, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(centre, radius + bleed / 1.1, radius + bleed / 1.1)

        if 0.0 < ripple < 1.0:
            reach = radius + 2 + (bleed - 4) * _ease_out(ripple)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(rgba(colour, int(110 * (1.0 - ripple))), 1.4))
            painter.drawEllipse(centre, reach, reach)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(rgba(colour, int(26 * fill)))
        painter.drawEllipse(rect)

        if ring > 0.0:
            ring_pen = QPen(rgba(colour, 165), 1.6)
            ring_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(ring_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            inset = rect.adjusted(0.8, 0.8, -0.8, -0.8)
            if ring >= 1.0:
                painter.drawEllipse(inset)
            else:
                painter.drawArc(inset, 90 * 16, int(-360 * 16 * ring))

        pen = QPen(colour, 3.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self.kind == "success":
            if tick > 0.0:
                painter.drawPath(self._trim(self._tick_path(centre), tick))
        else:
            painter.drawLine(QPointF(centre.x(), centre.y() - 12),
                             QPointF(centre.x(), centre.y() + 4))
            painter.setBrush(colour)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(centre.x(), centre.y() + 12), 2.2, 2.2)


class ElidedLabel(QWidget):
    """A path label that elides in the middle instead of widening the card."""

    def __init__(self, text: str = "", colour: QColor = None, parent=None):
        super().__init__(parent)
        self._text = text
        self._colour = colour if colour is not None else DEVICE_TITLE
        self.setFont(ui_font(12))
        self.setFixedHeight(18)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def setText(self, text: str) -> None:  # noqa: N802
        self._text = text
        self.update()

    def text(self) -> str:
        return self._text

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setPen(self._colour)
        metrics = QFontMetrics(self.font())
        elided = metrics.elidedText(self._text, Qt.TextElideMode.ElideMiddle,
                                    self.width())
        painter.drawText(QRectF(0, 0, self.width(), self.height()),
                         int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                         elided)
