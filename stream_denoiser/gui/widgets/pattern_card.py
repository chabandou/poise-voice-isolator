"""
Poise Voice Isolator - Pattern Card

A card (QFrame#card) with the gilded lattice drawn behind its content:
a 64px tile of a square, its 45-degree twin, spokes to the tile edges
and a centre dot, all in the theme's secondary colour. The lattice is
painted at 20% opacity through an elliptical radial mask, clear in the
middle (where the dial sits) and full strength at the edges. While
isolating it glides to the accent colour, matching the dial's ring.

Ported from the design's SVG (<pattern> + <radialGradient> mask), so the
numbers below are the design's own: tile 64, offset (-14, -6), stroke 1,
dot r 2.5, opacity .2, mask centre (.5, .55), radius .72, stops .4 -> 1.
"""
from PyQt6.QtWidgets import QFrame
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (QBrush, QColor, QImage, QPainter, QPainterPath,
                         QPen, QRadialGradient, QTransform)

from ..animations import Blend, EASE_BREATHE
from ..scaling import ui_scale
from ..themes import current as current_theme

TILE = 64.0                 # design px per tile
TILE_OFFSET = (-14.0, -6.0)  # pattern x/y: where the first tile starts
STROKE = 1.0
DOT_RADIUS = 2.5
OPACITY = 0.2
# Radial mask in bounding-box units (elliptical on a non-square card).
MASK_CENTER = (0.5, 0.55)
MASK_RADIUS = 0.72
MASK_CLEAR_STOP = 0.4       # fully hidden inside this fraction of the radius
CARD_RADIUS = 16
LIVE_FADE_MS = 600          # idle <-> live colour glide


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(round(a.red() + (b.red() - a.red()) * t),
                  round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t))


def _tile_path() -> QPainterPath:
    """Line work of one 64x64 tile, in design units."""
    path = QPainterPath()
    path.addRect(QRectF(21, 21, 22, 22))
    # The same square rotated 45 degrees about the tile centre.
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


class PatternCard(QFrame):
    """Card with a radial-masked gilded lattice behind its children."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layer_key = self._layer = None   # masked lattice, white
        self._tint_key = self._tinted = None   # the same, coloured
        self._tile = _tile_path()
        self._live = Blend(self, self.update, LIVE_FADE_MS, EASE_BREATHE)

    def set_live(self, live: bool, animated: bool = True) -> None:
        """Secondary colour when idle, the accent while isolating."""
        self._live.set_target(1.0 if live else 0.0, animated)

    def paintEvent(self, event):  # noqa: N802 (Qt override)
        super().paintEvent(event)
        w, h = self.width(), self.height()
        if w < 40 or h < 40:
            return
        palette = current_theme()
        color = _mix(QColor(palette["secondary"]), QColor(palette["accent"]),
                     self._live.value)
        image = self._tinted_image(w, h, color)
        p = QPainter(self)
        p.setOpacity(OPACITY)
        p.drawImage(0, 0, image)
        p.end()

    def _tinted_image(self, w: int, h: int, color: QColor) -> QImage:
        """The masked lattice in `color` (recoloured, not redrawn)."""
        layer = self._pattern_image(w, h)
        key = (self._layer_key, color.rgb())
        if key != self._tint_key:
            tinted = layer.copy()
            p = QPainter(tinted)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            p.fillRect(QRectF(0, 0, w, h), color)
            p.end()
            self._tint_key, self._tinted = key, tinted
        return self._tinted

    def _pattern_image(self, w: int, h: int) -> QImage:
        """Masked white lattice for the current size, scale and DPR."""
        from ..styles import _card_border_width
        k = ui_scale()
        dpr = self.devicePixelRatioF()
        key = (w, h, k, dpr)
        if key == self._layer_key:
            return self._layer

        image = QImage(round(w * dpr), round(h * dpr),
                       QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(dpr)
        image.fill(Qt.GlobalColor.transparent)

        # The SVG fills the card's padding box (inside the border), and
        # the card's rounded corners clip it.
        b = float(_card_border_width(k))
        box = QRectF(b, b, w - 2 * b, h - 2 * b)
        radius = max(0.0, CARD_RADIUS * k - b)
        clip = QPainterPath()
        clip.addRoundedRect(box, radius, radius)

        p = QPainter(image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setClipPath(clip)
        ink = QColor(Qt.GlobalColor.white)
        pen = QPen(ink, STROKE)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)    # SVG butt caps
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)

        # Paint the tiles opaque; the 20% opacity applies to the whole
        # layer afterwards, so crossings do not double up.
        cell = TILE * k
        ox = box.x() + TILE_OFFSET[0] * k
        oy = box.y() + TILE_OFFSET[1] * k
        cols = int(box.width() / cell) + 2
        rows = int(box.height() / cell) + 2
        for i in range(cols):
            for j in range(rows):
                p.save()
                p.translate(ox + i * cell, oy + j * cell)
                p.scale(k, k)
                # SVG patterns clip each tile to its own cell.
                p.setClipRect(QRectF(0, 0, TILE, TILE),
                              Qt.ClipOperation.IntersectClip)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(self._tile)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(ink)
                p.drawEllipse(QPointF(32, 32), DOT_RADIUS, DOT_RADIUS)
                p.restore()

        # Mask: alpha 0 out to 40% of the radius, ramping to 1 at the
        # rim (and padded beyond). The unit gradient is stretched to the
        # box, as objectBoundingBox units are in SVG.
        grad = QRadialGradient(QPointF(0, 0), 1.0)
        grad.setColorAt(MASK_CLEAR_STOP, QColor(255, 255, 255, 0))
        grad.setColorAt(1.0, QColor(255, 255, 255, 255))
        grad.setSpread(QRadialGradient.Spread.PadSpread)
        brush = QBrush(grad)
        brush.setTransform(
            QTransform()
            .scale(MASK_RADIUS * box.width(), MASK_RADIUS * box.height())
            * QTransform().translate(
                box.x() + MASK_CENTER[0] * box.width(),
                box.y() + MASK_CENTER[1] * box.height()))
        p.setClipping(False)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        p.fillRect(QRectF(0, 0, w, h), brush)
        p.end()

        self._layer_key, self._layer = key, image
        return image
