"""
Poise Voice Isolator - Donate button

A filled call-to-action in the theme's secondary colour (dark label and
icon). Hover draws a ring in the text colour, set off from the button by
a small gap: the same outline language as the selected theme tile.

The fill and ring are painted here (QSS can't draw an offset outline or
fade); the label and icon come from the stylesheet, which leaves the
background transparent.
"""
from PyQt6.QtWidgets import QPushButton
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen

from ..animations import Blend, mix_rgba
from ..scaling import sp
from ..themes import current as current_theme

RING_WIDTH = 2   # design px
RING_GAP = 3
RADIUS = 10


class DonateButton(QPushButton):
    """Secondary-filled button with an eased, offset hover ring."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setObjectName("donate")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ring = Blend(self, self.update, 150)

    def enterEvent(self, event):  # noqa: N802 (Qt override)
        if self.isEnabled():
            self._ring.set_target(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802 (Qt override)
        self._ring.set_target(0.0)
        super().leaveEvent(event)

    def paintEvent(self, event):  # noqa: N802 (Qt override)
        palette = current_theme()
        w, h = self.width(), self.height()
        inset = float(sp(RING_WIDTH + RING_GAP))
        radius = float(sp(RADIUS))

        fill = QColor(palette["secondary"])
        if self.isDown():                       # a touch deeper when pressed
            fill = mix_rgba(fill, QColor(palette["bg"]), 0.14)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(QRectF(inset, inset, w - 2 * inset, h - 2 * inset),
                          radius, radius)

        t = self._ring.value
        if t > 0.01:
            ring = QColor(palette["text"])
            ring.setAlphaF(t)
            ring_w = float(sp(RING_WIDTH))
            pen = QPen(ring, ring_w)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            half = ring_w / 2.0
            p.drawRoundedRect(QRectF(half, half, w - ring_w, h - ring_w),
                              radius + sp(RING_GAP), radius + sp(RING_GAP))
        p.end()
        super().paintEvent(event)               # icon + label (QSS)
