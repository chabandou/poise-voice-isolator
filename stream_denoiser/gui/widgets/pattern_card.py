"""
Poise Voice Isolator - Pattern Card

A card (QFrame#card) with the gilded lattice drawn behind its content:
a 64px tile of a square, its 45-degree twin, spokes to the tile edges
and a centre dot, all in the theme's secondary colour. The lattice is
painted at 20% opacity through an elliptical radial mask, clear in the
middle (where the dial sits) and full strength at the edges. While
isolating it glides to the accent colour, matching the dial's ring.

While isolating the lattice also pings: a ring of accent-coloured
lattice leaves the dial (set_ping_origin) and crosses the card. The
first goes out as the dial's live sweep closes (start_pings), then a
fainter one every PING_PERIOD_MS; the dial charges up before each of
those (see DialButton). The ring lights the bare lattice, so it shows
in the clear middle too. Stopping (stop_pings, from the moment Stop is
pressed) sends no more rings; one already crossing fades out over
PING_FADE_MS rather than vanishing.

Ported from the design's SVG (<pattern> + <radialGradient> mask), so the
numbers below are the design's own: tile 64, offset (-14, -6), stroke 1,
dot r 2.5, opacity .2, mask centre (.5, .55), radius .72, stops .4 -> 1.
"""
import time

from PyQt6.QtWidgets import QFrame
from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import (QBrush, QColor, QImage, QPainter, QPainterPath,
                         QPen, QRadialGradient, QTransform)

from ..animations import Blend, EASE_BREATHE, motion_ok
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

PING_PERIOD_MS = 5200       # between lattice pings while isolating
PING_FIRST_MS = 1600        # the first ring's flight...
PING_LOOP_MS = 2340         # ...and the later, slower ones'
PING_FIRST_ALPHA = 0.85
PING_LOOP_ALPHA = 0.32
PING_FROM, PING_TO = 70.0, 720.0   # ring radius, design px
PING_BAND = 80.0            # the ring: clear this far inside its edge,
PING_CORE = 22.0            # full strength this far inside it
PING_FRAME_MS = 33
PING_FADE_MS = 420          # a ring in flight when pings stop fades out


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


def _tint(layer: QImage, color: QColor) -> QImage:
    """A white layer recoloured (alpha kept)."""
    tinted = layer.copy()
    p = QPainter(tinted)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(QRectF(0, 0, tinted.width(), tinted.height()), color)
    p.end()
    return tinted


class PatternCard(QFrame):
    """Card with a radial-masked gilded lattice behind its children."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layer_key = self._layer = None   # masked lattice, white
        self._tint_key = self._tinted = None   # the same, coloured
        self._bare_key = self._bare = None     # unmasked lattice, white
        self._ping_key = self._ping_layer = None   # the same, accent
        self._tile = _tile_path()
        self._live = Blend(self, self.update, LIVE_FADE_MS, EASE_BREATHE)
        self._origin = None                    # the dial the pings leave
        self._ping_at = None
        self._ping_end = None                  # pings stopped: ring fades
        self._pinging = False                  # a ring is on screen
        self._ping_timer = QTimer(self)
        self._ping_timer.setInterval(PING_FRAME_MS)
        self._ping_timer.timeout.connect(self._ping_tick)

    def set_live(self, live: bool, animated: bool = True) -> None:
        """Secondary colour when idle, the accent while isolating."""
        self._live.set_target(1.0 if live else 0.0, animated)
        if not live:
            self.stop_pings(fade=animated)

    # -- pings ------------------------------------------------------------------
    def set_ping_origin(self, widget) -> None:
        """The (descendant) widget whose centre the pings leave from."""
        self._origin = widget

    def start_pings(self) -> None:
        """First ping now, then one every PING_PERIOD_MS until stopped."""
        if not motion_ok():
            return
        self._ping_at = time.monotonic()
        self._ping_end = None
        self._ping_timer.start()
        self.update()

    def stop_pings(self, fade: bool = True) -> None:
        """No more pings. A ring already crossing fades out (vanishes
        with fade=False or under reduced motion)."""
        if self._ping_at is None:
            return
        if fade and self._ping_end is not None:
            return                             # already fading out
        if fade and motion_ok() and self._ping_frame() is not None:
            self._ping_end = time.monotonic()
            if self.isVisible():
                self._ping_timer.start()
            return
        self._clear_pings()

    @property
    def pinging(self) -> bool:
        """Pings are scheduled (False once stopped, even mid-fade)."""
        return self._ping_at is not None and self._ping_end is None

    def _clear_pings(self) -> None:
        self._ping_at = self._ping_end = None
        self._ping_timer.stop()
        if self._pinging:
            self._pinging = False
            self.update()

    def showEvent(self, event):  # noqa: N802 (Qt override)
        super().showEvent(event)
        if self._ping_at is not None:
            self._ping_timer.start()

    def hideEvent(self, event):  # noqa: N802 (Qt override)
        self._ping_timer.stop()   # e.g. hidden to the tray: no wake-ups
        super().hideEvent(event)

    def _ping_tick(self) -> None:
        if not self.isVisible():
            return
        on = self._ping_frame() is not None
        if on or self._pinging:   # one more frame clears the last ring
            self.update()
        self._pinging = on
        if not on and self._ping_end is not None:
            self._clear_pings()   # the fading ring is gone: all done

    def _ping_frame(self):
        """(radius in design px, alpha) of the ring on screen, or None."""
        if self._ping_at is None:
            return None
        now = time.monotonic()
        t = (now - self._ping_at) * 1000.0
        index = int(t // PING_PERIOD_MS)
        into = t - index * PING_PERIOD_MS
        span = PING_FIRST_MS if index == 0 else PING_LOOP_MS
        if into >= span:
            return None
        fade = 1.0
        if self._ping_end is not None:
            stopped = (self._ping_end - self._ping_at) * 1000.0
            if index * PING_PERIOD_MS > stopped:
                return None                    # no ring after Stop
            u = (now - self._ping_end) * 1000.0 / PING_FADE_MS
            if u >= 1.0:
                return None
            fade = (1.0 - u) ** 2              # eases out to nothing
        eased = 1.0 - (1.0 - into / span) ** 3
        alpha = PING_FIRST_ALPHA if index == 0 else PING_LOOP_ALPHA
        return (PING_FROM + (PING_TO - PING_FROM) * eased,
                alpha * (1 - eased) * fade)

    def _ping_centre(self):
        origin = self._origin
        if origin is None or not origin.isVisible():
            return None
        return QPointF(origin.mapTo(self, origin.rect().center()))

    # -- painting ------------------------------------------------------------------
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
        frame = self._ping_frame()
        centre = self._ping_centre() if frame is not None else None
        if centre is not None:
            self._paint_ping(p, w, h, centre, *frame)
        p.end()

    def _paint_ping(self, p, w, h, centre, radius, alpha) -> None:
        """The accent lattice, seen only through a ring around `centre`."""
        r = radius * ui_scale()
        box = QRectF(centre.x() - r, centre.y() - r, 2 * r, 2 * r)
        box = box.intersected(QRectF(0, 0, w, h)).toAlignedRect()
        if box.isEmpty() or r <= 0:
            return
        layer = self._ping_image(w, h)
        dpr = self.devicePixelRatioF()
        ring = QImage(round(box.width() * dpr), round(box.height() * dpr),
                      QImage.Format.Format_ARGB32_Premultiplied)
        ring.setDevicePixelRatio(dpr)
        ring.fill(Qt.GlobalColor.transparent)
        q = QPainter(ring)
        q.drawImage(QPointF(-box.x(), -box.y()), layer)
        k = ui_scale()
        grad = QRadialGradient(
            QPointF(centre.x() - box.x(), centre.y() - box.y()), r)
        grad.setColorAt(max(0.0, (r - PING_BAND * k) / r),
                        QColor(255, 255, 255, 0))
        grad.setColorAt(max(0.0, (r - PING_CORE * k) / r),
                        QColor(255, 255, 255, 255))
        grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        q.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_DestinationIn)
        q.fillRect(QRectF(0, 0, box.width(), box.height()), QBrush(grad))
        q.end()
        p.setOpacity(alpha)
        p.drawImage(QPointF(box.topLeft()), ring)

    def _tinted_image(self, w: int, h: int, color: QColor) -> QImage:
        """The masked lattice in `color` (recoloured, not redrawn)."""
        layer = self._pattern_image(w, h)
        key = (self._layer_key, color.rgb())
        if key != self._tint_key:
            self._tint_key, self._tinted = key, _tint(layer, color)
        return self._tinted

    def _ping_image(self, w: int, h: int) -> QImage:
        """The unmasked lattice in the accent colour."""
        layer = self._lattice(w, h, masked=False)
        color = QColor(current_theme()["accent"])
        key = (self._bare_key, color.rgb())
        if key != self._ping_key:
            self._ping_key, self._ping_layer = key, _tint(layer, color)
        return self._ping_layer

    def _pattern_image(self, w: int, h: int) -> QImage:
        """Masked white lattice for the current size, scale and DPR."""
        return self._lattice(w, h, masked=True)

    def _lattice(self, w: int, h: int, masked: bool) -> QImage:
        """White lattice, through the radial mask or bare (cached)."""
        from ..styles import _card_border_width
        k = ui_scale()
        dpr = self.devicePixelRatioF()
        key = (w, h, k, dpr)
        if masked and key == self._layer_key:
            return self._layer
        if not masked and key == self._bare_key:
            return self._bare

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

        if masked:
            # Mask: alpha 0 out to 40% of the radius, ramping to 1 at the
            # rim (and padded beyond). The unit gradient is stretched to
            # the box, as objectBoundingBox units are in SVG.
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
            p.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_DestinationIn)
            p.fillRect(QRectF(0, 0, w, h), brush)
        p.end()

        if masked:
            self._layer_key, self._layer = key, image
        else:
            self._bare_key, self._bare = key, image
        return image
