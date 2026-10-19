"""
Poise Setup - painted pieces of the setup window.

Nothing here is stock Qt chrome: the rail, step rows, progress track,
checkbox and status badge all draw themselves from brand.PALETTE, which
is why the setup window can look like Poise without loading any of the
application's widgets.
"""
from __future__ import annotations

from PyQt6.QtCore import QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import (
    QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath,
    QPen, QPixmap, QRadialGradient,
)
from PyQt6.QtWidgets import QAbstractButton, QLabel, QSizePolicy, QWidget

from . import brand

ACCENT = QColor(95, 213, 235)
ACCENT_LIGHT = QColor(165, 243, 252)
GOLD = QColor(232, 196, 104)
TEXT = QColor(248, 250, 252)
MUTED = QColor(139, 148, 163)
DEVICE_TITLE = QColor(154, 163, 178)
BORDER_RGB = (165, 200, 255)
SUCCESS = QColor(74, 222, 128)
ERROR = QColor(248, 113, 113)
WARNING = QColor(250, 204, 21)


def rgba(rgb, alpha: int) -> QColor:
    """QColor from an (r, g, b) tuple and a 0-255 alpha."""
    return QColor(rgb[0], rgb[1], rgb[2], alpha)


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


class Rail(QWidget):
    """The brand rail: lattice texture, emblem, wordmark, tagline."""

    WIDTH = 322

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(self.WIDTH)
        self.setObjectName("rail")

        from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout

        outer = QVBoxLayout(self)
        outer.setContentsMargins(36, 42, 36, 30)
        outer.setSpacing(0)

        emblem = QLabel()
        emblem.setFixedSize(78, 78)
        pixmap = QPixmap(brand.asset("icon.png"))
        if not pixmap.isNull():
            emblem.setPixmap(pixmap.scaled(
                78, 78, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        outer.addWidget(emblem)

        outer.addSpacing(22)
        wordmark = QLabel("POISE")
        wordmark.setObjectName("wordmark")
        wordmark.setFont(heading_font(38, spacing=7.0))
        outer.addWidget(wordmark)

        wordsub = QLabel("VOICE ISOLATOR")
        wordsub.setObjectName("wordsub")
        wordsub.setFont(ui_font(9.5, QFont.Weight.DemiBold, spacing=3.2))
        outer.addWidget(wordsub)

        outer.addSpacing(16)
        outer.addWidget(Ornament())
        outer.addSpacing(14)

        tagline = QLabel("Take back control.")
        tagline.setObjectName("tagline")
        tagline.setFont(ui_font(13, QFont.Weight.Medium))
        outer.addWidget(tagline)

        blurb = QLabel("Everything your PC plays,\nwith the noise taken out.")
        blurb.setObjectName("tagline")
        blurb.setFont(ui_font(11.5))
        blurb.setContentsMargins(0, 6, 0, 0)
        outer.addWidget(blurb)

        outer.addStretch(1)

        version = QLabel(f"Version {brand.version()}")
        version.setObjectName("version")
        version.setFont(ui_font(10.5))
        outer.addWidget(version)

        fine = QLabel("Runs locally  ·  MIT licensed")
        fine.setObjectName("version")
        fine.setFont(ui_font(10))
        fine.setContentsMargins(0, 4, 0, 0)
        outer.addWidget(fine)

    def paintEvent(self, event):  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())

        background = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        background.setColorAt(0.0, QColor(brand.RAIL_TOP))
        background.setColorAt(1.0, QColor(brand.RAIL_BOTTOM))
        painter.fillRect(rect, background)

        glow = QRadialGradient(rect.width() / 2, 138, 250)
        glow.setColorAt(0.0, QColor(95, 213, 235, 30))
        glow.setColorAt(1.0, QColor(95, 213, 235, 0))
        painter.fillRect(rect, glow)

        # The banner's diamond lattice, faint enough to sit behind text.
        painter.setPen(QPen(rgba(BORDER_RGB, 11), 1))
        step = 56
        height = int(rect.height())
        width = int(rect.width())
        for x in range(-height, width + height, step):
            painter.drawLine(x, 0, x + height, height)
            painter.drawLine(x, 0, x - height, height)

        painter.setPen(QPen(rgba(BORDER_RGB, 24), 1))
        painter.drawLine(width - 1, 0, width - 1, height)


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
        return QSize(self.BOX + 12 + metrics.horizontalAdvance(self.text()) + 4,
                     self.height())

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(0, (self.height() - self.BOX) / 2, self.BOX, self.BOX)
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
                box.adjusted(-2.4, -2.4, 2.4, 2.4), 7, 7)

        painter.setFont(self.font())
        painter.setPen(TEXT if (checked or hovered) else DEVICE_TITLE)
        painter.drawText(
            QRectF(self.BOX + 10, 0, self.width() - self.BOX - 10, self.height()),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            self.text())


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
        self._pulse = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)
        self.setFixedHeight(34)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_state(self, state: str, detail: str = "") -> None:
        self._state = state
        self._detail = detail
        if state == self.ACTIVE and not self._timer.isActive():
            self._timer.start()
        elif state != self.ACTIVE:
            self._timer.stop()
        self.update()

    def state(self) -> str:
        return self._state

    def detail(self) -> str:
        return self._detail

    def _tick(self) -> None:
        self._pulse = (self._pulse + 0.04) % 1.0
        self.update()

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        mid = self.height() / 2
        centre = QRectF(2, mid - 4, 8, 8)

        if self._state == self.ACTIVE:
            halo = QRadialGradient(centre.center(), 13)
            halo.setColorAt(0.0, QColor(95, 213, 235, 60))
            halo.setColorAt(1.0, QColor(95, 213, 235, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(halo)
            painter.drawEllipse(QRectF(centre.center().x() - 13, mid - 13, 26, 26))
            painter.setBrush(ACCENT)
            painter.drawEllipse(centre)
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


class Badge(QWidget):
    """Round outcome glyph: success tick, error mark or warning mark."""

    def __init__(self, kind: str = "success", parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setFixedSize(64, 64)

    def paintEvent(self, event):  # noqa: N802
        colour = {"success": SUCCESS, "error": ERROR,
                  "warning": WARNING}.get(self.kind, ACCENT)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(1, 1, self.width() - 2, self.height() - 2)

        halo = QRadialGradient(rect.center(), 34)
        halo.setColorAt(0.0, QColor(colour.red(), colour.green(), colour.blue(), 60))
        halo.setColorAt(1.0, QColor(colour.red(), colour.green(), colour.blue(), 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(QRectF(-10, -10, self.width() + 20, self.height() + 20))

        painter.setBrush(QColor(colour.red(), colour.green(), colour.blue(), 22))
        painter.setPen(QPen(QColor(colour.red(), colour.green(), colour.blue(), 150), 1.2))
        painter.drawEllipse(rect)

        pen = QPen(colour, 2.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        centre = rect.center()
        if self.kind == "success":
            tick = QPainterPath()
            tick.moveTo(centre.x() - 9, centre.y() + 0.5)
            tick.lineTo(centre.x() - 3, centre.y() + 6.5)
            tick.lineTo(centre.x() + 9.5, centre.y() - 6.5)
            painter.drawPath(tick)
        else:
            painter.drawLine(int(centre.x()), int(centre.y() - 8),
                             int(centre.x()), int(centre.y() + 3))
            painter.setBrush(colour)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QRectF(centre.x() - 1.6, centre.y() + 7.6, 3.2, 3.2))


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
