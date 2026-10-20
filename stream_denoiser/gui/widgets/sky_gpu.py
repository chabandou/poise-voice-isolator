"""
Poise Voice Isolator - Night Sky on the GPU

The dial card's night sky (see sky.py) drawn by a fragment shader in a
Qt Quick window embedded over the card (SkyView). The window covers the
card in a rectangle, so the shader also draws what it hides: the page's
gradient around the card's rounded corners and the card's own fill and
border, and the dial's ring of ticks and its needle (show_ring: they
change on most frames). The widgets on the card, the headline and the
dial's disc and readout, cannot draw over a native window: the card
hands their images in and the view draws them on top (show_layer), and
the dial its pointer.

NightSky.frame still works out every layer at each moment, so the sky
moves exactly as the QPainter one does; only the drawing leaves the CPU.

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

from PyQt6 import sip
from PyQt6.QtCore import (QEvent, QPoint, QRect, QRectF, Qt, QTimer, QUrl,
                          pyqtSignal)
from PyQt6.QtGui import (QColor, QEnterEvent, QHelpEvent, QImage,
                         QMouseEvent, QPainter, QRegion, QVector4D,
                         QWheelEvent)
from PyQt6.QtQml import QQmlComponent, QQmlImageProviderBase
from PyQt6.QtQuick import (QQuickImageProvider, QQuickItem, QQuickView,
                           QSGRendererInterface)
from PyQt6.QtWidgets import QApplication, QWidget

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


# -- what sits on the sky ------------------------------------------------------------
_LAYER_QML = b"import QtQuick\nImage { cache: false; smooth: false; visible: false }\n"
TIP_MS = 700   # hovering this long over the dial asks for its tooltip
_MASKED = QRegion(QRect(-16, -16, 1, 1))   # nothing of the window shows


class _Layers(QQuickImageProvider):
    """The widgets drawn on the sky, as their latest images by name (the
    id changes with each, so it reloads; nothing is cached)."""

    def __init__(self):
        super().__init__(QQmlImageProviderBase.ImageType.Image)
        self.images = {}

    def requestImage(self, image_id, requested_size):  # noqa: N802 (Qt)
        image = self.images.get(image_id.split("/", 1)[0])
        if image is None:
            image = QImage(1, 1, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0)
        return image, image.size()


class _Input(QQuickItem):
    """Over the dial's image: hands what the pointer does there on to the
    dial widget under the view, which keeps its own logic (and takes the
    focus, and gives its cursor and tooltip). It draws nothing: only the
    GUI thread runs it (the scene renders on a thread of its own)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.target = None
        self.setAcceptedMouseButtons(Qt.MouseButton.AllButtons)
        self.setAcceptHoverEvents(True)
        self._tip = QTimer(self)
        self._tip.setSingleShot(True)
        self._tip.setInterval(TIP_MS)
        self._tip.timeout.connect(self._ask_tip)
        self._tip_at = None

    def _mouse(self, kind, event, button=None, buttons=None) -> None:
        target = self.target
        if target is None or sip.isdeleted(target):
            return
        QApplication.sendEvent(target, QMouseEvent(
            kind, event.position(), event.globalPosition(),
            event.button() if button is None else button,
            event.buttons() if buttons is None else buttons,
            event.modifiers()))
        self.setCursor(target.cursor())

    def mousePressEvent(self, event):  # noqa: N802 (Qt override)
        self._tip.stop()
        target = self.target
        if target is not None and not sip.isdeleted(target):
            # The view takes no focus (so keys stay with the dial): a
            # click on it raises Poise and focuses the dial itself.
            window = target.window()
            if not window.isActiveWindow():
                window.activateWindow()
            if target.focusPolicy() & Qt.FocusPolicy.ClickFocus:
                target.setFocus(Qt.FocusReason.MouseFocusReason)
        self._mouse(QEvent.Type.MouseButtonPress, event)
        event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802 (Qt override)
        self._mouse(QEvent.Type.MouseMove, event)
        event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802 (Qt override)
        self._mouse(QEvent.Type.MouseButtonRelease, event)
        event.accept()

    def mouseDoubleClickEvent(self, event):  # noqa: N802 (Qt override)
        self._mouse(QEvent.Type.MouseButtonDblClick, event)
        event.accept()

    def hoverEnterEvent(self, event):  # noqa: N802 (Qt override)
        target = self.target
        if target is not None and not sip.isdeleted(target):
            QApplication.sendEvent(target, QEnterEvent(
                event.position(), event.scenePosition(),
                event.globalPosition()))
        self.hoverMoveEvent(event)

    def hoverMoveEvent(self, event):  # noqa: N802 (Qt override)
        self._mouse(QEvent.Type.MouseMove, event, Qt.MouseButton.NoButton,
                    Qt.MouseButton.NoButton)
        self._tip_at = (event.position().toPoint(),
                        event.globalPosition().toPoint())
        self._tip.start()

    def hoverLeaveEvent(self, event):  # noqa: N802 (Qt override)
        self._tip.stop()
        target = self.target
        if target is not None and not sip.isdeleted(target):
            QApplication.sendEvent(target, QEvent(QEvent.Type.Leave))

    def wheelEvent(self, event):  # noqa: N802 (Qt override)
        target = self.target
        if target is not None and not sip.isdeleted(target):
            self._tip.stop()
            QApplication.sendEvent(target, QWheelEvent(
                event.position(), event.globalPosition(), event.pixelDelta(),
                event.angleDelta(), event.buttons(), event.modifiers(),
                event.phase(), event.inverted()))
        event.accept()

    def _ask_tip(self) -> None:
        target = self.target
        if self._tip_at is None or target is None or sip.isdeleted(target):
            return
        QApplication.sendEvent(target, QHelpEvent(
            QEvent.Type.ToolTip, *self._tip_at))


class SkyView(QWidget):
    """The card's sky on the GPU, with the card under it and what sits on
    it, in a Qt Quick window embedded over the card. `failed` fires if
    the scene graph cannot draw it here.

    The window is a native child of the top-level window, not of the
    card: inside a scroll area (Home's page is one) Qt would make every
    widget above it native, and the page slides' and crossfades' overlays
    would draw under them. It follows the card instead (clipped to what
    of it shows), and draws the whole card, offset. Unlike a QQuickWidget,
    the window it sits in stays a plain raster one: no GPU composition of
    the whole window, about half the GPU memory.

    Widgets over the card cannot draw over a native window, so the card
    hands their images in (show_layer) and the dial its pointer, through
    an item over its image. hold() masks the window away and paints a
    still of the sky here, an ordinary widget under the card's (which
    draw themselves again), while something needs one: an entrance
    effect on the card, a page slide's snapshot. The window keeps
    drawing meanwhile, so it is current when it shows again."""

    failed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        quick = QQuickView()
        quick.setFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)
        quick.setColor(QColor(0, 0, 0))
        engine = quick.engine()
        self._ring_images = _RingImages()     # (kept: Qt does not own it)
        engine.addImageProvider("sky", self._ring_images)
        self._layer_images = _Layers()
        engine.addImageProvider("layer", self._layer_images)
        self._component = QQmlComponent(engine, QUrl.fromLocalFile(
            str(SKY_QML)))
        self._root = (self._component.create()
                      if self._component.isReady() else None)
        self._quick = quick
        self._layers = {}
        self._layer_n = 0
        self._input = None
        if self._root is not None:
            self._root.setParentItem(quick.contentItem())
            self._root.setParent(quick.contentItem())
            for name in ("text", "dial"):
                layer = QQmlComponent(engine)
                layer.setData(_LAYER_QML, QUrl())
                item = layer.create()
                item.setParentItem(self._root)
                item.setParent(self._root)
                self._layers[name] = item
            self._input = _Input(self._root)
        self._box = QWidget.createWindowContainer(quick, self.window())
        self._box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._box.hide()
        self.destroyed.connect(self._box.deleteLater)
        self._sent = {}
        self._ring_key = None
        self._ring_n = 0
        self._checked = False
        self._holds = set()
        self._still = None
        self._masked = False
        self._awaiting = 0         # released: frames to wait for
        self._on_live = None
        self._late = QTimer(self)  # (no frame came: show it anyway)
        self._late.setSingleShot(True)
        self._late.setInterval(250)
        self._late.timeout.connect(self._go_live)
        self._showing = QTimer(self)
        self._showing.setSingleShot(True)
        self._showing.setInterval(0)
        self._showing.timeout.connect(self._show_box)
        self.quiet = False     # paint nothing (the card is drawing a layer)
        quick.sceneGraphError.connect(self._on_error)
        quick.afterFrameEnd.connect(self._check_api,
                                    Qt.ConnectionType.QueuedConnection)
        quick.frameSwapped.connect(self._swapped,
                                   Qt.ConnectionType.QueuedConnection)
        # Follow the card: it and everything it sits in, up to the window.
        widget = parent
        while widget is not None and widget is not self._box.parentWidget():
            widget.installEventFilter(self)
            widget = widget.parentWidget()

    @property
    def ok(self) -> bool:
        return self._root is not None

    def errors(self):
        return self._component.errors()

    def quickWindow(self):  # noqa: N802 (QQuickWidget's name)
        return self._quick

    def grabFramebuffer(self) -> QImage:  # noqa: N802 (QQuickWidget's name)
        return self._quick.grabWindow()

    def discard(self) -> None:
        """Hide and delete the view and its window."""
        self._box.hide()
        self.hide()
        self.deleteLater()

    def _on_error(self, *_) -> None:
        self.failed.emit()

    def _check_api(self) -> None:
        """After the first frame: the software renderer runs no shaders."""
        if self._checked:
            return
        self._checked = True
        try:
            self._quick.afterFrameEnd.disconnect(self._check_api)
        except TypeError:
            pass
        api = self._quick.rendererInterface().graphicsApi()
        if api in _SOFTWARE:
            self.failed.emit()

    # -- where the window goes ---------------------------------------------------
    def eventFilter(self, watched, event):  # noqa: N802 (Qt override)
        if event.type() in (QEvent.Type.Move, QEvent.Type.Resize,
                            QEvent.Type.Show, QEvent.Type.Hide):
            self._place()
        return False

    def resizeEvent(self, event):  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        if self._root is not None:
            self._root.setWidth(self.width())
            self._root.setHeight(self.height())
        self._place()

    def showEvent(self, event):  # noqa: N802 (Qt override)
        super().showEvent(event)
        self._place()

    def hideEvent(self, event):  # noqa: N802 (Qt override)
        self._place()
        super().hideEvent(event)

    def _card_rects(self):
        """(the card, the part of it that shows) in the window's frame."""
        top = self._box.parentWidget()
        rect = QRect(self.mapTo(top, QPoint(0, 0)), self.size())
        shown = rect
        widget = self.parentWidget()
        while widget is not None and widget is not top:
            shown = shown.intersected(QRect(widget.mapTo(top, QPoint(0, 0)),
                                            widget.size()))
            widget = widget.parentWidget()
        return rect, shown

    def _place(self) -> None:
        """The window over what shows of the card, the card drawn offset
        in it (masked away while held); hidden out of sight."""
        if self._root is None or sip.isdeleted(self._box):
            return
        rect, shown = self._card_rects()
        if self.isVisible() and not shown.isEmpty():
            self._box.setGeometry(shown)
            self._root.setX(rect.x() - shown.x())
            self._root.setY(rect.y() - shown.y())
            self._mask()
            if self._box.isVisible():
                self._box.raise_()
            elif not self._showing.isActive():
                # Not from inside a show (the window's own, say): a native
                # window shown there deadlocks with its render thread.
                self._showing.start()
        else:
            self._showing.stop()
            self._box.hide()

    def _show_box(self) -> None:
        rect, shown = self._card_rects()
        if self.isVisible() and not shown.isEmpty():
            self._box.show()
            self._box.raise_()

    def _mask(self) -> None:
        """Held, or until a frame of what it now shows is up: masked, the
        window vanishes from the screen yet keeps drawing, current the
        moment it shows again."""
        masked = bool(self._holds or self._awaiting)
        if masked != self._masked:
            self._masked = masked
            self._quick.setMask(_MASKED if masked else QRegion())

    # -- held as a still ------------------------------------------------------------
    @property
    def held(self) -> bool:
        return bool(self._holds)

    def hold(self, reason: str) -> None:
        """Paint a still of the sky and the card here, under the card's
        widgets, instead of showing the window, until every hold is
        released."""
        first = not self._holds and not self._awaiting
        self._holds.add(reason)
        if first:
            self._grab_still()
            self.repaint()    # on screen before the window goes
        self._mask()

    def release(self, reason: str, on_live=None) -> None:
        """Let `reason` go; the last one shows the window again once it
        has drawn a frame of the scene as it is now, then calls on_live()
        (the card hands it the dial again)."""
        if reason not in self._holds:
            return
        self._holds.discard(reason)
        if self._holds:
            return
        self._on_live = on_live
        if self._box.isVisible() or self._showing.isActive():
            # Two: one may have been drawn before the scene caught up.
            self._awaiting = 2
            self._quick.update()
            self._late.start()
        else:
            self._go_live()

    def _swapped(self) -> None:
        if self._awaiting:
            self._awaiting -= 1
            if self._awaiting:
                self._quick.update()
            else:
                self._go_live()

    def _go_live(self) -> None:
        self._awaiting = 0
        self._late.stop()
        if self._holds:
            return
        self._mask()
        self._still = None
        self.update()
        on_live, self._on_live = self._on_live, None
        if on_live is not None:
            on_live()

    def _grab_still(self) -> None:
        """The sky and the card under it, without what sits on it (the
        card's widgets draw themselves over the still)."""
        if self._root is None:
            return
        if self._box.size() != self.size():
            # The whole card (the window may show only part of it).
            self._box.setGeometry(QRect(self._box.pos(), self.size()))
            self._root.setX(0)
            self._root.setY(0)
        shown = {name: item.property("visible")
                 for name, item in self._layers.items()}
        for item in self._layers.values():
            item.setProperty("visible", False)
        self._root.setProperty("tickRing", _OFF)
        still = self._quick.grabWindow()
        for name, item in self._layers.items():
            item.setProperty("visible", shown[name])
        self._root.setProperty("tickRing", self._sent.get("tickRing", _OFF))
        self._place()
        if not still.isNull():
            still.setDevicePixelRatio(self._quick.devicePixelRatio())
            self._still = still

    def paintEvent(self, event):  # noqa: N802 (Qt override)
        if self._still is not None and not self.quiet:
            p = QPainter(self)
            p.drawImage(0, 0, self._still)
            p.end()

    # -- what sits on it ---------------------------------------------------------------
    def show_layer(self, name: str, image: QImage, rect: QRectF) -> None:
        """Draw `image` (a widget over the card) at `rect` in the card."""
        item = self._layers.get(name)
        if item is None:
            return
        self._layer_images.images[name] = image
        self._layer_n += 1
        item.setProperty("x", rect.x())
        item.setProperty("y", rect.y())
        item.setProperty("width", rect.width())
        item.setProperty("height", rect.height())
        item.setProperty("source",
                         QUrl(f"image://layer/{name}/{self._layer_n}"))
        item.setProperty("visible", True)

    def hide_layer(self, name: str) -> None:
        item = self._layers.get(name)
        if item is not None and item.property("visible"):
            item.setProperty("visible", False)
            self._layer_images.images.pop(name, None)

    def take_input(self, widget, rect: QRectF = None) -> None:
        """Hand the pointer over `rect` (in the card) on to `widget`, or
        to nothing."""
        if self._input is None:
            return
        self._input.target = widget
        if widget is None or rect is None:
            self._input.setVisible(widget is not None)
            return
        self._input.setVisible(True)
        self._input.setX(rect.x())
        self._input.setY(rect.y())
        self._input.setWidth(rect.width())
        self._input.setHeight(rect.height())

    # -- the scene ---------------------------------------------------------------------
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
        top = values.get("fillTop")
        if top is not None and sent.get("_clear") != top:
            # Under the first frame: the card's colour, not a flash.
            sent["_clear"] = top
            self._quick.setColor(QColor.fromRgbF(top.x(), top.y(), top.z()))
    