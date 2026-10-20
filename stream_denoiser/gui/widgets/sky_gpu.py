"""
Poise Voice Isolator - Night Sky on the GPU

The dial card's night sky (see sky.py) drawn by a fragment shader in a
QQuickWidget that covers the card. A widget window composes such a view
as a texture under its other widgets, in a rectangle, so the shader also
draws what the view hides: the page's gradient around the card's rounded
corners and the card's own fill and border. The dial and the headline
stay ordinary widgets over it, except for the dial's ring of ticks and
its needle, which the shader draws too (show_ring): they change on most
frames, and so the dial need not repaint with the sky to breathe.

NightSky.frame still works out every layer at each moment, so the sky
moves exactly as the QPainter one does; only the drawing leaves the CPU.
And since the sky is composed rather than painted, a frame of it no
longer repaints the dial over it.

The shader is assets/sky/sky.frag, baked into sky.frag.qsb (with
sky.qml, one property per uniform) by tools/bake_sky_shader.py.
POISE_SKY_RASTER=1 keeps the QPainter sky; PatternCard also falls back
to it when Qt Quick cannot run here (no GPU API, or the software
renderer, which has no shaders).
"""
import os
import re
import struct
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QVector4D
from PyQt6.QtQml import QQmlImageProviderBase
from PyQt6.QtQuick import QQuickImageProvider, QSGRendererInterface
from PyQt6.QtQuickWidgets import QQuickWidget

from .sky import (
    METEOR_GLOW_ALPHA, METEOR_HEAD_GLOW_ALPHA, METEOR_TAPER, METEOR_WHITE,
    MOTE_COUNT, SPARKLE_COUNT,
)

SKY_QML = Path(__file__).resolve().parent.parent / "assets" / "sky" / "sky.qml"
SHADER_MOTES = 18       # m0..m17 in sky.frag
SHADER_SPARKLES = 26    # s0..s25
assert MOTE_COUNT <= SHADER_MOTES and SPARKLE_COUNT <= SHADER_SPARKLES

RING_COLUMNS, RING_ROWS = 56, 7   # ringData in sky.frag
NEEDLE_COLUMN = 55
_OFF = QVector4D(0.0, 0.0, 0.0, 0.0)
# The shooting star's look, as sky.py draws it (meteorStyle in sky.frag).
_METEOR_STYLE = QVector4D(METEOR_TAPER, METEOR_WHITE, METEOR_GLOW_ALPHA,
                          METEOR_HEAD_GLOW_ALPHA)
_SOFTWARE = {QSGRendererInterface.GraphicsApi.Unknown,
             QSGRendererInterface.GraphicsApi.Software}


def gpu_sky_wanted() -> bool:
    """False when POISE_SKY_RASTER=1 asks for the QPainter sky."""
    return os.environ.get("POISE_SKY_RASTER") != "1"


def _rgba(colour: QColor) -> QVector4D:
    return QVector4D(colour.redF(), colour.greenF(), colour.blueF(),
                     colour.alphaF())


def _rgb(colour: QColor, w: float = 1.0) -> QVector4D:
    return QVector4D(colour.redF(), colour.greenF(), colour.blueF(), w)


# -- the card under the sky -----------------------------------------------------
def qss_stops(fill: str):
    """[(position, QColor)] of a QSS gradient (or [(0, colour)] for a
    plain colour)."""
    stops = re.findall(r"stop\s*:\s*([0-9.]+)\s+(#[0-9a-fA-F]{3,8})", fill)
    if stops:
        return [(float(at), QColor(c)) for at, c in stops]
    return [(0.0, QColor(fill.strip()))]


def qss_radial(fill: str):
    """(cx, cy, radius) of a QSS qradialgradient (the centre and a
    radius that covers everything for anything else)."""
    found = {key: float(v) for key, v in re.findall(
        r"\b(cx|cy|radius)\s*:\s*([0-9.]+)", fill)}
    return found.get("cx", 0.5), found.get("cy", 0.5), found.get("radius",
                                                                 1e6)


def card_base(size, radius: float, border: int, border_colour: QColor,
              card_fill: str, page_fill: str, page_offset, page_size) -> dict:
    """The uniforms for what the view covers besides the sky: the card
    (size, its QSS radius and border width and colour, its fill, a
    vertical gradient) and the page behind its corners (the page's QSS
    fill, a radial gradient or a colour, and where the card sits in
    it)."""
    w, h = size
    fill = qss_stops(card_fill)
    page = qss_stops(page_fill)[:4]
    page += [page[-1]] * (4 - len(page))
    cx, cy, ray = qss_radial(page_fill)
    base = {
        "card": QVector4D(radius, border, max(0.0, radius - border), 0.0),
        "fillTop": _rgb(fill[0][1]),
        "fillBottom": _rgb(fill[-1][1]),
        "borderRgba": _rgba(border_colour),
        "page": QVector4D(page_offset[0], page_offset[1],
                          max(1.0, page_size[0]), max(1.0, page_size[1])),
        "pageGrad": QVector4D(cx, cy, ray, 0.0),
    }
    for i, (at, colour) in enumerate(page):
        base[f"pageStop{i}"] = _rgb(colour, at)
    return base


# -- a frame of the sky as uniforms -----------------------------------------------
def _alphas(tone: QColor):
    """alpha -> sky._alpha(tone, alpha).alphaF() (the colour's alpha as Qt
    keeps it), on one reused QColor rather than one per mote or sparkle."""
    scratch, base = QColor(tone), tone.alphaF()

    def alpha_of(alpha: float) -> float:
        scratch.setAlphaF(max(0.0, min(1.0, base * alpha)))
        return scratch.alphaF()

    return alpha_of


def frame_uniforms(frame, box) -> dict:
    """NightSky.frame's layers as the shader's uniforms (everything off
    for no frame)."""
    u = {name: _OFF for name in _SKY_UNIFORMS}
    if frame is None:
        return u
    centre, k, ui = frame["centre"], frame["k"], frame["ui"]
    u["skyClip"] = QVector4D(box.x(), box.y(), box.width(), box.height())
    u["geo"] = QVector4D(centre.x(), centre.y(), k, ui)

    if frame["band"] is not None:
        r, ((clear, _), (core, colour), _) = frame["band"]
        u["band"] = QVector4D(r, clear, core, colour.alphaF())
        u["bandRgb"] = _rgb(colour)

    tone, alpha_of = frame["mote_tone"], _alphas(frame["mote_tone"])
    for i, (at, _, _, r, alpha) in enumerate(frame["motes"]):
        u["moteRgb"] = _rgb(tone)
        u[f"m{i}"] = QVector4D(at.x(), at.y(), r, alpha_of(alpha))
    tone, alpha_of = frame["sparkle_tone"], _alphas(frame["sparkle_tone"])
    for i, (x, y, size, _, alpha) in enumerate(frame["sparkles"]):
        u["sparkRgb"] = _rgb(tone)
        u[f"s{i}"] = QVector4D(x, y, size, alpha_of(alpha))
    m = frame["meteor"]
    if m is not None:
        a, b, c = m["arc"]
        u["meteor"] = QVector4D(a.x(), a.y(), b.x(), b.y())
        u["meteorEnd"] = QVector4D(c.x(), c.y(), m["s0"], m["s1"])
        u["meteorRgba"] = _rgba(m["colour"])
        u["meteorGeo"] = QVector4D(m["width"], m["glow"], m["head_r"],
                                   m["head_glow"])
        u["meteorHead"] = QVector4D(m["head"], m["white"], 0.0, 1.0)
        u["meteorStyle"] = _METEOR_STYLE

    for i, (r, ray, stops) in enumerate(frame["aura"]):
        (_, c0), (p1, c1), (p2, c2) = stops
        u[f"auraRgb{i}"] = _rgb(c0)
        u[f"auraA{i}"] = QVector4D(c0.alphaF(), c1.alphaF(), c2.alphaF(), 0)
        u[f"auraP{i}"] = QVector4D(p1, p2, r, ray)

    g = frame["geometry"]
    widths = [0.0, 0.0, 0.0]
    for i, pen in enumerate(g["ring"]):
        u[f"ringPen{i}"] = _rgba(pen.color())
        widths[i] = pen.widthF()
    u["ring"] = QVector4D(g["ring_r"], *widths)
    # No shared turn: each square's angle carries its star's own kick.
    u["stars"] = QVector4D(g["stars_scale"], 0, 0, 0)
    (half, first, pens), (_, second, _) = g["squares"]
    u["squares"] = QVector4D(first, second, 0, 0)
    widths = [0.0, 0.0, 0.0]
    for i, pen in enumerate(pens):
        u[f"starPen{i}"] = _rgba(pen.color())
        widths[i] = pen.widthF()
    u["starW"] = QVector4D(*widths, half)
    beads = [c.alphaF() for c in g["beads"]]
    u["beadsA"] = QVector4D(*beads[:4])
    u["beadsB"] = QVector4D(*beads[4:])
    u["beadRgb"] = _rgb(g["beads"][0])
    flare_r = 0.0
    if frame["flares"] is not None:
        colour, flare_r = frame["flares"]
        u["flare"] = _rgba(colour)
    u["beadGeo"] = QVector4D(g["bead_r"], flare_r, 0, 0)

    for i, (r, pens) in enumerate(frame["halos"]):
        light = pens[2]
        u[f"halo{i}"] = QVector4D(r, light.widthF(), light.color().alphaF(),
                                  1.0)
        u["haloAcc"] = _rgb(pens[0].color())
        u["haloLight"] = _rgb(light.color())
    return u


# -- the dial's ring as a texture ----------------------------------------------------
def ring_image(strokes) -> QImage:
    """DialButton._ring_strokes as sky.frag's ringData: a column per tick
    and one for the needle; rows: the stroke's rgb, its glow's rgb, (the
    stroke's alpha, the glow's, which breathe: 128 the stroke, 64 the
    glow), the stroke's inner and outer radius and the glow's (two bytes
    each, x 256). Missing strokes stay clear."""
    data = bytearray(RING_COLUMNS * RING_ROWS * 4)
    row = RING_COLUMNS * 4
    pack = struct.pack_into
    for _, r0, r1, rgba, _, slot, breathes in strokes:
        column, tick = divmod(slot, 2)        # even slots are glows
        at = column * 4
        # rgb (0xAARRGGBB -> R, G, B, X), the alpha, the radii (x 256).
        pack(">I", data, (0 if tick else row) + at, (rgba << 8) & 0xFFFFFFFF)
        data[2 * row + at + (0 if tick else 1)] = rgba >> 24
        if breathes:
            data[2 * row + at + 2] |= 128 if tick else 64
        pack(">H", data, (3 if tick else 5) * row + at,
             max(0, min(0xFFFF, round(r0 * 256))))
        pack(">H", data, (4 if tick else 6) * row + at,
             max(0, min(0xFFFF, round(r1 * 256))))
    return QImage(bytes(data), RING_COLUMNS, RING_ROWS, row,
                  QImage.Format.Format_RGBX8888).copy()


def ring_uniform(over: float, strokes) -> QVector4D:
    """tickRing: the stretch, the needle's angle and glow width, on."""
    angle = glow = 0.0
    for stroke_angle, _, _, _, width, slot, _ in strokes:
        if slot == 2 * NEEDLE_COLUMN:
            angle, glow = stroke_angle, width
    return QVector4D(over, angle, glow, 1.0)


class _RingImages(QQuickImageProvider):
    """Hands the view's Image the ring's latest texture (the id changes
    with each, so it reloads; nothing is cached)."""

    def __init__(self):
        super().__init__(QQmlImageProviderBase.ImageType.Image)
        self.image = ring_image(())

    def requestImage(self, image_id, requested_size):  # noqa: N802 (Qt)
        return self.image, self.image.size()


_SKY_UNIFORMS = (
    ["skyClip", "geo", "band", "bandRgb", "moteRgb", "sparkRgb", "meteor",
     "meteorEnd", "meteorRgba", "meteorGeo", "meteorHead", "meteorStyle",
     "ring",
     "ringPen0", "ringPen1", "ringPen2", "stars",
     "squares", "starW", "starPen0", "starPen1", "starPen2", "beadsA",
     "beadsB", "beadRgb", "beadGeo", "flare",
     "haloAcc", "haloLight"]
    + [f"m{i}" for i in range(SHADER_MOTES)]
    + [f"s{i}" for i in range(SHADER_SPARKLES)]
    + [f"{name}{i}" for i in range(2)
       for name in ("auraRgb", "auraA", "auraP")]
    + [f"halo{i}" for i in range(3)])


class SkyView(QQuickWidget):
    """The card's sky (and the card under it) on the GPU. `failed` fires
    if the scene graph cannot draw it here."""

    failed = pyqtSignal()
    QML = SKY_QML          # the scene (see HomeScene for more in it)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self._ring_images = _RingImages()     # (kept: Qt does not own it)
        self.engine().addImageProvider("sky", self._ring_images)
        self.setSource(QUrl.fromLocalFile(str(self.QML)))
        self._root = self._sky_item()
        self._sent = {}
        self._ring_key = None
        self._ring_n = 0
        self._checked = False
        window = self.quickWindow()
        window.sceneGraphError.connect(lambda *_: self.failed.emit())
        window.afterFrameEnd.connect(self._check_api)

    def _sky_item(self):
        """The ShaderEffect of sky.qml, whose properties are the sky's
        uniforms."""
        return self.rootObject()

    @property
    def ok(self) -> bool:
        return (self._root is not None
                and self.status() == QQuickWidget.Status.Ready)

    def _check_api(self) -> None:
        """After the first frame: the software renderer runs no shaders."""
        if self._checked:
            return
        self._checked = True
        api = self.quickWindow().rendererInterface().graphicsApi()
        if api in _SOFTWARE:
            self.failed.emit()

    def show_ring(self, over, strokes, breath: float = 1.0) -> None:
        """The dial's ring (DialButton.ring_frame), or none: strokes None
        hands it back to the dial."""
        key = None if strokes is None else (over, strokes)
        if strokes is not None:
            self.show_breath(breath)
        if key == self._ring_key:
            return
        self._ring_key = key
        if strokes is None:
            self._set("tickRing", _OFF)
            return
        self._ring_images.image = ring_image(strokes)
        self._ring_n += 1
        self._root.setProperty("ringDataSource",
                               f"image://sky/ringData/{self._ring_n}")
        self._set("tickRing", ring_uniform(over, strokes))

    def show_breath(self, breath: float) -> None:
        """The idle breath's alpha, for the strokes marked breathing."""
        self._set("tickBreath", breath)

    def place_ring(self, x: float, y: float, k: float) -> None:
        """Where the dial is: its exact centre in the card and its
        scale (dial units to px)."""
        self._set("tickAt", QVector4D(x, y, k, 0.0))

    def _set(self, name, value) -> None:
        if self._sent.get(name) != value:
            self._root.setProperty(name, value)
            self._sent[name] = value

    def show_frame(self, frame, box, base: dict) -> None:
        """Send what changed since the last frame."""
        values = frame_uniforms(frame, box)
        values.update(base)
        sent = self._sent
        root = self._root
        for name, value in values.items():
            if sent.get(name) != value:
                root.setProperty(name, value)
                sent[name] = value
