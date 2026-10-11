"""
Poise Voice Isolator - Pattern Card

A card (QFrame#card) with a faint 8-point-star tile lattice drawn behind
its content. The pattern is strongest at the edges and fades out toward
the middle, so it frames the dial without competing with it.
"""
import math

from PyQt6.QtWidgets import QFrame
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen

from ..scaling import sp
from ..themes import current as current_theme

CELL = 72          # design px per tile
SQUARE = 30.0 / 72  # square side as a fraction of the cell
BASE_ALPHA = 0.13
CARD_RADIUS = 16


def _smoothstep(edge0: float, edge1: float, x: float) -> float:
    if edge1 <= edge0:
        return 1.0
    t = max(0.0, min(1.0, (x - edge0) / (edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)


class PatternCard(QFrame):
    """Card with a radial-faded tile lattice behind its children."""

    def paintEvent(self, event):  # noqa: N802 (Qt override)
        super().paintEvent(event)
        w, h = self.width(), self.height()
        if w < 40 or h < 40:
            return
        cell = float(sp(CELL))
        cx, cy = w / 2.0, h / 2.0
        inner = min(w, h) * 0.55
        outer = max(w, h) * 0.5
        accent = QColor(current_theme()["accent"])

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        radius = float(sp(CARD_RADIUS))
        clip.addRoundedRect(QRectF(1, 1, w - 2, h - 2), radius, radius)
        p.setClipPath(clip)

        side = cell * SQUARE
        dot = cell * 3.0 / 72
        cols = int(w / cell) // 2 + 2
        rows = int(h / cell) // 2 + 2
        for i in range(-cols, cols + 1):
            for j in range(-rows, rows + 1):
                x, y = cx + i * cell, cy + j * cell
                # Keep the headline and hint copy clean: no tiles behind
                # the central text bands (only the corners frame them).
                if 0.12 * w < x < 0.88 * w and (
                        y < 0.2 * h + cell / 2 or y > 0.86 * h - cell / 2):
                    continue
                dist = math.hypot(x - cx, y - cy)
                alpha = BASE_ALPHA * _smoothstep(inner, outer, dist)
                if alpha < 0.012:
                    continue
                col = QColor(accent)
                col.setAlphaF(alpha)
                p.setPen(QPen(col, 1.0))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.save()
                p.translate(x, y)
                p.drawRect(QRectF(-side / 2, -side / 2, side, side))
                p.rotate(45)
                p.drawRect(QRectF(-side / 2, -side / 2, side, side))
                p.restore()
                p.drawEllipse(QPointF(x, y), dot, dot)
        p.end()
