"""
Poise Voice Isolator - Power Button Widget

Large circular glowing power button matching the mockup: cyan disc with
an outer glow while active, dark disc while idle, red ring on error.
Keeps the old ToggleButton signal API (toggled_state / set_active /
set_transitioning / is_active) so MainWindow wiring is unchanged.
"""
from PyQt6.QtWidgets import QAbstractButton, QSizePolicy
from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QRadialGradient, QPen, QFont,
)

from ..scaling import sp
from ..themes import current as current_theme


class PowerButton(QAbstractButton):
    """Glowing circular power button."""

    toggled_state = pyqtSignal(bool)  # True = started, False = stopped

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setMinimumSize(self.sizeHint())

        self._is_active = False
        self._is_transitioning = False
        self._has_error = False

        self.clicked.connect(self._on_clicked)

    def sizeHint(self):  # noqa: N802 (Qt override)
        return QSize(sp(210), sp(210))

    # -- state API (matches old ToggleButton) -------------------------------
    def _on_clicked(self):
        if self._is_transitioning:
            return
        self._is_active = not self._is_active
        self._has_error = False
        self.update()
        self.toggled_state.emit(self._is_active)

    def set_active(self, active: bool):
        self._is_active = active
        if active:
            self._has_error = False
        self.update()

    def set_transitioning(self, transitioning: bool):
        self._is_transitioning = transitioning
        self.setEnabled(not transitioning)
        self.update()

    def set_error(self, error: bool = True):
        self._has_error = error
        self.update()

    @property
    def is_active(self) -> bool:
        return self._is_active

    # -- painting ------------------------------------------------------------
    def paintEvent(self, event):  # noqa: N802 (Qt override)
        s = min(self.width(), self.height())
        cx = cy = s / 2
        disc_r = s * 0.36
        ring_r = s * 0.42

        active = self._is_active
        error = self._has_error
        palette = current_theme()
        accent = QColor(palette["accent"])

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Outer glow.
        glow = QRadialGradient(cx, cy, s * 0.5)
        if error:
            glow.setColorAt(0.0, QColor(239, 68, 68, 90))
        elif active:
            glow.setColorAt(0.0, QColor(
                accent.red(), accent.green(), accent.blue(), 110))
        else:
            glow.setColorAt(0.0, QColor(
                accent.red(), accent.green(), accent.blue(), 28))
        glow.setColorAt(1.0, QColor(
            accent.red(), accent.green(), accent.blue(), 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(int(cx - s * 0.5), int(cy - s * 0.5), int(s), int(s))

        # Ring.
        if error:
            ring_color = QColor("#f87171")
        elif active:
            ring_color = accent.lighter(125)
        else:
            ring_color = QColor(palette["muted"])
            ring_color.setAlpha(90)
        p.setPen(QPen(ring_color, 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(int(cx - ring_r), int(cy - ring_r),
                      int(ring_r * 2), int(ring_r * 2))

        # Disc.
        disc = QRadialGradient(cx - disc_r * 0.25, cy - disc_r * 0.3, disc_r * 1.4)
        if active:
            disc.setColorAt(0.0, accent.lighter(140))
            disc.setColorAt(1.0, accent)
        else:
            card = QColor(palette["card"])
            disc.setColorAt(0.0, card.lighter(135))
            disc.setColorAt(1.0, card)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(disc)
        p.drawEllipse(int(cx - disc_r), int(cy - disc_r),
                      int(disc_r * 2), int(disc_r * 2))

        # Power glyph: 300-degree arc + vertical line.
        if active:
            glyph = QColor(palette["bg"])
        elif error:
            glyph = QColor("#f87171")
        else:
            glyph = QColor(palette["muted"]).darker(140)
        pen = QPen(glyph, disc_r * 0.085)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        arc_box = disc_r * 0.336
        # Gap at the top: start 120deg, span 300deg (Qt: 0deg = 3 o'clock).
        p.drawArc(int(cx - arc_box), int(cy - arc_box),
                  int(arc_box * 2), int(arc_box * 2),
                  120 * 16, 300 * 16)
        p.drawLine(int(cx), int(cy - disc_r * 0.336), int(cx), int(cy - disc_r * 0.014))

        # State text.
        if self._is_transitioning:
            text = "..."
        elif error and not active:
            text = "ERR"
        else:
            text = "ON" if active else "OFF"
        p.setPen(glyph)
        p.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        p.drawText(int(cx - disc_r), int(cy + disc_r * 0.55),
                   int(disc_r * 2), 24, Qt.AlignmentFlag.AlignCenter, text)
        p.end()
