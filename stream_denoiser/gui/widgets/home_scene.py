"""
Poise Voice Isolator - the Vigil Home card as one Qt Quick scene

SkyView (widgets/sky_gpu.py) draws the card and its night sky, and the
dial's ring of ticks, in a QQuickWidget under the dial and the headline,
which stay widgets painted over it: each of their paints is a raster
paint of the window's backing store, uploaded and composed with the
view's frame on every change. HomeScene draws them in the view too
(assets/sky/home.qml: the sky, then HomeDial.qml, then the headline),
so the whole card is one scene graph frame and those widgets paint
nothing.

They stay in the card's layout all the same, where they are: the dial
widget still takes the pointer, the wheel, the keys, focus and its
tooltip, and works out its look each frame (DialButton.face_state); the
headline label still lays out and wraps its text, and its TextSwap
still runs the swaps. HomeScene only draws them, from properties set on
the GUI thread (no Python runs on Qt Quick's render thread). The disc
and the power glyph are a small shader (assets/sky/disc.frag); the text
is Qt Quick Text, which mists and smokes as the widgets did
(SmokeText.qml).

Only for a breathing theme's dial (Vigil, Eclipse: the themes with the
sky). POISE_HOME_SCENE=0 keeps the sky-only view (for comparing).
"""
import os

from PyQt6.QtCore import QObject
from PyQt6.QtGui import QColor, QVector4D

from .sky_gpu import SKY_QML, SkyView

HOME_QML = SKY_QML.with_name("home.qml")
# HomeDial.qml's ShaderEffect "disc": the uniforms of disc.frag.
DISC_UNIFORMS = frozenset((
    "faceTop", "faceMid", "faceEdge", "accentRgb", "rimRgb", "charge",
    "focusRgba", "glyphRgba", "stem", "unit"))


def home_scene_wanted() -> bool:
    """False when POISE_HOME_SCENE=0 asks for the sky-only view."""
    return os.environ.get("POISE_HOME_SCENE") != "0"


def _vec(colour: QColor) -> QVector4D:
    return QVector4D(colour.redF(), colour.greenF(), colour.blueF(),
                     colour.alphaF())


class HomeScene(SkyView):
    """The card, its sky, the dial and the headline in one view."""

    QML = HOME_QML

    def __init__(self, parent=None):
        super().__init__(parent)
        top = self.rootObject()
        self._dial = top.findChild(QObject, "dial") if top else None
        self._disc = (self._dial.findChild(QObject, "disc")
                      if self._dial is not None else None)
        self._headline = (top.findChild(QObject, "headline")
                          if top else None)
        self._dial_sent = {}
        self._text_sent = {}

    def _sky_item(self):
        top = self.rootObject()
        loader = top.findChild(QObject, "sky") if top is not None else None
        return loader.property("item") if loader is not None else None

    @property
    def ok(self) -> bool:
        return (super().ok and self._dial is not None
                and self._disc is not None and self._headline is not None)

    # -- the dial ------------------------------------------------------------------
    def place_dial(self, x: float, y: float, k: float) -> None:
        """The dial's design square: its top left in the card and its
        scale (design units to px)."""
        self._send(self._dial, self._dial_sent, "x", x)
        self._send(self._dial, self._dial_sent, "y", y)
        self._send(self._dial, self._dial_sent, "scale", k)

    def show_dial(self, state) -> None:
        """DialButton.face_state (None: no dial drawn here)."""
        dial, sent = self._dial, self._dial_sent
        self._send(dial, sent, "visible", state is not None)
        if state is None:
            return
        for name, value in state.items():
            if name in DISC_UNIFORMS:
                if isinstance(value, QColor):
                    value = _vec(value)
                self._send(self._disc, sent, "disc." + name, value)
            else:
                self._send(dial, sent, name, value)

    # -- the headline ---------------------------------------------------------------
    def show_headline(self, state) -> None:
        """PatternCard._headline_state (None: none drawn here)."""
        item, sent = self._headline, self._text_sent
        self._send(item, sent, "shown", state is not None)
        if state is None:
            return
        for name, value in state.items():
            self._send(item, sent, name, value)

    @staticmethod
    def _send(item, sent: dict, key: str, value) -> None:
        if sent.get(key) != value:
            item.setProperty(key.rpartition(".")[2], value)
            sent[key] = value
