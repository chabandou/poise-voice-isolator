"""
Poise Voice Isolator - Night Sky

The backdrop of Vigil and Eclipse for the dial card (PatternCard paints it in
place of the lattice): a soft aura and quiet geometry around the dial
(a ring with beads on it and an eight-point star turning slowly, its
sides touching the ticks' outer edge), small eight-point sparkles scattered over the
card, motes of light drifting up through it and, now and then, a
shooting star down one side (none under reduced motion). Idle it is
candle gold and breathes slowly; while isolating it turns lavender and
moves on the dial's breathing cycle (BREATH_MS): the ring and the star
light up with the first pulse and gather light with the dial's disc
before each one after (CHARGE), and as it leaves, a soft band of light and three halos leave the dial,
the star swells as the band reaches it and settles back, the beads flare
as the band passes them, and each sparkle flashes and is pushed outward
as the band reaches it, springing back.

The dial itself breathes on the same cycle (see DialButton); the shared
timelines live here. Ported from the design's CSS (the Vigil board), so
the numbers are its own: geometry around the dial is in dial units (the
dial is 300 across), sparkles and motes are placed in fractions of the
card and sized in px.
"""
import math

from PyQt6.QtCore import QLineF, QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush, QColor, QLinearGradient, QPainterPath, QPen, QPolygonF,
    QRadialGradient,
)

from ..animations import cubic_bezier_fn, mix_rgba

BREATH_MS = 8000          # live: one breath; a pulse leaves the dial at 0
IDLE_BREATH_MS = 7000     # idle: the aura, star and lit ticks breathe
GATHER_MS = 1800          # starting: everything draws in, then out
BAND_MS = 3040            # the pulse's band crosses the card
BAND_FROM, BAND_TO = 90.0, 780.0     # its radius (dial units)
BAND_INNER, BAND_CORE = 150.0, 50.0  # clear this far inside its edge,
BAND_ALPHA = 0.13 * 0.5              # brightest this far (as it leaves)
HALO_DELAYS = (0, 450, 900)          # three halos leave the disc
HALO_MS = 2560
HALO_GROWTH = 1.7                    # scale 1 -> 2.7
HALO_ALPHA = 0.55
FLARE_DELAY = 400         # the beads flare as the band passes them
PULSE_FADE_MS = 600       # a pulse in flight when isolating stops fades
DISC_R = 88.0
AURA_R = 290.0            # the aura's disc; its gradient runs to the
AURA_RAY = 410.0          # box's corner, as CSS circle gradients do
RING_R, RING_ALPHA = 168.0, 0.13              # the beads sit on it
STAR_HALF, STAR_TURN_MS = 136.0, 240000       # the star (its sides on
#                                               the ticks' ends, R_OUT)
STAR_ALPHA = (0.07, 0.105)                    # idle, live between pulses
BEAD_R, BEAD_MS, BEAD_STEP = 1.8, 6000, 750
FLARE_R = 3.2
# The charge the ring and star hold (0..1, as the disc's): their lines
# brighten toward accent_light, x(1 + GLOW_LIFT) at full, over soft
# halos (width x the line's, alpha x the line's).
GLOW_LIFT = 1.5
GLOW_HALO = ((10.0, 0.3), (4.0, 0.6))
FIRST_GLOW_MS = 140       # the first pulse's charge lights this fast
SEED = 0x2F6B1D3          # the design's scatter, star for star
MOTE_COUNT = 18
SPARKLE_COUNT = 26
SPARKLE_GAP = 64.0        # px apart at least (on the design's card)
DESIGN_CARD = (912.0, 522.0)
NEAR = 330.0              # sparkles nearer the dial are pushed harder
PUSH_NEAR, PUSH_FAR = (12.0, -1.5), (7.0, -1.0)   # out, then the recoil
# A shooting star: one at a random moment in each METEOR_EVERY_MS, down
# one side of the sky, clear of the dial and the headline (never under
# reduced motion). It surfaces and dives like something breaching: it
# flies a ballistic arc (a quadratic bezier at an even pace: rising
# into view slowing, tipping over, diving faster), and its light and
# size swell as it surfaces and sink as it dives, a meteor's light curve
# (rising to a late peak, falling away faster). Its trail follows the
# arc, brightest and widest by the head, growing as it surfaces and
# drawn down after it as it dives. Sizes in px, lengths in card widths.
METEOR_EVERY_MS = 30000
METEOR_MS = 1700          # its flight, from surfacing to gone
METEOR_SEED = SEED ^ 0x5EED
METEOR_TRAVEL = (0.31, 0.42)   # how far it goes, end to end...
METEOR_TRAIL = (0.20, 0.26)    # ...and how long its trail grows
METEOR_ANGLE = (25.0, 60.0)    # its chord, in degrees below the horizon
METEOR_ARC = (0.10, 0.17)      # how far the arc bows up, x the chord
METEOR_CLEAR = 178.0      # dial units kept clear around the dial (and
#                           above it, where the headline is)
METEOR_ALPHA = 0.85
METEOR_W, METEOR_GLOW = 1.8, 6.5     # the trail at the head, its glow...
METEOR_TAPER = 0.25       # ...narrowing to this much at the tail
METEOR_GLOW_ALPHA = 0.14
METEOR_WHITE = 0.5        # the trail whitens toward the head this much
METEOR_HEAD, METEOR_HEAD_GLOW = 1.6, 6.0
METEOR_HEAD_GLOW_ALPHA = 0.6    # at its middle, falling off outward
METEOR_NEAR = 0.45        # surfaced, it is this much bigger than unseen
METEOR_TRAIL_LAG = 0.07   # the trail's light trails the head's this much

# The design's CSS easings.
BREATH = cubic_bezier_fn(0.45, 0.0, 0.25, 1.0)
SOFT = cubic_bezier_fn(0.3, 0.6, 0.2, 1.0)
EASE = cubic_bezier_fn(0.25, 0.1, 0.25, 1.0)
EASE_IN = cubic_bezier_fn(0.42, 0.0, 1.0, 1.0)
EASE_IN_OUT = cubic_bezier_fn(0.42, 0.0, 0.58, 1.0)
_BAND = cubic_bezier_fn(0.2, 0.5, 0.3, 1.0)
_HALO = cubic_bezier_fn(0.2, 0.55, 0.3, 1.0)
_KICK = cubic_bezier_fn(0.2, 0.7, 0.3, 1.0)
_SHOVE = cubic_bezier_fn(0.2, 0.8, 0.3, 1.0)
_RECOIL = cubic_bezier_fn(0.45, 0.0, 0.3, 1.0)
_SURFACE = cubic_bezier_fn(0.45, 0.0, 0.55, 1.0)   # a shooting star rising
_DIVE = cubic_bezier_fn(0.4, 0.0, 0.65, 1.0)       # ...and sinking away


def _linear(u: float) -> float:
    return u


def keyframes(u: float, frames) -> float:
    """CSS-style keyframes at u (0..1): (offset, value, easing to the
    next frame)."""
    a, va, ease = frames[0]
    if u <= a:
        return va
    for i in range(1, len(frames)):
        b, vb, nxt = frames[i]
        if u <= b:
            f = (u - a) / (b - a) if b > a else 1.0
            return va + (vb - va) * ease(f)
        a, va, ease = b, vb, nxt
    return frames[-1][1]


def keyframes2(u: float, first, second):
    """keyframes(u, first), keyframes(u, second) for two tracks with the
    same offsets and easings (a sparkle's twinkle and flash, the aura),
    easing once for both."""
    a, va, ease = first[0]
    wa = second[0][1]
    if u <= a:
        return va, wa
    for i in range(1, len(first)):
        b, vb, nxt = first[i]
        wb = second[i][1]
        if u <= b:
            e = ease((u - a) / (b - a) if b > a else 1.0)
            return va + (vb - va) * e, wa + (wb - wa) * e
        a, va, wa, ease = b, vb, wb, nxt
    return first[-1][1], second[-1][1]


# -- timelines (u: position in the loop; live loops start at the pulse) ------
TICKS_IDLE = ((0, 0.84, BREATH), (0.45, 1.0, BREATH), (1, 0.84, BREATH))
TICKS_LIVE = ((0, 1.0, BREATH), (0.12, 0.8, BREATH), (0.75, 0.8, BREATH),
              (1, 1.0, BREATH))
CHARGE = ((0, 1.0, SOFT), (0.12, 0.0, EASE_IN), (0.75, 0.0, EASE_IN),
          (1, 1.0, _linear))
AURA_IDLE = (((0, 0.94, BREATH), (0.45, 1.03, BREATH), (1, 0.94, BREATH)),
             ((0, 0.7, BREATH), (0.45, 1.0, BREATH), (1, 0.7, BREATH)))
AURA_GATHER = (((0, 1.03, BREATH), (0.55, 0.9, BREATH), (1, 1.03, BREATH)),
               ((0, 0.9, BREATH), (0.55, 0.6, BREATH), (1, 0.9, BREATH)))
AURA_LIVE = (((0, 1.06, BREATH), (0.12, 0.96, BREATH), (0.75, 0.96, BREATH),
              (1, 1.06, BREATH)),
             ((0, 1.0, BREATH), (0.12, 0.72, BREATH), (0.75, 0.72, BREATH),
              (1, 1.0, BREATH)))
STARS_IDLE = ((0, 0.985, BREATH), (0.45, 1.02, BREATH), (1, 0.985, BREATH))
# Live, the star swells as each pulse's band reaches it (~85-170 ms in,
# see band_arrival) and settles back, dipping a hair under on the way.
STARS_LIVE_SWELL = ((0, 1.0, _KICK), (0.02, 1.05, _RECOIL),
                    (0.1, 0.995, EASE_IN_OUT), (0.16, 1.0, _linear),
                    (1, 1.0, _linear))
BEAD = ((0, 0.1, BREATH), (0.12, 0.6, BREATH), (0.3, 0.1, BREATH),
        (1, 0.1, BREATH))
FLARE = ((0, 0.25, _linear), (0.04, 0.9, _linear), (0.16, 0.0, _linear),
         (0.72, 0.0, _linear), (1, 0.25, _linear))
TWINKLE = (((0, 0.14, BREATH), (0.5, 0.55, BREATH), (1, 0.14, BREATH)),
           ((0, 0.8, BREATH), (0.5, 1.0, BREATH), (1, 0.8, BREATH)))
FLASH = (((0, 0.3, _linear), (0.03, 1.0, _linear), (0.15, 0.32, _linear),
          (0.72, 0.26, _linear), (1, 0.6, _linear)),
         ((0, 0.9, _linear), (0.03, 1.4, _linear), (0.15, 0.95, _linear),
          (0.72, 0.9, _linear), (1, 1.08, _linear)))
FLASH_REST = (0.6, 1.08)  # where a flash ends (and waits for the next)
MOTE = ((0, 0.0, _linear), (0.2, 0.55, _linear), (0.75, 0.4, _linear),
        (1, 0.0, _linear))
MOTE_DRIFT = (16.0, -150.0)  # px over a mote's life
# The shooting star's light (u: through its flight), its nearness too: it
# surfaces slowly to a late, rounded peak and sinks away faster as it
# dives, gone a little before the end (its trail's, lagging, after).
METEOR_LIGHT = ((0, 0.0, _SURFACE), (0.56, 1.0, _DIVE), (0.9, 0.0, _linear),
                (1, 0.0, _linear))


def push_track(near: bool):
    """The outward push of a sparkle as the band reaches it (px)."""
    out, back = PUSH_NEAR if near else PUSH_FAR
    return ((0, 0.0, _SHOVE), (0.05, out, _RECOIL), (0.3, back, EASE_IN_OUT),
            (0.44, 0.0, _linear), (1, 0.0, _linear))


_PUSH = {near: push_track(near) for near in (True, False)}


def breath_pos(ms: float, period: float) -> float:
    """0..1 position in a loop of `period` ms."""
    return (ms % period) / period


def band_arrival(distance: float) -> float:
    """ms after a pulse when its band's edge reaches `distance` (dial
    units), on the band's easing."""
    f = (distance - BAND_FROM) / (BAND_TO - BAND_FROM)
    if f <= 0.0:
        return 0.0
    if f >= 1.0:
        return float(BAND_MS)
    lo, hi = 0.0, 1.0
    for _ in range(24):
        mid = (lo + hi) / 2
        if _BAND(mid) < f:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2 * BAND_MS


def charge(cycle, stopped=None) -> float:
    """0..1: the light the ring and star hold, on the disc's CHARGE curve
    (full as each pulse leaves, gathering before the next). None until
    the first pulse, which lights it in FIRST_GLOW_MS. After Stop
    (`stopped` ms into the cycle) the charge in hand fades as the pulse
    in flight does and no new one gathers."""
    if cycle is None:
        return 0.0

    def held(at):
        if at < FIRST_GLOW_MS:
            return SOFT(at / FIRST_GLOW_MS)
        if at < BREATH_MS / 2:      # the first pulse's falls from there
            at -= FIRST_GLOW_MS
        return keyframes(breath_pos(at, BREATH_MS), CHARGE)

    if stopped is None:
        return held(cycle)
    u = (cycle - stopped) / PULSE_FADE_MS
    if u >= 1.0:
        return 0.0
    return held(stopped) * (1.0 - max(0.0, u)) ** 2


def meteor_flight(now: float):
    """The shooting star of the span `now` (ms) falls in: (its start ms,
    the seeded generator that places it). Each span's is the same on
    every run and lies wholly inside it, never at its very edges."""
    index = math.floor(now / METEOR_EVERY_MS)
    rand = _mulberry32((METEOR_SEED + index * 0x9E3779B9) & 0xFFFFFFFF)
    start = (index * METEOR_EVERY_MS
             + (0.1 + 0.8 * rand()) * (METEOR_EVERY_MS - METEOR_MS))
    return start, rand


def meteor_due(now: float, ahead: float = 0.0) -> bool:
    """True while a shooting star is crossing at `now` (ms) or leaves
    within `ahead` ms: the card's clock runs faster for it."""
    for at in (now, now + ahead):
        start, _ = meteor_flight(at)
        if start - ahead <= now < start + METEOR_MS:
            return True
    return False


def meteor_trail_at(t: float):
    """The trail at t (0 its tail, 1 at the head): (alpha factor, white
    mixed in, width factor). Brightest, whitest and widest by the head,
    tapering away behind it (sky.frag's shootingStar draws the same)."""
    return (t * t, METEOR_WHITE * t * t * t,
            METEOR_TAPER + (1.0 - METEOR_TAPER) * t)


def arc_point(arc, s: float) -> QPointF:
    """The point s (0..1) along a shooting star's arc (a, b, c)."""
    a, b, c = arc
    v = 1.0 - s
    return QPointF(v * v * a.x() + 2 * v * s * b.x() + s * s * c.x(),
                   v * v * a.y() + 2 * v * s * b.y() + s * s * c.y())


def arc_tangent(arc, s: float):
    """The unit direction of travel at s along the arc."""
    a, b, c = arc
    x = (1.0 - s) * (b.x() - a.x()) + s * (c.x() - b.x())
    y = (1.0 - s) * (b.y() - a.y()) + s * (c.y() - b.y())
    n = math.hypot(x, y) or 1.0
    return x / n, y / n


def meteor_path(rand, box: QRectF, centre: QPointF, k: float):
    """Where a shooting star flies, from its seeded generator: (its arc
    (start, control, end points), the trail's share of the arc), down one
    side of the sky, bowing up (so it rises into view and dives), clear of
    the dial and the column above it (the headline); None if the card
    leaves no room."""
    clear = METEOR_CLEAR * k
    inset = 0.03 * box.width()
    left, right = box.left() + inset, box.right() - inset
    top, bottom = box.top() + inset, box.bottom() - inset

    def free(x, y):
        if not (left < x < right and top < y < bottom):
            return False
        dx, dy = x - centre.x(), y - centre.y()
        return dx * dx + dy * dy > clear * clear and (
            abs(dx) > clear or dy > 0)

    width = box.width()
    for _ in range(48):
        rightward = rand() < 0.5
        on_right = rand() < 0.5
        lo, hi = ((centre.x() + clear, right) if on_right
                  else (left, centre.x() - clear))
        x = lo + (hi - lo) * rand()
        y = top + (centre.y() - top) * rand()
        angle = math.radians(METEOR_ANGLE[0] + (METEOR_ANGLE[1]
                                                - METEOR_ANGLE[0]) * rand())
        travel = width * (METEOR_TRAVEL[0] + (METEOR_TRAVEL[1]
                                              - METEOR_TRAVEL[0]) * rand())
        trail = width * (METEOR_TRAIL[0] + (METEOR_TRAIL[1]
                                            - METEOR_TRAIL[0]) * rand())
        bow = travel * (METEOR_ARC[0] + (METEOR_ARC[1]
                                         - METEOR_ARC[0]) * rand())
        dx = math.cos(angle) * (1.0 if rightward else -1.0)
        dy = math.sin(angle)
        nx, ny = (dy, -dx) if rightward else (-dy, dx)   # up, off the chord
        arc = (QPointF(x, y),
               QPointF(x + dx * travel / 2 + nx * bow,
                       y + dy * travel / 2 + ny * bow),
               QPointF(x + dx * travel, y + dy * travel))
        if hi > lo and all(free(p.x(), p.y()) for p in (
                arc_point(arc, s / 16) for s in range(17))):
            return arc, min(1.0, trail / travel)
    return None


# -- the scatter ----------------------------------------------------------------
def _mulberry32(seed: int):
    """The design's seeded generator (mulberry32), so the scatter matches."""
    state = seed & 0xFFFFFFFF

    def rand() -> float:
        nonlocal state
        state = (state + 0x6D2B79F5) & 0xFFFFFFFF
        t = ((state ^ (state >> 15)) * (1 | state)) & 0xFFFFFFFF
        t = ((t + (((t ^ (t >> 7)) * (61 | t)) & 0xFFFFFFFF))
             & 0xFFFFFFFF) ^ t
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296.0

    return rand


class Mote:
    __slots__ = ("fx", "fy", "size", "period", "offset")

    def __init__(self, fx, fy, size, period, offset):
        self.fx, self.fy, self.size = fx, fy, size
        self.period, self.offset = period, offset


class Sparkle:
    __slots__ = ("fx", "fy", "size", "alpha", "twinkle", "twinkle_at",
                 "sway", "sway_at")

    def __init__(self, fx, fy, size, alpha, twinkle, twinkle_at, sway,
                 sway_at):
        self.fx, self.fy, self.size, self.alpha = fx, fy, size, alpha
        self.twinkle, self.twinkle_at = twinkle, twinkle_at
        self.sway, self.sway_at = sway, sway_at


def scatter(seed: int = SEED):
    """(motes, sparkles): a seeded scatter, the same on every run. The
    sparkles keep SPARKLE_GAP apart and clear of the dial and headline
    (a random scatter rather than a pattern, which lined up in bands)."""
    rand = _mulberry32(seed)
    motes = []
    for _ in range(MOTE_COUNT):
        x, y = 5 + rand() * 90, 28 + rand() * 66
        size = 1.3 + rand() * 1.6
        period = round(14 + rand() * 12) * 1000.0
        motes.append(Mote(x / 100, y / 100, size, period, rand() * 20000.0))
    sparkles, placed = [], []
    sx, sy = DESIGN_CARD[0] / 100, DESIGN_CARD[1] / 100
    for _ in range(900):
        if len(sparkles) >= SPARKLE_COUNT:
            break
        x, y = 3 + rand() * 94, 5 + rand() * 90
        if ((x - 50) / 24) ** 2 + ((y - 53) / 40) ** 2 < 1:
            continue                       # the dial
        if y < 15 and 22 < x < 78:
            continue                       # the headline
        if y > 90 and 15 < x < 85:
            continue                       # under the dial
        px, py = (x - 50) * sx, (y - 52.5) * sy
        if any(math.hypot(ox - px, oy - py) < SPARKLE_GAP
               for ox, oy in placed):
            continue
        placed.append((px, py))
        size = round(6 + rand() * 7)
        alpha = 0.55 + rand() * 0.45
        twinkle, twinkle_at = (4 + rand() * 6) * 1000, rand() * 8000
        sway, sway_at = (11 + rand() * 10) * 1000, rand() * 20000
        sparkles.append(Sparkle(x / 100, y / 100, size, alpha, twinkle,
                                twinkle_at, sway, sway_at))
    return motes, sparkles


def sparkle_path() -> QPainterPath:
    """An eight-point sparkle, 10 units across (long, short, long...)."""
    path = QPainterPath()
    for k in range(16):
        r = 0.9 if k % 2 else (5.0 if k % 4 == 0 else 2.6)
        a = k * math.pi / 8
        point = QPointF(r * math.sin(a), -r * math.cos(a))
        if k == 0:
            path.moveTo(point)
        else:
            path.lineTo(point)
    path.closeSubpath()
    return path


def _alpha(colour: QColor, alpha: float) -> QColor:
    c = QColor(colour)
    c.setAlphaF(max(0.0, min(1.0, colour.alphaF() * alpha)))
    return c


def _charged_pens(colour: QColor, light: QColor, alpha: float, width: float,
                  glow: float):
    """Pens, drawn in order, for a line of `alpha` holding `glow` (0..1)
    of the charge: soft halos, then the line brightened toward `light`."""
    pens = []
    if glow > 0.01:
        for spread, level in GLOW_HALO:
            pens.append(QPen(_alpha(colour, alpha * level * glow),
                             width * spread))
    pens.append(QPen(_alpha(mix_rgba(colour, light, glow),
                            alpha * (1.0 + GLOW_LIFT * glow)), width))
    return pens


def _square_outline(half: float, pen: QPen):
    """A square's outline (centred, `half` across), as stroking it with
    `pen` would draw it, in pieces Qt rasterizes far faster when rotated
    (about a third of a drawRect): (flat pen, brush, edges, corners). The
    edges are flat-capped lines, the sides stopping short of the corners
    by half the pen; the corners fill the rest of the bevel join, so
    nothing is drawn twice."""
    e = pen.widthF() / 2
    flat = QPen(pen)
    flat.setCapStyle(Qt.PenCapStyle.FlatCap)
    edges = [QLineF(-half, -half, half, -half),
             QLineF(-half, half, half, half),
             QLineF(half, -half + e, half, half - e),
             QLineF(-half, -half + e, -half, half - e)]
    corners = QPainterPath()
    for sx, sy in ((1, -1), (1, 1), (-1, 1), (-1, -1)):
        corners.moveTo(sx * half, sy * (half + e))
        corners.lineTo(sx * (half + e), sy * half)
        corners.lineTo(sx * (half + e), sy * (half - e))
        corners.lineTo(sx * half, sy * (half - e))
        corners.closeSubpath()
    return flat, pen.color(), edges, corners


def _bead(centre: QPointF, k: float, i: int) -> QPointF:
    """Bead i of 8 on the ring, clockwise from the top."""
    angle = math.radians(i * 45.0)
    return QPointF(centre.x() + RING_R * k * math.sin(angle),
                   centre.y() - RING_R * k * math.cos(angle))


class NightSky:
    """The sky at a moment: frame() works out every layer's draw values
    (the card owns the clock and passes the moment in); paint() draws a
    frame with QPainter, and the GPU sky (sky_gpu.py) with a shader."""

    def __init__(self, seed: int = SEED):
        self.motes, self.sparkles = scatter(seed)
        self._path = sparkle_path()
        self._placed_key = None
        self._placed = []
        self._meteor_key = None
        self._meteor_path = None

    def _place(self, box: QRectF, centre: QPointF, k: float, ui: float):
        """Sparkles in card px: (x, y, cos, sin, arrival ms, near, s)."""
        key = (box.x(), box.y(), box.width(), box.height(),
               centre.x(), centre.y(), k, ui)
        if key != self._placed_key:
            self._placed = []
            for s in self.sparkles:
                x = box.x() + s.fx * box.width()
                y = box.y() + s.fy * box.height()
                dx, dy = x - centre.x(), y - centre.y()
                dist = math.hypot(dx, dy) or 1.0
                self._placed.append((
                    x, y, dx / dist, dy / dist, band_arrival(dist / k),
                    dist / ui < NEAR, s))
            self._placed_key = key
        return self._placed

    # -- the moment ----------------------------------------------------------------
    def frame(self, box: QRectF, centre: QPointF, k: float, ui: float,
              now: float, look: dict):
        """Every layer's draw values at `now`, in drawing order (None when
        the sky is not shown yet).

        look: live / gather / error / reveal (0..1 blends), gather_ms (ms
        into starting), cycle (ms since the first pulse, or None),
        stopped (cycle ms at Stop, or None), gain(index) (how much of
        that breath's pulse to show), moving (False under reduced motion:
        no charge), and the colours secondary / accent / accent_light
        (QColor).
        """
        live, gather = look["live"], look["gather"]
        reveal = look["reveal"]
        if reveal <= 0.001:
            return None
        sec, acc = look["secondary"], look["accent"]
        light = look["accent_light"]
        cycle, gain = look["cycle"], look["gain"]
        # Live loops sit just before a pulse until the first one leaves.
        u_live = (breath_pos(cycle, BREATH_MS) if cycle is not None
                  else 1.0 - 1e-6)
        u_idle = breath_pos(now, IDLE_BREATH_MS)
        u_gather = breath_pos(look["gather_ms"], GATHER_MS)

        def blend(idle, gathered, lit):
            v = idle + (gathered - idle) * gather
            return v + (lit - v) * live

        geo = mix_rgba(sec, acc, live)
        aura_idle = keyframes2(u_idle, *AURA_IDLE)
        aura_gather = keyframes2(u_gather, *AURA_GATHER)
        aura_live = keyframes2(u_live, *AURA_LIVE)
        # Starting, the star holds its size; live, each pulse swells it
        # and lights it, from the first.
        stars = blend(keyframes(u_idle, STARS_IDLE), 1.0,
                      keyframes(u_live, STARS_LIVE_SWELL))
        glow = charge(cycle, look["stopped"]) if look["moving"] else 0.0
        mote_tone = mix_rgba(sec, acc, live)
        sparkle_tone = mix_rgba(sec, light, live)
        return {
            "centre": centre, "k": k, "ui": ui, "glow": glow,
            "band": self._band(k, cycle, gain, acc, reveal),
            "motes": self._motes(box, ui, now, mote_tone, reveal),
            "mote_tone": mote_tone,
            "sparkles": self._sparkles(box, centre, k, ui, now, cycle, gain,
                                       live, sparkle_tone, reveal),
            "sparkle_tone": sparkle_tone,
            "meteor": (self._meteor(box, centre, k, ui, now, sparkle_tone,
                                    reveal)
                       if look["moving"] else None),
            "aura": self._aura(k, live, look["error"], reveal, sec, acc,
                               blend(aura_idle[0], aura_gather[0],
                                     aura_live[0]),
                               blend(aura_idle[1], aura_gather[1],
                                     aura_live[1])),
            "geometry": self._geometry(k, now, live, geo, light, glow,
                                       reveal, stars),
            "flares": self._flares(k, cycle, gain, live, geo, reveal),
            "halos": self._halos(k, cycle, gain, acc, light, reveal),
        }

    @staticmethod
    def _events(cycle, gain, delay: float, span: float):
        """(u, gain) of the latest pulse event `delay` ms into a breath, if
        it is still running (u: 0..1 through `span` ms)."""
        if cycle is None:
            return None
        rel = cycle - delay
        index = math.floor(rel / BREATH_MS)
        into = rel - index * BREATH_MS
        if index < 0 or into >= span:
            return None
        g = gain(index)
        return (into / span, g) if g > 0.001 else None

    def _band(self, k, cycle, gain, acc, reveal):
        """The pulse's band: (radius, [(stop, colour)]), or None."""
        event = self._events(cycle, gain, 0.0, BAND_MS)
        if event is None:
            return None
        u, g = event
        e = _BAND(u)
        r = (BAND_FROM + (BAND_TO - BAND_FROM) * e) * k
        strength = BAND_ALPHA * (1.0 - e) * g * reveal
        if strength <= 0.002 or r <= 1.0:
            return None
        return r, ((max(0.0, (r - BAND_INNER * k) / r), _alpha(acc, 0.0)),
                   (max(0.0, (r - BAND_CORE * k) / r),
                    _alpha(acc, strength)),
                   (1.0, _alpha(acc, 0.0)))

    def _motes(self, box, ui, now, colour, reveal):
        """[(centre, glow radius, glow alpha, radius, alpha)]: `colour`
        (the frame's mote_tone) at those alphas, see _alpha. Numbers, not
        colours: made per frame for every mote, a QColor each cost more
        than the rest of the sky's maths."""
        dx, dy = MOTE_DRIFT
        out = []
        for m in self.motes:
            u = breath_pos(now + m.offset, m.period)
            a = keyframes(u, MOTE) * reveal
            if a <= 0.01:
                continue
            x = box.x() + m.fx * box.width() + dx * u * ui
            y = box.y() + m.fy * box.height() + dy * u * ui
            r = m.size / 2 * ui
            out.append((QPointF(x, y), r + 2.6 * ui, a * 0.22, r, a))
        return out

    def _sparkles(self, box, centre, k, ui, now, cycle, gain, live, colour,
                  reveal):
        """[(x, y, size, glow alpha, alpha)]: the sparkle path scaled by
        size x 1.5 (its glow), then by size, in `colour` (the frame's
        sparkle_tone) at those alphas (see _alpha, and _motes)."""
        out = []
        for x, y, cos, sin, arrival, near, s in self._place(box, centre, k,
                                                            ui):
            # Idle: a slow twinkle and a sway along the line to the dial.
            u = breath_pos(now + s.twinkle_at, s.twinkle)
            alpha, scale = keyframes2(u, *TWINKLE)
            u = breath_pos(now + s.sway_at, 2 * s.sway) * 2
            sway = -2.0 + 4.0 * EASE_IN_OUT(u if u <= 1 else 2 - u)
            offset = sway
            if live > 0.001:
                # Live: a flash and a push as the band reaches it.
                lit_alpha, lit_scale = FLASH_REST
                push = 0.0
                if cycle is not None:
                    rel = cycle - arrival
                    index = math.floor(rel / BREATH_MS)
                    g = gain(index) if index >= 0 else 0.0
                    if g > 0.001:
                        v = (rel - index * BREATH_MS) / BREATH_MS
                        flash_alpha, flash_scale = keyframes2(v, *FLASH)
                        lit_alpha += (flash_alpha - lit_alpha) * g
                        lit_scale += (flash_scale - lit_scale) * g
                        push = keyframes(v, _PUSH[near]) * g
                alpha += (lit_alpha - alpha) * live
                scale += (lit_scale - scale) * live
                offset += (push - offset) * live
            a = alpha * s.alpha * reveal
            if a <= 0.01:
                continue
            out.append((x + cos * offset * ui, y + sin * offset * ui,
                        s.size / 10.0 * ui * scale,
                        a * 0.22, a))
        return out

    def _meteor(self, box, centre, k, ui, now, colour, reveal):
        """The shooting star in flight, or None: {arc: its (start,
        control, end) points; s0, s1: the trail's stretch of it (0..1,
        the head at s1); back, front: the points there; colour: the
        trail's (its alpha, the trail's light); head: the head's alpha;
        white: how white its core burns; width, glow, head_r, head_glow:
        px, as near as it is}."""
        start, rand = meteor_flight(now)
        u = (now - start) / METEOR_MS
        if not 0.0 <= u < 1.0:
            return None
        key = (start, box.x(), box.y(), box.width(), box.height(),
               centre.x(), centre.y(), k)
        if key != self._meteor_key:
            self._meteor_key = key
            self._meteor_path = meteor_path(rand, box, centre, k)
        if self._meteor_path is None:
            return None
        arc, span = self._meteor_path
        # An even pace along the arc: it rises slowing, dives speeding up.
        s1 = u
        near = keyframes(u, METEOR_LIGHT)
        trailing = keyframes(max(0.0, u - METEOR_TRAIL_LAG), METEOR_LIGHT)
        # The trail grows as it surfaces and is drawn down after it.
        s0 = max(0.0, s1 - span * trailing)
        light = trailing * METEOR_ALPHA * reveal
        head = near * METEOR_ALPHA * reveal
        if max(light, head) <= 0.005 or s1 - s0 < 1e-3:
            return None
        size = 1.0 + METEOR_NEAR * (near - 1.0)
        return {"arc": arc, "s0": s0, "s1": s1,
                "back": arc_point(arc, s0), "front": arc_point(arc, s1),
                "colour": _alpha(colour, light), "head": head,
                "white": 0.55 + 0.4 * near * near,
                "width": METEOR_W * ui * size, "glow": METEOR_GLOW * ui * size,
                "head_r": METEOR_HEAD * ui * size,
                "head_glow": METEOR_HEAD_GLOW * ui * size}

    @staticmethod
    def _aura(k, live, error, reveal, sec, acc, scale, alpha):
        """[(disc radius, gradient radius, [(stop, colour)])]."""
        r = AURA_R * k * scale
        ray = AURA_RAY * k * scale
        gold = (1.0 - live) * (1.0 - 0.6 * error) * alpha * reveal
        out = []
        for colour, a, stops in (
                (sec, gold, ((0.0, 0.12), (0.32, 0.045), (0.62, 0.0))),
                (acc, live * alpha * reveal,
                 ((0.0, 0.24), (0.34, 0.08), (0.64, 0.0)))):
            if a <= 0.005:
                continue
            out.append((r, ray, tuple((at, _alpha(colour, level * a))
                                      for at, level in stops)))
        return out

    @staticmethod
    def _geometry(k, now, live, colour, light, glow, reveal, stars):
        """The ring, the star and the beads."""
        width = max(1.0, k)
        # The star: its two squares swell together (idle, and with each
        # pulse), turning slowly, charged with the ring.
        scale = stars
        idle_a, live_a = STAR_ALPHA
        pens = _charged_pens(colour, light,
                             (idle_a + (live_a - idle_a) * live) * reveal,
                             1.0 / scale, glow)
        turn = 360.0 * now / STAR_TURN_MS
        squares = [(STAR_HALF, angle + turn, pens) for angle in (0.0, 45.0)]
        beads = [_alpha(colour, keyframes(breath_pos(now - i * BEAD_STEP,
                                                     BEAD_MS), BEAD) * reveal)
                 for i in range(8)]
        return {
            "ring": _charged_pens(colour, light, RING_ALPHA * reveal, width,
                                  glow),
            "ring_r": RING_R * k,
            "stars_scale": k * scale,
            "squares": squares,
            "beads": beads, "bead_r": BEAD_R * k}

    @staticmethod
    def _flares(k, cycle, gain, live, colour, reveal):
        """The beads flare as each pulse's band passes them: (colour,
        radius), or None."""
        if live <= 0.001:
            return None
        a = FLARE[0][1]                  # waiting for the first pulse
        if cycle is not None:
            rel = cycle - FLARE_DELAY
            index = math.floor(rel / BREATH_MS)
            u = (rel - index * BREATH_MS) / BREATH_MS
            a = keyframes(u, FLARE)
            if u < FLARE[2][0]:          # the flash belongs to a pulse
                rest = FLARE[0][1] * (1.0 - u / FLARE[2][0])
                a = rest + (a - rest) * (gain(index) if index >= 0 else 0.0)
        a *= live * reveal
        if a <= 0.005:
            return None
        return _alpha(colour, a), FLARE_R * k

    def _halos(self, k, cycle, gain, acc, light, reveal):
        """[(radius, [pens])]: the halos leaving the disc."""
        out = []
        for delay in HALO_DELAYS:
            event = self._events(cycle, gain, float(delay), HALO_MS)
            if event is None:
                continue
            u, g = event
            e = _HALO(u)
            grow = 1.0 + HALO_GROWTH * e
            a = HALO_ALPHA * (1.0 - e) * g * reveal
            if a <= 0.005:
                continue
            out.append((DISC_R * k * grow, [
                QPen(_alpha(colour, a * level), width * k * grow)
                for colour, width, level in ((acc, 10.0, 0.07),
                                             (acc, 5.0, 0.14),
                                             (light, 1.0, 1.0))]))
        return out

    # -- painting ------------------------------------------------------------------
    def paint(self, p, box: QRectF, clip, centre: QPointF, k: float,
              ui: float, now: float, look: dict) -> None:
        """Paint the sky at `now` (see frame) inside `clip`."""
        f = self.frame(box, centre, k, ui, now, look)
        if f is None:
            return
        p.save()
        p.setClipPath(clip)
        p.setPen(Qt.PenStyle.NoPen)
        if f["band"] is not None:
            r, stops = f["band"]
            grad = QRadialGradient(centre, r)
            for at, colour in stops:
                grad.setColorAt(at, colour)
            p.setBrush(grad)
            p.drawEllipse(centre, r, r)
        tone = f["mote_tone"]
        for at, glow_r, glow, r, alpha in f["motes"]:
            p.setBrush(_alpha(tone, glow))
            p.drawEllipse(at, glow_r, glow_r)
            p.setBrush(_alpha(tone, alpha))
            p.drawEllipse(at, r, r)
        tone = f["sparkle_tone"]
        for x, y, size, glow, alpha in f["sparkles"]:
            p.save()
            p.translate(x, y)
            p.scale(size * 1.5, size * 1.5)
            p.setBrush(_alpha(tone, glow))
            p.drawPath(self._path)
            p.scale(1 / 1.5, 1 / 1.5)
            p.setBrush(_alpha(tone, alpha))
            p.drawPath(self._path)
            p.restore()
        if f["meteor"] is not None:
            self._paint_meteor(p, f["meteor"])
        for r, ray, stops in f["aura"]:
            grad = QRadialGradient(centre, ray)
            for at, colour in stops:
                grad.setColorAt(at, colour)
            p.setBrush(grad)
            p.drawEllipse(centre, r, r)
        self._paint_geometry(p, centre, k, f["geometry"])
        if f["flares"] is not None:
            colour, r = f["flares"]
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(colour)
            for i in range(8):
                p.drawEllipse(_bead(centre, k, i), r, r)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for r, pens in f["halos"]:
            for pen in pens:
                p.setPen(pen)
                p.drawEllipse(centre, r, r)
        p.restore()

    @staticmethod
    def _paint_meteor(p, m) -> None:
        """The trail (its glow, then itself) as a strip along the arc,
        tapering back from the head, lit and whitened along it by
        meteor_trail_at; then the head: a soft glow and a near-white
        core."""
        arc, s0, s1 = m["arc"], m["s0"], m["s1"]
        back, front, colour = m["back"], m["front"], m["colour"]
        white = QColor(255, 255, 255, colour.alpha())   # whitens, no more
        p.setPen(Qt.PenStyle.NoPen)
        steps = 16
        spine = []
        for i in range(steps + 1):
            t = i / steps
            s = s0 + (s1 - s0) * t
            tx, ty = arc_tangent(arc, s)
            spine.append((arc_point(arc, s), -ty, tx, meteor_trail_at(t)[2]))
        for width, level in ((m["glow"], METEOR_GLOW_ALPHA),
                             (m["width"], 1.0)):
            # Along the chord, which the trail's short stretch of the
            # gentle arc barely leaves.
            grad = QLinearGradient(back, front)
            for t in (0.0, 0.25, 0.5, 0.7, 0.85, 1.0):
                lit, whiten, _ = meteor_trail_at(t)
                grad.setColorAt(t, _alpha(mix_rgba(colour, white, whiten),
                                          lit * level))
            half = width / 2
            left = [QPointF(pt.x() + nx * half * w, pt.y() + ny * half * w)
                    for pt, nx, ny, w in spine]
            right = [QPointF(pt.x() - nx * half * w, pt.y() - ny * half * w)
                     for pt, nx, ny, w in reversed(spine)]
            p.setBrush(QBrush(grad))
            p.drawPolygon(QPolygonF(left + right))
        head = m["head"]
        if head <= 0.005:
            return
        rgb = QColor(colour)
        rgb.setAlphaF(1.0)
        glow_r = m["head_glow"]
        glow = QRadialGradient(front, glow_r)      # falls off as (1 - r)^2
        for at in (0.0, 0.25, 0.5, 0.75, 1.0):
            glow.setColorAt(at, _alpha(rgb, head * METEOR_HEAD_GLOW_ALPHA
                                       * (1.0 - at) ** 2))
        p.setBrush(QBrush(glow))
        p.drawEllipse(front, glow_r, glow_r)
        core = mix_rgba(rgb, QColor(255, 255, 255), m["white"])
        p.setBrush(_alpha(core, head))
        p.drawEllipse(front, m["head_r"], m["head_r"])

    @staticmethod
    def _paint_geometry(p, centre, k, g) -> None:
        p.setBrush(Qt.BrushStyle.NoBrush)
        for pen in g["ring"]:
            p.setPen(pen)
            p.drawEllipse(centre, g["ring_r"], g["ring_r"])

        p.save()
        p.translate(centre)
        p.scale(g["stars_scale"], g["stars_scale"])
        outlines = {}
        for half, angle, pens in g["squares"]:
            key = (half, id(pens))
            if key not in outlines:
                outlines[key] = [_square_outline(half, pen) for pen in pens]
            p.save()
            p.rotate(angle)
            for pen, brush, edges, corners in outlines[key]:
                p.setPen(pen)
                p.drawLines(edges)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(brush)
                p.drawPath(corners)
            p.restore()
        p.restore()

        p.setPen(Qt.PenStyle.NoPen)
        for i, colour in enumerate(g["beads"]):
            p.setBrush(colour)
            p.drawEllipse(_bead(centre, k, i), g["bead_r"], g["bead_r"])
