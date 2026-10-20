"""
Poise Voice Isolator - Lattice Patterns

The line work a lattice theme draws behind the dial (see PatternCard).
Each theme names one by its "lattice" key (themes.STYLE_DEFAULTS):

- rub_el_hizb: a 64px tile of a square, its 45-degree twin, spokes and a
  centre dot. The original; PatternCard draws it itself (_tile_path).
- khatam: eight-pointed stars (khatam) and crosses, drawn as strapwork:
  each line a band of two fine lines. A 72px tile.
- twelve: twelve-pointed stars on a hexagonal grid, six-pointed stars
  between them (a Mamluk field). A 128 x 222px tile.
- dome: eight-pointed stars wrapped round the dial like the plan of a
  muqarnas dome: small beside it, growing towards the card's edges. One
  piece the size of the card, as strapwork.

The Islamic ones come from Hankin's polygons-in-contact method: polygons
laid edge to edge, and from the middle of every edge two rays go into
the polygon at a fixed angle to the edge, each stopping where it meets
the ray from the next edge. A ray leaves an edge in a straight line with
the one in the polygon across it, so the lines run on unbroken.

khatam, twelve and dome are centred on the dial (a star behind it);
rub_el_hizb keeps its fixed place. Geometry is in design px; the card
scales it by the UI scale.
"""
import math
from functools import lru_cache

from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QPainterPath

#: Per pattern: tile (w, h) in design px (None: drawn whole, see
#: dome_path), stroke width, the cleared middle of a strapwork band (0:
#: plain lines), dots (x, y, r) per tile, layer opacity and its mask
#: ("card": clear round the card's middle; "dial": clear round the dial).
SPECS = {
    "rub_el_hizb": {"tile": (64.0, 64.0), "stroke": 1.0, "gap": 0.0,
                    "dots": ((32.0, 32.0, 2.5),), "opacity": 0.2,
                    "mask": "card", "centred": False},
    "khatam": {"tile": (72.0, 72.0), "stroke": 3.6, "gap": 1.6,
               "dots": ((0.0, 0.0, 2.0), (72.0, 0.0, 2.0), (0.0, 72.0, 2.0),
                        (72.0, 72.0, 2.0), (36.0, 36.0, 1.4)),
               "opacity": 0.22, "mask": "card", "centred": True},
    "twelve": {"tile": (128.0, 128.0 * math.sqrt(3.0)), "stroke": 1.0,
               "gap": 0.0,
               "dots": tuple((x, y, 2.4) for x, y in (
                   (0.0, 0.0), (128.0, 0.0), (64.0, 64.0 * math.sqrt(3.0)),
                   (0.0, 128.0 * math.sqrt(3.0)),
                   (128.0, 128.0 * math.sqrt(3.0)))),
               "opacity": 0.22, "mask": "card", "centred": True},
    "dome": {"tile": None, "stroke": 3.4, "gap": 1.4, "dots": (),
             "opacity": 0.26, "mask": "dial", "centred": True},
}
DEFAULT = "rub_el_hizb"

KHATAM_ANGLE = 45.0     # contact angles, degrees from the edge
TWELVE_ANGLE = 60.0
DOME_ANGLE = 67.5
DOME_FOLDS = 16         # stars round the dial
DOME_R0 = 150.0         # design px from the dial to the first ring of stars
# The dome's mask: clear out to DOME_CLEAR of DOME_MASK_R, full by
# DOME_FULL (a circle round the dial).
DOME_MASK_R = 400.0
DOME_CLEAR, DOME_FULL = 0.36, 0.92


def spec(kind: str) -> dict:
    """The pattern `kind`'s spec (unknown: the default)."""
    return SPECS.get(kind, SPECS[DEFAULT])


def _regular(cx, cy, n, r, a0):
    return [(cx + r * math.cos(a0 + 2 * math.pi * i / n),
             cy + r * math.sin(a0 + 2 * math.pi * i / n)) for i in range(n)]


def _rotate(v, a):
    c, s = math.cos(a), math.sin(a)
    return (v[0] * c - v[1] * s, v[0] * s + v[1] * c)


def hankin(poly, angle_deg: float):
    """The polygons-in-contact motif of one convex polygon: a list of
    (m1, p, m2) polylines, from the middle of one edge to where its ray
    meets the next edge's, and on to that edge's middle."""
    area = sum(poly[i - 1][0] * poly[i][1] - poly[i][0] * poly[i - 1][1]
               for i in range(len(poly)))
    if area < 0:   # one winding, so a +angle ray turns inwards
        poly = poly[::-1]
    theta = math.radians(angle_deg)
    n = len(poly)
    rays = []
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        d = ((b[0] - a[0]) / length, (b[1] - a[1]) / length)
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        rays.append((mid, _rotate(d, theta), _rotate((-d[0], -d[1]), -theta)))
    out = []
    for i in range(n):
        m1, ra, _ = rays[i]
        m2, _, rb = rays[(i + 1) % n]
        den = ra[0] * rb[1] - ra[1] * rb[0]
        if abs(den) < 1e-9:
            continue
        t = ((m2[0] - m1[0]) * rb[1] - (m2[1] - m1[1]) * rb[0]) / den
        reach = max(math.hypot(v[0] - m1[0], v[1] - m1[1]) for v in poly)
        if not 0 < t < reach:
            continue   # the rays part: no meeting inside this polygon
        out.append((m1, (m1[0] + ra[0] * t, m1[1] + ra[1] * t), m2))
    return out


def _path(polylines) -> QPainterPath:
    path = QPainterPath()
    for m1, p, m2 in polylines:
        path.moveTo(QPointF(*m1))
        path.lineTo(QPointF(*p))
        path.lineTo(QPointF(*m2))
    return path


def _near(poly, w, h, pad):
    return (max(v[0] for v in poly) > -pad and min(v[0] for v in poly) < w + pad
            and max(v[1] for v in poly) > -pad
            and min(v[1] for v in poly) < h + pad)


def _tiling_488(t, i_range, j_range, place=lambda v: v):
    """4.8.8 (octagons on the lattice points, squares between) in tiles
    of side `t`, each vertex put through `place`."""
    ro = (t / 2) / math.cos(math.pi / 8)
    rs = t * math.tan(math.pi / 8) / math.sqrt(2.0)
    for i in i_range:
        for j in j_range:
            yield [place(v) for v in _regular(i * t, j * t, 8, ro, math.pi / 8)]
            yield [place(v) for v in _regular((i + .5) * t, (j + .5) * t, 4,
                                              rs, 0.0)]


@lru_cache(maxsize=None)
def tile_path(kind: str) -> QPainterPath:
    """One tile of `kind` (khatam or twelve), in design px with a star
    centred on the tile's corner. It holds the line work of every polygon
    that reaches the tile, so drawn clipped to its cell it is whole."""
    w, h = spec(kind)["tile"]
    lines = []
    if kind == "khatam":
        for poly in _tiling_488(w, range(-1, 3), range(-1, 3)):
            if _near(poly, w, h, 1.0):
                lines += hankin(poly, KHATAM_ANGLE)
    elif kind == "twelve":
        # 4.6.12: dodecagons on a hexagonal lattice, squares between
        # neighbours, hexagons in the gaps (edge e, w = (3 + sqrt 3) e).
        e = w / (3 + math.sqrt(3.0))
        rd = e / (2 * math.sin(math.pi / 12))
        for i in range(-1, 3):
            for j in range(-1, 3):
                for cx, cy in ((i * w, j * h), (i * w + w / 2, j * h + h / 2)):
                    polys = [_regular(cx, cy, 12, rd, math.pi / 12)]
                    for k in range(3):
                        a = math.radians(60 * k)
                        polys.append(_regular(cx + math.cos(a) * w / 2,
                                              cy + math.sin(a) * w / 2, 4,
                                              e / math.sqrt(2.0),
                                              a + math.pi / 4))
                    for a in (math.radians(30), math.radians(90)):
                        polys.append(_regular(
                            cx + math.cos(a) * w / math.sqrt(3.0),
                            cy + math.sin(a) * w / math.sqrt(3.0), 6, e,
                            a + math.pi / 6))
                    for poly in polys:
                        if _near(poly, w, h, 1.0):
                            lines += hankin(poly, TWELVE_ANGLE)
    else:
        raise ValueError(f"no tile for lattice {kind!r}")
    return _path(lines)


def dome_path(cx: float, cy: float, w: float, h: float,
              k: float = 1.0) -> QPainterPath:
    """The dome round (cx, cy) for a w x h card (px), at UI scale `k`:
    4.8.8 in DOME_FOLDS columns, wrapped round the centre by a log-polar
    map (column -> angle, row -> log radius), so each ring of stars is a
    little larger than the one inside it."""
    step = 2 * math.pi / DOME_FOLDS
    r0 = DOME_R0 * k

    def place(v):
        a = v[0] * step - math.pi / 2
        r = r0 * math.exp(v[1] * step)
        return (cx + r * math.cos(a), cy + r * math.sin(a))

    reach = math.hypot(max(cx, w - cx), max(cy, h - cy)) + 2 * r0
    rows = int(math.ceil(math.log(max(reach / r0, 1.0)) / step)) + 1
    lines = []
    for poly in _tiling_488(1.0, range(DOME_FOLDS), range(-1, rows + 1),
                            place):
        mx = sum(v[0] for v in poly) / len(poly)
        my = sum(v[1] for v in poly) / len(poly)
        if math.hypot(mx - cx, my - cy) < 0.4 * r0:
            continue   # too small to see, and under the dial
        if _near(poly, w, h, 2.0):
            lines += hankin(poly, DOME_ANGLE)
    return _path(lines)
