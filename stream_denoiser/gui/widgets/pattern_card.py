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

A theme whose backdrop is "sky" (Vigil, Eclipse) gets the night sky instead (see
widgets/sky.py): always gently moving, so it runs its own clock while
shown (SKY_FRAME_MS, faster while starting and isolating, and for the
moment a shooting star crosses). Its pulses
follow the same calls, on the dial's breathing cycle (BREATH_MS) rather
than PING_PERIOD_MS, and it also follows the dial's phase (set_phase) to
draw in while starting. Where Qt Quick can run, the sky is drawn on the
GPU by a view covering the card (widgets/sky_gpu.py; it draws the card
too, and the dial's ring of ticks: see DialButton.set_ring_sink);
otherwise, or with POISE_SKY_RASTER=1, it is painted here. With the
ambient motion still (animations.ambient_ok: Reduce motion in Settings)
there is no GPU view: one still sky is painted here and kept.
"""
import math
import time

from PyQt6.QtWidgets import QFrame
from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, QTimer
from PyQt6.QtGui import (QBrush, QColor, QImage, QPainter, QPainterPath,
                         QPen, QRadialGradient, QRegion, QTransform)

from ..animations import Blend, EASE_BREATHE, FrameTimer, ambient_ok
from ...logging_config import get_logger
from ..scaling import ui_scale
from ..themes import current as current_theme, style as theme_style
from .sky import BREATH_MS, PULSE_FADE_MS, NightSky, meteor_due

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

SKY_FRAME_MS = 100          # the night sky's slow loops, at rest...
SKY_LIVE_FRAME_MS = 33      # ...its pulses and the starting draw-in...
SKY_METEOR_FRAME_MS = 16    # ...and a shooting star's second of flight
SKY_LIVE_FADE_MS = 2400     # gold <-> lavender, as slowly as it breathes
SKY_GATHER_MS = 600         # into and out of the starting draw-in
SKY_REVEAL_DELAY_MS = 300   # first show: the sky surfaces...
SKY_REVEAL_MS = 2400        # ...slowly

_logger = get_logger(__name__)


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
        self._live = Blend(self, self._changed, LIVE_FADE_MS, EASE_BREATHE)
        self._origin = None                    # the dial the pings leave
        self._ping_at = None
        self._ping_end = None                  # pings stopped: ring fades
        self._pinging = False                  # a ring is on screen
        self._ping_region = QRegion()          # where it was painted last
        self._ping_timer = FrameTimer(self)
        self._ping_timer.setInterval(PING_FRAME_MS)
        self._ping_timer.timeout.connect(self._ping_tick)

        # The night sky (sky backdrop only; built on first use).
        self._sky = None
        self._phase = "idle"
        self._gather_at = time.monotonic()   # the starting draw-in began
        self._gather = Blend(self, self._changed, SKY_GATHER_MS,
                             EASE_BREATHE)
        self._error = Blend(self, self._changed, SKY_LIVE_FADE_MS,
                            EASE_BREATHE)
        self._reveal = Blend(self, self._changed, SKY_REVEAL_MS)
        self._revealed = False
        self._sky_timer = FrameTimer(self)
        self._sky_timer.setInterval(SKY_FRAME_MS)
        self._sky_timer.timeout.connect(self._sky_tick)
        # The sky on the GPU (made on first show; None paints it here).
        self._view = None
        self._view_failed = self._making_view = False
        self._base_key = self._base = None
        self._still_key = self._still = None   # the sky holding still

    def _sky_on(self) -> bool:
        return theme_style("backdrop") == "sky"

    def _changed(self) -> None:
        """What the backdrop shows moved: the GPU sky's next frame, or a
        repaint."""
        if self._view is not None:
            self._show_sky_frame()
        else:
            self.update()

    def set_live(self, live: bool, animated: bool = True) -> None:
        """Secondary colour when idle, the accent while isolating."""
        self._live.set_target(
            1.0 if live else 0.0, animated and ambient_ok(),
            duration_ms=SKY_LIVE_FADE_MS if self._sky_on() else LIVE_FADE_MS)
        if not live:
            self.stop_pings(fade=animated)
        self._run_sky()

    def set_phase(self, phase: str) -> None:
        """The dial's phase (idle | starting | live | stopping | error):
        the sky draws in while starting and dims its aura on an error."""
        if phase == self._phase:
            return
        self._phase = phase
        if phase == "starting":
            self._gather_at = time.monotonic()
        animated = self.isVisible() and ambient_ok()
        self._gather.set_target(1.0 if phase == "starting" else 0.0, animated)
        self._error.set_target(1.0 if phase == "error" else 0.0, animated)
        self._run_sky()

    def refresh_motion(self) -> None:
        """Reduce motion changed (animations.set_still): the GPU sky
        goes (one still sky painted here) or comes back, and the clocks
        follow."""
        if not ambient_ok():
            self._ping_timer.stop()
            self._reveal.snap(1.0)
            for blend in (self._live, self._gather, self._error):
                blend.snap(blend.target)
            if self._ping_end is not None:
                self._clear_pings()
        elif self._ping_at is not None and not self._sky_on()                 and self.isVisible():
            self._ping_timer.start()
        self._sync_view()
        self._run_sky()
        self._changed()

    def refresh_theme(self) -> None:
        """The theme changed: switch backdrops (and their clocks)."""
        if self._sky_on():
            self._reveal.snap(1.0)
            self._revealed = True
            self._ping_timer.stop()
            if self._ping_at is not None and self._ping_end is None:
                # Mid-isolation: carry on breathing from now.
                self._ping_at = time.monotonic()
        else:
            self._sky_timer.stop()
            if self._ping_at is not None and self.isVisible():
                self._ping_timer.start()
        self._live.snap(self._live.target)
        self._sync_view()
        self._run_sky()
        self._changed()
        self.update()

    # -- pings ------------------------------------------------------------------
    def set_ping_origin(self, widget) -> None:
        """The (descendant) widget whose centre the pings leave from."""
        if self._view is not None:
            self._hand_ring(False)
        self._origin = widget
        if self._view is not None:
            self._hand_ring(True)

    def start_pings(self) -> None:
        """First ping now, then one every PING_PERIOD_MS until stopped."""
        if not ambient_ok():
            return
        self._ping_at = time.monotonic()
        self._ping_end = None
        if self._sky_on():
            self._run_sky()                    # a breath starts now
        else:
            self._ping_timer.start()
        self.update()

    def stop_pings(self, fade: bool = True) -> None:
        """No more pings. A ring already crossing fades out (vanishes
        with fade=False or under reduced motion)."""
        if self._ping_at is None:
            return
        if fade and self._ping_end is not None:
            return                             # already fading out
        if self._sky_on():
            # The sky keeps its rhythm while it fades back to gold; only
            # the pulse in flight fades and no new one leaves.
            if fade and ambient_ok():
                self._ping_end = time.monotonic()
                self._run_sky()
            else:
                self._clear_pings()
            return
        if fade and ambient_ok() and self._ping_frame() is not None:
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
            self.update(self._ping_region)
        self._ping_region = QRegion()

    def showEvent(self, event):  # noqa: N802 (Qt override)
        super().showEvent(event)
        if not self._revealed:
            self._revealed = True
            if self._sky_on() and ambient_ok():
                QTimer.singleShot(SKY_REVEAL_DELAY_MS, self._begin_reveal)
            else:
                self._reveal.snap(1.0)
        if self._ping_at is not None and not self._sky_on():
            self._ping_timer.start()
        self._sync_view()
        self._run_sky()

    def resizeEvent(self, event):  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        if self._view is not None:
            self._view.setGeometry(self.rect())
            self._show_sky_frame()

    def hideEvent(self, event):  # noqa: N802 (Qt override)
        self._ping_timer.stop()   # e.g. hidden to the tray: no wake-ups
        self._sky_timer.stop()
        super().hideEvent(event)

    # -- the night sky's clock -----------------------------------------------------
    def _begin_reveal(self) -> None:
        self._reveal.set_target(1.0, self.isVisible() and ambient_ok())

    def _run_sky(self) -> None:
        """Run the sky's clock while it is shown (faster while it pulses
        or draws in)."""
        if not (self._sky_on() and ambient_ok() and self.isVisible()):
            self._sky_timer.stop()
            return
        busy = (self._ping_at is not None or self._live.target > 0
                or self._live.value > 0.001 or self._phase == "starting"
                or self._gather.value > 0.001)
        interval = SKY_LIVE_FRAME_MS if busy else SKY_FRAME_MS
        if meteor_due(time.monotonic() * 1000.0, interval):
            interval = SKY_METEOR_FRAME_MS
        if self._sky_timer.interval() != interval:
            self._sky_timer.setInterval(interval)
        if not self._sky_timer.isActive():
            self._sky_timer.start()

    def _sky_tick(self) -> None:
        if (self._ping_end is not None and self._live.value <= 0.001
                and (time.monotonic() - self._ping_end) * 1000.0
                >= PULSE_FADE_MS):
            self._clear_pings()   # faded back to gold: the breath ends
        self._run_sky()
        self._changed()

    def _pulse_gain(self, index: int, now: float) -> float:
        """How much of breath `index`'s pulse to show: all of it while
        isolating; after Stop the one in flight fades and none follow."""
        if self._ping_end is None:
            return 1.0
        stopped = (self._ping_end - self._ping_at) * 1000.0
        if index * BREATH_MS > stopped:
            return 0.0
        u = (now - self._ping_end) * 1000.0 / PULSE_FADE_MS
        return 0.0 if u >= 1.0 else (1.0 - u) ** 2

    def _ping_tick(self) -> None:
        if not self.isVisible():
            return
        frame = self._ping_frame()
        on = frame is not None
        if on or self._pinging:   # one more frame clears the last ring
            # Only where the ring is, or just was: not the card (or the
            # dial over it) as a whole.
            region = QRegion()
            centre = self._ping_centre() if on else None
            if centre is not None:
                region = self._ring_region(centre, frame[0])
            self.update(region.united(self._ping_region))
            self._ping_region = region
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

    def _ring_region(self, centre: QPointF, radius: float) -> QRegion:
        """Where a ping ring of `radius` (design px) can draw: its box, less
        the square inside the clear middle of the ring (see _paint_ping)."""
        k = ui_scale()
        r = radius * k
        outer = QRectF(centre.x() - r, centre.y() - r, 2 * r, 2 * r)
        region = QRegion(outer.toAlignedRect().adjusted(-2, -2, 2, 2))
        half = (r - PING_BAND * k) / math.sqrt(2.0) - 2.0
        if half > 0:
            region = region.subtracted(QRegion(QRectF(
                centre.x() - half, centre.y() - half, 2 * half, 2 * half
            ).toRect()))
        return region.intersected(QRegion(self.rect()))

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
        if self._sky_on():
            if self._view is None:
                self._paint_sky(w, h)
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
            self._paint_ping(p, w, h, centre, *frame,
                             within=event.region())
        p.end()

    def _paint_sky(self, w: int, h: int) -> None:
        """The night sky, centred on the dial and clipped to the card."""
        moment = self._sky_moment(w, h)
        p = QPainter(self)
        if moment[-1]["moving"]:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._sky.paint(p, *moment)
        else:
            p.drawImage(0, 0, self._still_sky(w, h, moment))
        p.end()

    def _still_sky(self, w: int, h: int, moment) -> QImage:
        """The sky holding still (at `moment`, see _sky_moment), painted
        once and kept until what it shows changes: the dial repaints over
        it on every hover."""
        box, clip, centre, k, ui, now, look = moment
        dpr = self.devicePixelRatioF()
        key = (w, h, dpr, centre.x(), centre.y(), k, ui) + tuple(
            (name, v.rgba() if isinstance(v, QColor) else v)
            for name, v in sorted(look.items()) if not callable(v))
        if key != self._still_key:
            image = QImage(round(w * dpr), round(h * dpr),
                           QImage.Format.Format_ARGB32_Premultiplied)
            image.setDevicePixelRatio(dpr)
            image.fill(Qt.GlobalColor.transparent)
            q = QPainter(image)
            q.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._sky.paint(q, *moment)
            q.end()
            self._still_key, self._still = key, image
        return self._still

    def _sky_moment(self, w: int, h: int):
        """(box, clip, centre, k, ui, now, look): where the sky goes in
        the card and the moment to draw (see NightSky.frame)."""
        from ..styles import _card_border_width
        ui = ui_scale()
        b = float(_card_border_width(ui))
        box = QRectF(b, b, w - 2 * b, h - 2 * b)
        radius = max(0.0, CARD_RADIUS * ui - b)
        clip = QPainterPath()
        clip.addRoundedRect(box, radius, radius)
        centre = self._ping_centre() or QPointF(w / 2, h * 0.55)
        origin = self._origin
        k = (min(origin.width(), origin.height()) / 300.0
             if origin is not None else ui)
        if self._sky is None:
            self._sky = NightSky()
        palette = current_theme()
        moving = ambient_ok()
        now = time.monotonic()
        cycle = stopped = None
        if moving and self._ping_at is not None:
            cycle = (now - self._ping_at) * 1000.0
            if self._ping_end is not None:
                stopped = (self._ping_end - self._ping_at) * 1000.0
        look = {
            "live": self._live.value, "gather": self._gather.value,
            "error": self._error.value, "reveal": self._reveal.value,
            # Reduced motion: every loop holds still.
            "gather_ms": (now - self._gather_at) * 1000.0 if moving else 0.0,
            "cycle": cycle, "stopped": stopped,
            "gain": lambda index: self._pulse_gain(index, now),
            "moving": moving,
            "secondary": QColor(palette["secondary"]),
            "accent": QColor(palette["accent"]),
            "accent_light": QColor(palette["accent_light"]),
        }
        return (box, clip, centre, k, ui, now * 1000.0 if moving else 0.0,
                look)

    # -- the sky on the GPU ----------------------------------------------------------
    def _sync_view(self) -> None:
        """A GPU sky while the sky is the backdrop and Qt Quick can draw
        it here (made when first shown); none otherwise."""
        if not (self._sky_on() and ambient_ok()):
            self._drop_view()     # (a still sky is painted here)
            return
        if (self._view is not None or self._view_failed or self._making_view
                or not self.isVisible()):
            return
        # The first view in a window makes Qt recreate it for the GPU,
        # showing this card again: no second view from in there.
        self._making_view = True
        try:
            from .sky_gpu import SkyView, gpu_sky_wanted
            if not gpu_sky_wanted():
                self._view_failed = True
                return
            view = SkyView(self)
        except Exception as e:   # no Qt Quick here
            _logger.warning(f"Night sky on the CPU (no Qt Quick: {e})")
            self._view_failed = True
            return
        finally:
            self._making_view = False
        if not view.ok:
            _logger.warning("Night sky on the CPU (its shader did not load: "
                            f"{[str(e.toString()) for e in view.errors()]})")
            view.deleteLater()
            self._view_failed = True
            return
        view.failed.connect(self._view_fallback)
        view.setGeometry(self.rect())
        view.lower()               # under the dial and the headline
        self._view = view
        self._hand_ring(True)
        self._show_sky_frame()
        view.show()

    def _view_fallback(self) -> None:
        _logger.warning("Night sky on the CPU (Qt Quick has no GPU here)")
        self._view_failed = True
        self._drop_view()

    def _hand_ring(self, to_view: bool) -> None:
        """The dial's ring drawn by the GPU sky (to_view) or by the dial."""
        origin = self._origin
        if origin is not None and hasattr(origin, "set_ring_sink"):
            origin.set_ring_sink(self._view.show_ring if to_view else None)
            # Where the ticks go follows the dial (an error line under the
            # headline moves it), even when no sky frame is coming.
            if to_view:
                origin.installEventFilter(self)
            else:
                origin.removeEventFilter(self)

    def eventFilter(self, watched, event):  # noqa: N802 (Qt override)
        if (watched is self._origin and self._view is not None
                and event.type() in (QEvent.Type.Move, QEvent.Type.Resize)):
            self._show_sky_frame()
        return super().eventFilter(watched, event)

    def _drop_view(self) -> None:
        if self._view is not None:
            self._hand_ring(False)
            self._view.hide()
            self._view.deleteLater()
            self._view = None
            self.update()

    def _show_sky_frame(self) -> None:
        w, h = self.width(), self.height()
        if w < 40 or h < 40:
            return
        if self._sky is None:
            self._sky = NightSky()
        box, _, centre, k, ui, now, look = self._sky_moment(w, h)
        self._view.show_frame(self._sky.frame(box, centre, k, ui, now, look),
                              box, self._view_base(w, h, ui))
        # Each of the dial's paints sends its ring; while its own clock
        # rests only the idle breath moves, sent with each sky frame.
        origin = self._origin
        if (origin is not None and hasattr(origin, "ring_frame")
                and origin.isVisible()):
            # The ring is drawn about the dial's exact centre (the sky's
            # is the centre pixel of the widget, half a pixel off).
            at = QPointF(origin.mapTo(self, QPoint(0, 0)))
            self._view.place_ring(at.x() + origin.width() / 2,
                                  at.y() + origin.height() / 2,
                                  min(origin.width(), origin.height())
                                  / 300.0)
            if not origin.ring_animating():
                self._view.show_breath(origin.ring_breath())

    def _view_base(self, w: int, h: int, ui: float) -> dict:
        """The card the GPU sky draws under itself, and the page around
        its corners (see sky_gpu.card_base)."""
        page = self.parentWidget()
        while page is not None and page.objectName() != "page":
            page = page.parentWidget()
        page = page or self.window()
        at = self.mapTo(page, QPoint(0, 0))
        palette = current_theme()
        key = (w, h, ui, at.x(), at.y(), page.width(), page.height(),
               id(palette))
        if key != self._base_key:
            from ..styles import _card_border_width
            from .sky_gpu import card_base
            border = QColor(*(int(v) for v in
                              palette["border_rgb"].split(",")))
            border.setAlphaF(float(palette["border_alpha"]))
            self._base_key = key
            self._base = card_base(
                (w, h), round(CARD_RADIUS * ui), _card_border_width(ui),
                border, theme_style("card_fill") or palette["card"],
                theme_style("window_fill") or palette["bg"],
                (at.x(), at.y()), (page.width(), page.height()))
        return self._base

    def _paint_ping(self, p, w, h, centre, radius, alpha,
                    within: QRegion = None) -> None:
        """The accent lattice, seen only through a ring around `centre`
        (worked out only in the part of `within` the ring covers)."""
        r = radius * ui_scale()
        region = self._ring_region(centre, radius)
        if within is not None:
            region = region.intersected(within)
        box = region.boundingRect().intersected(QRect(0, 0, w, h))
        if box.isEmpty() or r <= 0:
            return
        layer = self._ping_image(w, h)
        dpr = self.devicePixelRatioF()
        ring = QImage(round(box.width() * dpr), round(box.height() * dpr),
                      QImage.Format.Format_ARGB32_Premultiplied)
        ring.setDevicePixelRatio(dpr)
        ring.fill(Qt.GlobalColor.transparent)
        q = QPainter(ring)
        q.setClipRegion(region.translated(-box.x(), -box.y()))
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
