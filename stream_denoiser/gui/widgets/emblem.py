"""
Poise Voice Isolator - Emblem

The About-page brand mark: the app icon inside a full ring of ticks,
echoing the Start/Stop dial. Drawn in a 300-unit square like the dial.
"""
import math

from PyQt6.QtWidgets import QSizePolicy, QWidget
from PyQt6.QtCore import QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap

from ..scaling import sp
from ..themes import current as current_theme

REF = 300.0
TICKS = 72
MAJOR_EVERY = 6
DISC_R = 96.0


class Emblem(QWidget):
    """Icon + tick ring (theme-aware, paint-only)."""

    def __init__(self, size: int = 260, parent=None):
        super().__init__(parent)
        self._px = sp(size)
        self._pixmap = None
        self.setFixedSize(self._px, self._px)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def sizeHint(self):  # noqa: N802 (Qt override)
        return QSize(self._px, self._px)

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self.update()

    def paintEvent(self, event):  # noqa: N802 (Qt override)
        palette = current_theme()
        k = min(self.width(), self.height()) / REF
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.translate(self.width() / 2, self.height() / 2)
        p.scale(k, k)
        accent = QColor(palette["accent"])
        accent.setAlpha(215)
        for i in range(TICKS):
            angle = math.radians(-90 + 360.0 * i / TICKS)
            inner = 110.0 if i % MAJOR_EVERY == 0 else 118.0
            head = i == 0
            pen = QPen(QColor(palette["secondary"]) if head else accent,
                       5.0 if head else 4.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            cs, sn = math.cos(angle), math.sin(angle)
            p.drawLine(QPointF(inner * cs, inner * sn),
                       QPointF(136.0 * cs, 136.0 * sn))
        p.setPen(QPen(QColor(palette["groove"]), 2.0))
        p.setBrush(QColor(palette["pill"]))
        p.drawEllipse(QPointF(0, 0), DISC_R, DISC_R)
        if self._pixmap is not None and not self._pixmap.isNull():
            side = DISC_R * 1.35
            p.drawPixmap(QRectF(-side / 2, -side / 2, side, side),
                         self._pixmap, QRectF(self._pixmap.rect()))
        p.end()
