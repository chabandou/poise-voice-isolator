"""
Poise Voice Isolator - Emblem

The About-page brand mark: the app icon inside a full ring of ticks,
echoing the Start/Stop dial. Drawn in a 300-unit square like the dial.

It hides an easter egg, the seal. Hovering lifts the ticks nearest the
pointer and lays a soft sheen on the face. A click unwinds the dial the
way the site's emblem draws on, in reverse (the needle lifts off, the
ticks fly out counter-clockwise, the dashes are taken back one by one and
the wave un-writes), the face eases in, and two squares spin in around
it and lock into a rub el hizb. Then تَمَّ بِحَمْدِ اللَّهِ ("it is finished,
with praise to God", the line scribes closed a manuscript with) is
written inside it from the bottom up, in the gold of the site's colophon
(docs/src/colophon.ts). Another click brings the dial back, replaying
the site's entrance. Leaving the page shows the plain emblem again.

The pen's paths, the lettering and each letter group's shape are baked
by tools/bake_seal_pen.py into assets/seal (the UI process stays free of
numpy, and Qt cannot read the site's font). With Reduce motion on (or
animation effects off) a click crossfades straight to the other state.
"""
import bisect
import json
import math
import os
import re
import time
from functools import lru_cache

from PyQt6.QtCore import QByteArray, QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPolygonF,
    QRadialGradient,
)
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ..animations import (
    FrameTimer,
    ambient_ok,
    cubic_bezier_fn,
    mix_rgba,
    motion_ok,
)
from ..scaling import sp
from ..themes import current as current_theme

REF = 300.0
TICKS = 72
MAJOR_EVERY = 6
DISC_R = 96.0
DISC_SEAL = 88.0     # the face eases to the site emblem's size
HALF = 96.0          # half side of each square: edges clear the face,
                     # points reach r 136, where the tick ring ended
SPIN = math.radians(405)   # how far each square turns on its way in
MARK_SIDE = DISC_R * 1.35  # the icon, as it always sat in the disc
HIT_R = 142.0              # the pointer counts as over the emblem inside
SWAP_MS = 300              # Reduce motion: the crossfade between states

SEAL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets", "seal")

# The whole sequence plays this much slower than the times below (ms).
PACE = 1.12

# The seal: when each beat starts and ends.
SEAL = {
    "needle": (0, 340),
    "tick_from": 160, "tick_step": 11, "tick_ms": 170,
    "dash_from": 560, "dash_step": 110, "dash_ms": 100,
    "wave": (820, 1480),
    "disc": (1080, 1700),
    "sq1": (1600, 2160),   # the diagonal square
    "sq2": (2340, 2900),   # the upright one
    "write": 3350,
}
# The way back (the site's entrance), squares last in first out.
RESTORE = {
    "text_fade": (0, 420),
    "out1": (100, 560),    # the upright square
    "out2": (240, 700),    # the diagonal one
    "disc": (560, 1100),
    "wave": (1000, 2050),
    "dash_from": 1870, "dash_step": 150, "dash_ms": 140,
    "tick_from": 1800, "tick_step": 20, "tick_ms": 90,
}
_LANDS = RESTORE["tick_from"] + 70 * RESTORE["tick_step"] + RESTORE["tick_ms"]
RESTORE["needle"] = (_LANDS, _LANDS + 560)
RESTORE["bloom"] = (_LANDS, _LANDS + 900)
RESTORE_MS = RESTORE["bloom"][1] + 100

# The lock is a detent: a stiff, slightly underdamped spring that catches
# a square at full speed. Its velocity stays continuous through the
# impact (it runs on past its seat, is pulled back and settles), which
# reads as a part clicking home rather than a stop and a twitch.
LOCK_ZETA = 0.45                 # damping ratio: one small rebound
LOCK_PEAK = math.radians(6)      # how far momentum carries it past
LOCK_SQUASH = 0.025              # pressed into the face at the peak


def _lock_peak_factor() -> float:
    """Peak of e^(-zeta wn t) sin(wd t), per v / wd."""
    r = math.sqrt(1 - LOCK_ZETA ** 2)
    phi = math.atan(r / LOCK_ZETA)
    return math.exp((-LOCK_ZETA / r) * phi) * math.sin(phi)


LOCK_PF = _lock_peak_factor()
# A square's speed eases from 1.35x to 0.65x its average (never crawls).
SPIN_IN = (1.35, -0.35)

_manim = cubic_bezier_fn(0.45, 0.0, 0.55, 1.0)      # the site's --manim-ease
_reveal = cubic_bezier_fn(0.22, 1.0, 0.36, 1.0)     # --reveal-ease
_overshoot = cubic_bezier_fn(0.34, 1.56, 0.64, 1.0)  # the needle's landing

# The icon's wave and axis dashes (icon.svg), in its 24-unit space.
WAVE_DASHES = ((3.0, 5.0), (7.5, 8.5), (15.5, 16.5), (19.0, 21.0))
WAVE_SAMPLES = 120
# Half-widths, in icon units, of what a clip must uncover around the
# stroke (1.9 wide, plus its glow) and at a pen's leading end.
CLIP_HALF = 1.7
LEAD_R = 1.0


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def _seg(t, a, b):
    return _clamp((t - a) / (b - a), 0.0, 1.0)


def _smooth(t):
    return t * t * (3 - 2 * t)


def _ease_in(t):
    return t * t * t


def _ease_out(t):
    return 1 - (1 - t) ** 3


def _bell(t):
    return 0.0 if t <= 0 or t >= 1 else math.sin(math.pi * t)


def _lerp(a, b, t):
    return a + (b - a) * t


def _ang_diff(a, b):
    return math.atan2(math.sin(a - b), math.cos(a - b))


def _blank(n: int) -> QImage:
    img = QImage(n, n, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    return img


# -- the baked pen ----------------------------------------------------------
class SealPen:
    """assets/seal: the pen's points in writing order, each with the time
    the pen reaches it (ms, before PACE), the lettering's coverage and
    the atlas of letter-group shapes."""

    def __init__(self, folder: str = SEAL_DIR):
        with open(os.path.join(folder, "pen.json"), encoding="utf-8") as f:
            data = json.load(f)
        self.text_space = float(data["textSpace"])
        self.text_scale = float(data["textScale"])
        self.duration = float(data["duration"])
        b = data["bounds"]
        self.left, self.right = float(b["left"]), float(b["right"])
        self.text = QImage(os.path.join(folder, "text.png"))
        self.atlas = QImage(os.path.join(folder, "parts.png"))
        if self.text.isNull() or self.atlas.isNull():
            raise OSError("seal images missing")
        self.parts = [(QRectF(p["x"], p["y"], p["w"], p["h"]),
                       QRectF(p["ox"], p["oy"], p["w"], p["h"]))
                      for p in data["parts"]]
        self.items = []     # (t0, t1)
        self.points = []    # (x, y, r, t, item)
        self.times = []
        settles = []
        for index, item in enumerate(data["items"]):
            self.items.append((float(item["t0"]), float(item["t1"])))
            for x, y, r, t in item["pts"]:
                self.points.append((x, y, r, t, index))
                self.times.append(t)
            if item["last"]:
                settles.append((float(item["t1"]), int(item["part"])))
        settles.sort()
        self.settles = settles
        self.settle_times = [t for t, _ in settles]


@lru_cache(maxsize=1)
def load_pen():
    """The baked pen, or None when its files are missing (the emblem
    then stays a plain mark)."""
    try:
        return SealPen()
    except (OSError, ValueError, KeyError):
        return None


class _Ink:
    """The lettering as the pen has uncovered it, at one pixel size: a
    reveal mask of round stamps (and each letter group's own shape once
    the pen leaves it) over the gilded fill, drawn up to a time."""

    def __init__(self, pen: SealPen, n: int, colour: QColor):
        self.pen = pen
        self.n = n
        self.k = n / pen.text_space
        self.colour = QColor(colour)
        self.fill = self._paint_fill()
        self.rev = _blank(n)
        self.ink = _blank(n)
        self.fx = _blank(n)
        self.tau = -math.inf
        self.stamped = 0
        self.settled = 0

    def _paint_fill(self) -> QImage:
        img = _blank(self.n)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(QRectF(0, 0, self.n, self.n), self.pen.text)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        p.fillRect(QRectF(0, 0, self.n, self.n), self.colour)
        p.end()
        return img

    def recolour(self, colour: QColor) -> None:
        self.colour = QColor(colour)
        self.fill = self._paint_fill()
        self._compose()

    def _compose(self) -> None:
        self.ink = self.rev.copy()
        p = QPainter(self.ink)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        p.drawImage(0, 0, self.fill)
        p.end()

    def advance(self, tau: float) -> None:
        """Uncover everything the pen has reached by `tau` (ms)."""
        pen = self.pen
        if tau < self.tau:
            self.rev.fill(Qt.GlobalColor.transparent)
            self.stamped = self.settled = 0
        self.tau = tau
        end = bisect.bisect_right(pen.times, tau)
        settle_end = bisect.bisect_right(pen.settle_times, tau)
        if end == self.stamped and settle_end == self.settled:
            return
        p = QPainter(self.rev)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.scale(self.k, self.k)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255))
        for x, y, r, _t, _i in pen.points[self.stamped:end]:
            p.drawEllipse(QPointF(x, y), r, r)
        for _t, part in pen.settles[self.settled:settle_end]:
            src, dst = pen.parts[part]
            p.drawImage(dst, pen.atlas, src)
        p.end()
        self.stamped, self.settled = end, settle_end
        self._compose()

    def effects(self, tau: float):
        """Wet shine trailing the pen and, once the lines are written, one
        glint across the gilding (None when neither shows)."""
        pen = self.pen
        writing = tau <= pen.duration + 1000
        glint = (tau - (pen.duration + 250)) / 1500.0
        if not writing and not 0 <= glint < 1:
            return None
        fx = self.fx
        fx.fill(Qt.GlobalColor.transparent)
        p = QPainter(fx)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(self.k, self.k)
        p.setPen(Qt.PenStyle.NoPen)
        if writing:
            p.setBrush(QColor(255, 255, 255))
            start = bisect.bisect_right(pen.times, tau - 1000)
            for x, y, r, t, _i in pen.points[start:self.stamped]:
                p.setOpacity(0.5 * (1 - (tau - t) / 1000.0) ** 1.7)
                p.drawEllipse(QPointF(x - r * 0.22, y - r * 0.28),
                              r * 0.42, r * 0.42)
            p.setOpacity(1.0)
        if 0 <= glint < 1:
            x = pen.right + 100 - (pen.right - pen.left + 200) * _smooth(glint)
            grad = QLinearGradient(x - 55, 0, x + 55, 0)
            grad.setColorAt(0.0, QColor(255, 250, 230, 0))
            grad.setColorAt(0.5, QColor(255, 250, 230, 178))
            grad.setColorAt(1.0, QColor(255, 250, 230, 0))
            p.fillRect(QRectF(x - 55, 0, 110, pen.text_space), QBrush(grad))
        p.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_DestinationIn)
        p.resetTransform()
        p.drawImage(0, 0, self.fill)
        p.end()
        return fx

    def head(self, tau: float):
        """The pen's tip while it is down: (x, y, r) in text space."""
        if self.stamped == 0:
            return None
        x, y, r, _t, item = self.pen.points[self.stamped - 1]
        t0, t1 = self.pen.items[item]
        if t0 <= tau <= t1 + 8:
            return x, y, r
        return None


# -- the icon ---------------------------------------------------------------
def _icon_parts(svg: str):
    """The icon's SVG split into the wave alone and the dashes alone (its
    one path holds both), so each can be uncovered on its own."""
    match = re.search(r'\sd="([^"]+)"', svg)
    if not match:
        return None
    subpaths = [s.strip() for s in re.split(r"(?=M)", match.group(1)) if s.strip()]
    waves = [s for s in subpaths if "C" in s]
    dashes = [s for s in subpaths if "C" not in s]
    if len(waves) != 1 or not dashes:
        return None
    start, end = match.span(1)
    return (svg[:start] + waves[0] + svg[end:],
            svg[:start] + " ".join(dashes) + svg[end:])


def _render_svg(svg: str, n: int) -> QImage:
    from PyQt6.QtSvg import QSvgRenderer
    img = _blank(max(1, n))
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if renderer.isValid():
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(p, QRectF(0, 0, img.width(), img.height()))
        p.end()
    return img


def _icon_transform():
    """Icon units (its 24-unit path space) to emblem units: icon.svg's
    viewBox is 16 14 76 76 with the path at translate(18, 18) scale(3),
    drawn MARK_SIDE wide around the centre."""
    s = 3 * MARK_SIDE / 76
    return s, (18 - 16) / 76 * MARK_SIDE - MARK_SIDE / 2, \
        (18 - 14) / 76 * MARK_SIDE - MARK_SIDE / 2


def _wave_points():
    path = QPainterPath(QPointF(3, 12))
    path.cubicTo(3.00015, 8.14286, 4.28571, 3, 6.85714, 3)
    path.cubicTo(10.7143, 2.9999, 13.2857, 21, 17.1429, 21)
    path.cubicTo(19.7143, 21, 21, 15.8571, 21, 12)
    s, tx, ty = _icon_transform()
    out = []
    for i in range(WAVE_SAMPLES + 1):
        pt = path.pointAtPercent(i / WAVE_SAMPLES)
        out.append(QPointF(tx + s * pt.x(), ty + s * pt.y()))
    return out


_WAVE = None


def _stroke_clip(points, lead_r: float, start_r: float) -> QPainterPath:
    """What uncovers a pen's stroke along `points`: the stroke and its
    glow, cut square at the pen, with a round tip and a round start."""
    s = _icon_transform()[0]
    line = QPainterPath(points[0])
    for pt in points[1:]:
        line.lineTo(pt)
    stroker = QPainterPathStroker()
    stroker.setWidth(2 * CLIP_HALF * s)
    stroker.setCapStyle(Qt.PenCapStyle.FlatCap)
    stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    clip = stroker.createStroke(line)
    caps = QPainterPath()
    caps.addEllipse(points[0], start_r * s, start_r * s)
    caps.addEllipse(points[-1], lead_r * s, lead_r * s)
    return clip.united(caps)


# -- the widget -------------------------------------------------------------
class Emblem(QWidget):
    """Icon + tick ring, with the seal behind a click (theme-aware)."""

    def __init__(self, size: int = 260, parent=None):
        super().__init__(parent)
        self._px = sp(size)
        self.setFixedSize(self._px, self._px)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.setAccessibleName("Poise emblem")
        self._svg = None            # the icon's SVG text
        self._fallback = None       # or a raster icon
        self._icons = None          # (pixel size, full, wave, dashes, glow)
        self._ink = None
        self._mode = "rest"         # rest | seal | restore
        self._t = 0.0               # ms into the sequence, before PACE
        self._playing = False
        self._sealed_at = 0.0
        self._swap = None           # (snapshot, start) while crossfading
        self._inside = False
        self._pressed = False
        self._hand = False
        self._hover = 0.0
        self._ang, self._ang_s = -math.pi / 2, -math.pi / 2
        self._pt = [0.0, -60.0]
        self._pt_s = [0.0, -60.0]
        self._last = time.perf_counter()
        self._clock = FrameTimer(self)
        self._clock.timeout.connect(self._tick)

    def sizeHint(self):  # noqa: N802 (Qt override)
        return QSize(self._px, self._px)

    # -- public -------------------------------------------------------------
    def set_icon(self, path: str) -> None:
        """The app icon for the current theme: an icon*.svg (the wave
        and dashes then animate on their own), else a raster image."""
        self._svg, self._fallback = None, None
        if path and path.lower().endswith(".svg"):
            try:
                with open(path, encoding="utf-8") as f:
                    self._svg = f.read()
            except (OSError, UnicodeDecodeError):
                self._svg = None
        if self._svg is None and path:
            from PyQt6.QtGui import QPixmap
            self._fallback = QPixmap(path)
        self._icons = None
        self.update()

    def seal_ms(self) -> float:
        pen = load_pen()
        return SEAL["write"] + (pen.duration if pen else 3744.0) + 1900

    def state(self) -> str:
        """rest, sealing, sealed or restoring."""
        if self._mode == "rest":
            return "rest"
        if self._mode == "restore":
            return "restoring"
        return "sealing" if self._playing or self._t < self.seal_ms() else "sealed"

    def press(self) -> None:
        """What a click does: seal the plain emblem, or bring the dial
        back to a sealed one. Ignored while either sequence plays."""
        if not self._clickable():
            return
        sealing = self._mode == "rest"
        if not ambient_ok():
            # Reduce motion: crossfade straight to the other state.
            snapshot = self.grab() if motion_ok() else None
            self._jump(sealing)
            if snapshot is not None and not snapshot.isNull():
                self._swap = (snapshot, time.perf_counter())
                self._wake()
            return
        self._mode = "seal" if sealing else "restore"
        self._t = 0.0
        self._playing = True
        self._update_cursor()
        self._wake()

    def reset(self) -> None:
        """Back to the plain emblem, at once."""
        self._mode, self._t, self._playing = "rest", 0.0, False
        self._update_cursor()
        self.update()

    def seek(self, mode: str, t: float) -> None:
        """Hold a frame of a sequence (`t` in ms of its own timeline,
        before PACE). For tests and tools."""
        self._mode, self._t, self._playing = mode, float(t), False
        if mode == "seal" and t >= self.seal_ms():
            self._sealed_at = time.perf_counter()
        self.update()

    # -- state --------------------------------------------------------------
    def _clickable(self) -> bool:
        if self._playing or load_pen() is None:
            return False
        return self._mode == "rest" or (
            self._mode == "seal" and self._t >= self.seal_ms())

    def _jump(self, sealing: bool) -> None:
        if sealing:
            self._mode, self._t = "seal", self.seal_ms()
            self._sealed_at = time.perf_counter()
        else:
            self._mode, self._t = "rest", 0.0
        self._playing = False
        self._update_cursor()
        self._wake()
        self.update()

    def _want_hover(self) -> float:
        return 1.0 if (self._inside and self._clickable() and motion_ok()) else 0.0

    def _sealed(self) -> bool:
        return self._mode == "seal" and not self._playing and self._t >= self.seal_ms()

    def _busy(self) -> bool:
        """True while something still moves: a sequence, the hover
        easing, the sheen catching up with the pointer, or the finished
        seal's slow glow (ambient)."""
        if self._playing or self._swap is not None:
            return True
        if abs(self._want_hover() - self._hover) > 0.002:
            return True
        if self._hover > 0.01 and (abs(self._pt[0] - self._pt_s[0]) > 0.05
                                   or abs(self._pt[1] - self._pt_s[1]) > 0.05
                                   or abs(_ang_diff(self._ang, self._ang_s)) > 0.002):
            return True
        return self._sealed() and ambient_ok() and self.isVisible()

    def _interval(self) -> int:
        """A frame every 16 ms while it answers the user; the finished
        seal's slow glow alone needs no more than 20 a second."""
        quick = (self._playing or self._swap is not None or self._hover > 0.01
                 or abs(self._want_hover() - self._hover) > 0.002)
        return 16 if quick else 50

    def _wake(self) -> None:
        if not self._busy():
            return
        interval = self._interval()
        if self._clock.isActive():
            if self._clock.interval() != interval:
                self._clock.setInterval(interval)
            return
        self._last = time.perf_counter()
        self._clock.start(interval)

    def _tick(self) -> None:
        now = time.perf_counter()
        dt = min(50.0, (now - self._last) * 1000.0)
        self._last = now
        if self._playing:
            self._t += dt / PACE
            total = self.seal_ms() if self._mode == "seal" else RESTORE_MS
            if self._t >= total:
                self._t = total
                self._playing = False
                if self._mode == "restore":
                    self._mode, self._t = "rest", 0.0
                else:
                    self._sealed_at = now
                self._update_cursor()
        if self._swap is not None and (now - self._swap[1]) * 1000 >= SWAP_MS:
            self._swap = None
        follow = 1 - math.exp(-dt / 90.0)
        self._hover += (self._want_hover() - self._hover) * (1 - math.exp(-dt / 110.0))
        self._ang_s += _ang_diff(self._ang, self._ang_s) * (1 - math.exp(-dt / 70.0))
        self._pt_s[0] += (self._pt[0] - self._pt_s[0]) * follow
        self._pt_s[1] += (self._pt[1] - self._pt_s[1]) * follow
        self.update()
        if not self._busy():
            self._clock.stop()
        elif self._clock.interval() != self._interval():
            self._clock.setInterval(self._interval())

    def _update_cursor(self) -> None:
        hand = self._inside and self._clickable()
        if hand == self._hand:
            return
        self._hand = hand
        if hand:
            from ..cursors import apply_link_cursor
            apply_link_cursor(self)
        else:
            self.unsetCursor()

    # -- events -------------------------------------------------------------
    def _units(self, pos):
        k = min(self.width(), self.height()) / REF
        return ((pos.x() - self.width() / 2) / k,
                (pos.y() - self.height() / 2) / k)

    def mouseMoveEvent(self, event):  # noqa: N802 (Qt override)
        x, y = self._units(event.position())
        inside = math.hypot(x, y) <= HIT_R
        if inside and not self._inside:
            load_pen()          # a few ms, before the click needs it
        self._inside = inside
        self._ang = math.atan2(y, x)
        self._pt = [x, y]
        self._update_cursor()
        self._wake()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):  # noqa: N802 (Qt override)
        self._inside = False
        self._pressed = False
        self._update_cursor()
        self._wake()
        super().leaveEvent(event)

    def _over(self, event) -> bool:
        x, y = self._units(event.position())
        return math.hypot(x, y) <= HIT_R

    def mousePressEvent(self, event):  # noqa: N802 (Qt override)
        if event.button() == Qt.MouseButton.LeftButton and self._over(event) \
                and self._clickable():
            self._pressed = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802 (Qt override)
        if self._pressed and event.button() == Qt.MouseButton.LeftButton:
            self._pressed = False
            if self._over(event):
                self.press()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def showEvent(self, event):  # noqa: N802 (Qt override)
        super().showEvent(event)
        self._wake()

    def hideEvent(self, event):  # noqa: N802 (Qt override)
        super().hideEvent(event)
        if not event.spontaneous():
            # Left the About page: the plain emblem next time.
            self._clock.stop()
            self._inside = False
            self._hover = 0.0
            self._swap = None
            self.reset()

    # -- painting -----------------------------------------------------------
    def _icon_images(self, n: int):
        if self._icons is not None and self._icons[0] == n:
            return self._icons
        full = wave = dashes = None
        if self._svg:
            full = _render_svg(self._svg, n)
            parts = _icon_parts(self._svg)
            if parts:
                wave, dashes = _render_svg(parts[0], n), _render_svg(parts[1], n)
        else:
            pixmap = self._fallback
            if pixmap is not None and not pixmap.isNull():
                full = pixmap.toImage().scaled(
                    n, n, Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
        glow = None
        if full is not None:
            # A soft bloom: the icon shrunk and stretched back.
            small = max(4, n // 8)
            glow = full.scaled(small, small, Qt.AspectRatioMode.IgnoreAspectRatio,
                               Qt.TransformationMode.SmoothTransformation).scaled(
                n, n, Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
        self._icons = (n, full, wave, dashes, glow)
        return self._icons

    def _ink_for(self, n: int, colour: QColor):
        pen = load_pen()
        if pen is None:
            return None
        if self._ink is None or self._ink.n != n:
            self._ink = _Ink(pen, n, colour)
        elif self._ink.colour != colour:
            self._ink.recolour(colour)
        return self._ink

    def paintEvent(self, event):  # noqa: N802 (Qt override)
        pal = current_theme()
        k = min(self.width(), self.height()) / REF
        self._dpr = self.devicePixelRatioF()
        self._k = k
        self._c = {
            "accent": QColor(pal["accent"]),
            "light": QColor(pal["accent_light"]),
            "secondary": QColor(pal["secondary"]),
            "groove": QColor(pal["groove"]),
            "pill": QColor(pal["pill"]),
        }
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.translate(self.width() / 2, self.height() / 2)
        p.scale(k, k)
        if self._mode == "restore":
            self._paint_restore(p)
        else:
            self._paint_seal(p, self._t if self._mode == "seal" else 0.0)
        if self._swap is not None:
            snapshot, start = self._swap
            u = _clamp((time.perf_counter() - start) * 1000 / SWAP_MS, 0, 1)
            p.resetTransform()
            p.setOpacity(1 - _ease_out(u))
            p.drawPixmap(0, 0, snapshot)
            p.setOpacity(1.0)
        p.end()

    def _paint_seal(self, p: QPainter, t: float) -> None:
        z = SEAL
        pen = load_pen() if self._mode == "seal" else None
        end = z["write"] + (pen.duration if pen else 3744.0)
        at_rest = self._mode == "rest"
        sealed = self._sealed()
        hover = self._hover

        r = _lerp(DISC_R, DISC_SEAL, _manim(_seg(t, *z["disc"])))
        s1 = self._square_in(t, z["sq1"], math.pi / 4, -1)
        s2 = self._square_in(t, z["sq2"], 0.0, 1)
        finale = _bell(_seg(t, end + 250, end + 1450))
        breath = 0.0
        if sealed and ambient_ok():
            phase = (time.perf_counter() - self._sealed_at) / 5.2
            breath = 0.16 * (0.5 - 0.5 * math.cos(phase * 2 * math.pi))
        ambient = finale * 0.9 + breath + (0.3 * hover if sealed else 0.0)
        rim = ((0.4 * hover if at_rest else 0.0)
               + 0.5 * _bell(_seg(t, z["disc"][0], z["disc"][1] + 250))
               + 0.35 * finale)

        self._star_fill(p, _smooth(_seg(t, z["sq2"][1], z["sq2"][1] + 500)))
        self._disc(p, r, rim)

        last_tick = z["tick_from"] + 70 * z["tick_step"] + z["tick_ms"]
        if t < last_tick:
            for i in range(1, TICKS):
                j = TICKS - 1 - i
                start = z["tick_from"] + j * z["tick_step"]
                u = _seg(t, start, start + z["tick_ms"])
                if u >= 1:
                    continue
                e = _ease_in(u)
                w = self._hover_weight(i) if at_rest else 0.0
                self._tick_line(p, i, 20 * e + 3.5 * w, 1 - e, w)
        un = _seg(t, *z["needle"])
        if un < 1:
            out = (-2 * _smooth(un / 0.3) if un < 0.3
                   else -2 + 18 * _ease_in((un - 0.3) / 0.7))
            self._tick_line(p, 0, out, 1 - _ease_in(un), 0.0)

        uw = _seg(t, *z["wave"])
        dash_frac = []
        for j in range(4):   # last dash first, each taken back in turn
            start = z["dash_from"] + (3 - j) * z["dash_step"]
            dash_frac.append(1 - _ease_in(_seg(t, start, start + z["dash_ms"])))
        self._mark(p, 1 - _manim(uw), (1 - uw) / 0.1 if uw > 0.9 else 1.0,
                   dash_frac, 0.35 * hover if at_rest else 0.0)

        for sq in (s1, s2):
            if sq is not None:
                self._square(p, sq[0], sq[1], sq[2], sq[3] + ambient)
        if pen is not None and t > z["write"]:
            self._calligraphy(p, t - z["write"], 1.0)

    def _paint_restore(self, p: QPainter) -> None:
        z, t = RESTORE, self._t
        r = _lerp(DISC_SEAL, DISC_R, _manim(_seg(t, *z["disc"])))
        self._star_fill(p, 1 - _smooth(_seg(t, 0, z["out2"][1])))
        self._disc(p, r, 0.45 * _bell(_seg(t, z["disc"][0] - 100, z["disc"][1] + 300))
                   + 0.3 * _bell(_seg(t, *z["bloom"])))
        for i in range(1, TICKS):
            start = z["tick_from"] + (i - 1) * z["tick_step"]
            if t < start:
                continue
            u = _seg(t, start, start + z["tick_ms"])
            self._tick_line(p, i, 18 * (1 - _reveal(u)), _clamp(u / 0.45, 0, 1), 0.0)
        if t >= z["needle"][0]:
            u = _seg(t, *z["needle"])
            self._tick_line(p, 0, 14 * (1 - _overshoot(u)), _clamp(u / 0.4, 0, 1), 0.0)

        uw = _seg(t, *z["wave"])
        dash_frac = []
        for j in range(4):   # written one at a time, left to right
            start = z["dash_from"] + j * z["dash_step"]
            dash_frac.append(_reveal(_seg(t, start, start + z["dash_ms"])))
        self._mark(p, _manim(uw), _clamp(uw / 0.08, 0, 1), dash_frac,
                   0.9 * _bell(_seg(t, *z["bloom"])))

        for sq in (self._square_out(t, z["out2"], math.pi / 4, -1),
                   self._square_out(t, z["out1"], 0.0, 1)):
            if sq is not None:
                self._square(p, *sq)
        if load_pen() is not None:
            self._calligraphy(p, math.inf, 1 - _manim(_seg(t, *z["text_fade"])))

    # -- pieces ---------------------------------------------------------------
    def _hover_weight(self, i: int) -> float:
        if self._hover < 0.002:
            return 0.0
        a = -math.pi / 2 + 2 * math.pi * i / TICKS
        d = abs(_ang_diff(a, self._ang_s))
        return self._hover * math.exp(-((d / 0.27) ** 2))

    def _tick_line(self, p, i, out, alpha, glow) -> None:
        if alpha <= 0.002:
            return
        a = -math.pi / 2 + 2 * math.pi * i / TICKS
        cs, sn = math.cos(a), math.sin(a)
        inner = (110.0 if i % MAJOR_EVERY == 0 else 118.0) + out
        outer = 136.0 + out
        head = i == 0
        if head:
            colour = QColor(self._c["secondary"])
            colour.setAlphaF(_clamp(alpha, 0, 1))
        else:
            colour = mix_rgba(self._c["accent"], self._c["light"], glow)
            colour.setAlphaF(_clamp(alpha * (215 + 40 * glow) / 255, 0, 1))
        pen = QPen(colour, 5.0 if head else 4.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(inner * cs, inner * sn), QPointF(outer * cs, outer * sn))

    def _disc(self, p, r, light) -> None:
        edge = mix_rgba(self._c["groove"], self._c["light"], _clamp(light, 0, 1))
        p.setPen(QPen(edge, 2.0))
        p.setBrush(self._c["pill"])
        p.drawEllipse(QPointF(0, 0), r, r)
        if self._hover < 0.01:
            return
        # The sheen: a soft light on the face under the pointer, as if it
        # were glazed, and the rim catching it on the pointer's side.
        x, y = self._pt_s
        light = self._c["light"]
        disc = QPainterPath()
        disc.addEllipse(QPointF(0, 0), r, r)
        glaze = QRadialGradient(QPointF(x, y), r * 0.95)
        for stop, a in ((0.0, 0.13), (0.45, 0.04), (1.0, 0.0)):
            c = QColor(light)
            c.setAlphaF(a * self._hover)
            glaze.setColorAt(stop, c)
        p.save()
        p.setClipPath(disc)
        p.fillRect(QRectF(-r, -r, 2 * r, 2 * r), QBrush(glaze))
        p.restore()
        rim = QRadialGradient(QPointF(x, y), r * 1.1)
        c0, c1 = QColor(light), QColor(light)
        c0.setAlphaF(0.75 * self._hover)
        c1.setAlphaF(0.0)
        rim.setColorAt(0.0, c0)
        rim.setColorAt(1.0, c1)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QBrush(rim), 2.0))
        p.drawEllipse(QPointF(0, 0), r, r)

    def _mark(self, p, frac, alpha, dash_frac, glow) -> None:
        n = max(1, round(MARK_SIDE * self._k * self._dpr))
        _n, full, wave, dashes, bloom = self._icon_images(n)
        if full is None:
            return
        rect = QRectF(-MARK_SIDE / 2, -MARK_SIDE / 2, MARK_SIDE, MARK_SIDE)
        whole = frac >= 1 and all(f >= 1 for f in dash_frac)
        if glow > 0.01 and bloom is not None and whole:
            p.setOpacity(_clamp(0.6 * glow, 0, 1))
            p.drawImage(rect, bloom)
        if whole or wave is None:
            if frac > 0.003 and alpha > 0:
                p.setOpacity(_clamp(alpha, 0, 1) if wave is None else 1.0)
                p.drawImage(rect, full)
            p.setOpacity(1.0)
            return
        global _WAVE
        if _WAVE is None:
            _WAVE = _wave_points()
        if frac > 0.003 and alpha > 0:
            p.save()
            p.setOpacity(_clamp(alpha, 0, 1))
            if frac < 1:
                upto = frac * WAVE_SAMPLES
                i = int(upto)
                pts = _WAVE[:i + 1]
                if i < WAVE_SAMPLES:
                    a, b = _WAVE[i], _WAVE[i + 1]
                    f = upto - i
                    pts = pts + [QPointF(_lerp(a.x(), b.x(), f), _lerp(a.y(), b.y(), f))]
                if len(pts) < 2:
                    pts = [pts[0], pts[0]]
                p.setClipPath(_stroke_clip(pts, LEAD_R, CLIP_HALF))
            p.drawImage(rect, wave)
            p.restore()
        s, tx, ty = _icon_transform()
        clip = QPainterPath()
        for (x0, x1), f in zip(WAVE_DASHES, dash_frac):
            if f <= 0.02:
                continue
            xe = x0 + (x1 - x0) * f
            piece = QPainterPath()
            piece.setFillRule(Qt.FillRule.WindingFill)   # the tip overlaps
            piece.addRect(QRectF(tx + s * (x0 - 2), ty + s * (12 - CLIP_HALF),
                                 s * (xe - x0 + 2), s * 2 * CLIP_HALF))
            piece.addEllipse(QPointF(tx + s * xe, ty + s * 12), LEAD_R * s, LEAD_R * s)
            clip = clip.united(piece.simplified())
        if not clip.isEmpty():
            p.save()
            p.setClipPath(clip)
            p.drawImage(rect, dashes)
            p.restore()

    def _square_in(self, t, span, target, direction):
        start, end = span
        if t < start:
            return None
        u = _seg(t, start, end)
        prog = SPIN_IN[0] * u + SPIN_IN[1] * u * u
        theta = target - direction * SPIN * (1 - prog)
        lock = t - end
        sc = 1.08 - 0.08 * _ease_out(u)
        glow = 0.0
        if lock >= 0:
            v = SPIN * (SPIN_IN[0] + 2 * SPIN_IN[1]) / (end - start)   # rad/ms
            wd = LOCK_PF * v / LOCK_PEAK
            wn = wd / math.sqrt(1 - LOCK_ZETA ** 2)
            ring = math.exp(-LOCK_ZETA * wn * lock) * math.sin(wd * lock)
            theta += direction * (v / wd) * ring
            sc *= 1 - LOCK_SQUASH * (ring / LOCK_PF)
            glow = 0.5 * (_smooth(lock / 90) if lock < 90
                          else math.exp(-(lock - 90) / 450))
        return theta, sc, _ease_out(_clamp(u / 0.4, 0, 1)), glow

    @staticmethod
    def _square_out(t, span, target, direction):
        u = _seg(t, *span)
        if u >= 1:
            return None
        e = u * u
        return (target - direction * SPIN * 0.5 * e, 1 + 0.08 * e,
                1 - _ease_in(u), 0.0)

    def _square(self, p, theta, sc, alpha, glow) -> None:
        if alpha <= 0.002:
            return
        p.save()
        p.rotate(math.degrees(theta))
        p.scale(sc, sc)
        p.setBrush(Qt.BrushStyle.NoBrush)
        side = QRectF(-HALF, -HALF, 2 * HALF, 2 * HALF)
        g = _clamp(glow, 0, 1.4)
        if g > 0.01:
            # A soft glow round the whole square: wider, fainter strokes.
            for extra, a in ((4.0, 0.22), (9.0, 0.10), (16.0, 0.05)):
                c = QColor(self._c["light"])
                c.setAlphaF(_clamp(a * g * alpha, 0, 1))
                pen = QPen(c, 2.4 + extra)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                p.setPen(pen)
                p.drawRect(side)
        main = mix_rgba(self._c["accent"], self._c["light"], _clamp(g * 0.7, 0, 1))
        main.setAlphaF(_clamp(alpha, 0, 1))
        pen = QPen(main, 2.4)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        p.setPen(pen)
        p.drawRect(side)
        inner = QColor(self._c["accent"])
        inner.setAlphaF(_clamp(alpha * 0.45, 0, 1))
        p.setPen(QPen(inner, 0.8))
        p.drawRect(side.adjusted(5, 5, -5, -5))
        p.restore()

    def _star_fill(self, p, a) -> None:
        """Once both squares are in, the star they make takes a faint
        tint, so it reads as one seal rather than two frames."""
        if a <= 0.01:
            return
        path = QPainterPath()
        path.setFillRule(Qt.FillRule.WindingFill)
        corner = HALF * math.sqrt(2)
        for base in (0.0, math.pi / 4):
            path.addPolygon(QPolygonF([
                QPointF(corner * math.cos(base + math.pi / 4 + n * math.pi / 2),
                        corner * math.sin(base + math.pi / 4 + n * math.pi / 2))
                for n in range(4)]))
            path.closeSubpath()
        tint = mix_rgba(self._c["pill"], self._c["accent"], 0.09)
        tint.setAlphaF(_clamp(a, 0, 1))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(tint)
        p.drawPath(path)

    def _calligraphy(self, p, tau, alpha) -> None:
        pen = load_pen()
        if pen is None or alpha <= 0 or tau < 0:
            return
        half = pen.text_space / 2 * pen.text_scale
        n = max(8, round(2 * half * self._k * self._dpr))
        ink = self._ink_for(n, self._c["secondary"])
        ink.advance(tau)
        rect = QRectF(-half, -half, 2 * half, 2 * half)
        p.setOpacity(_clamp(alpha, 0, 1))
        p.drawImage(rect, ink.ink)
        fx = ink.effects(tau)
        if fx is not None:
            p.drawImage(rect, fx)
        p.setOpacity(1.0)
        tip = ink.head(tau)
        if tip is None:
            return
        # The bead of ink on the pen's tip.
        x, y, r = tip
        s = pen.text_scale
        cx, cy = (x - pen.text_space / 2) * s, (y - pen.text_space / 2) * s
        rr = (r * 0.6 + 3) * s
        grad = QRadialGradient(QPointF(cx, cy), rr * 1.6)
        c0, c1 = QColor(self._c["secondary"]), QColor(self._c["secondary"])
        c0.setAlphaF(0.6)
        c1.setAlphaF(0.0)
        grad.setColorAt(0.0, c0)
        grad.setColorAt(1.0, c1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        p.drawEllipse(QPointF(cx, cy), rr * 1.6, rr * 1.6)
        p.setBrush(QColor(255, 255, 255, 217))
        dot = max(0.8 * s, rr * 0.13)
        p.drawEllipse(QPointF(cx - rr * 0.25, cy - rr * 0.3), dot, dot)
