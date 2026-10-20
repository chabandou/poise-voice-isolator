"""The dial card over the GPU sky: what sits on it is drawn by the view
(layers), the dial takes its pointer through it, and the view is held as
a still while something needs one (widgets/pattern_card.py, sky_gpu.py)."""
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("PyQt6.QtQuick")

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def app():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _pump(app, secs=0.2):
    end = time.time() + secs
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


@pytest.fixture
def vigil(monkeypatch):
    from stream_denoiser.gui import themes
    monkeypatch.delenv("POISE_NO_ANIM", raising=False)
    monkeypatch.delenv("POISE_REDUCE_MOTION", raising=False)
    monkeypatch.delenv("POISE_SKY_RASTER", raising=False)
    before = themes.current_id()
    themes.set_current("vigil")
    yield
    themes.set_current(before)


def _fake_view_class():
    """A stand-in SkyView that records what the card hands it (the suite
    runs offscreen, where Qt Quick has no GPU)."""
    from PyQt6.QtCore import QRectF, pyqtSignal
    from PyQt6.QtWidgets import QWidget

    class FakeView(QWidget):
        failed = pyqtSignal()
        made = []

        def __init__(self, parent=None):
            super().__init__(parent)
            self.ok = True
            self.quiet = False
            self.layers, self.input, self.holds = {}, None, set()
            FakeView.made.append(self)

        def errors(self):
            return []

        def show_frame(self, *args):
            pass

        def show_ring(self, *args):
            pass

        def show_breath(self, *args):
            pass

        def place_ring(self, *args):
            pass

        def show_layer(self, name, image, rect):
            self.layers[name] = (image, QRectF(rect))

        def hide_layer(self, name):
            self.layers.pop(name, None)

        def take_input(self, widget, rect=None):
            self.input = (widget, rect)

        def hold(self, reason):
            self.holds.add(reason)

        def release(self, reason, on_live=None):
            self.holds.discard(reason)
            if not self.holds and on_live is not None:
                on_live()

        @property
        def held(self):
            return bool(self.holds)

        def discard(self):
            self.hide()
            self.deleteLater()

    return FakeView


def _card(app, monkeypatch, effect=False):
    """A Vigil card like Home's (headline, error line, dial) over a fake
    view; returns (card, title, error, dial, view)."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QGraphicsOpacityEffect, QLabel, QVBoxLayout
    from stream_denoiser.gui.widgets import sky_gpu
    from stream_denoiser.gui.widgets.dial import DialButton
    from stream_denoiser.gui.widgets.pattern_card import PatternCard
    fake = _fake_view_class()
    monkeypatch.setattr(sky_gpu, "SkyView", fake)
    card = PatternCard()
    card.resize(900, 520)
    layout = QVBoxLayout(card)
    title = QLabel("Ready to isolate")
    error = QLabel("Something went wrong")
    error.setVisible(False)
    dial = DialButton()
    layout.addWidget(title)
    layout.addWidget(error)
    layout.addStretch(1)                       # (as Home lays it out)
    layout.addWidget(dial, alignment=Qt.AlignmentFlag.AlignHCenter)
    layout.addStretch(1)
    card.set_ping_origin(dial)
    if effect:
        card.setGraphicsEffect(QGraphicsOpacityEffect(card))
    card.show()
    _pump(app, 0.3)
    assert fake.made, "no view made"
    return card, title, error, dial, fake.made[-1]


def test_the_view_draws_the_dial_and_the_headline(app, vigil, monkeypatch):
    from PyQt6.QtCore import QPoint, QRectF, QSizeF, QPointF
    card, title, _, dial, view = _card(app, monkeypatch)
    image, rect = view.layers["dial"]
    assert rect == QRectF(QPointF(dial.mapTo(card, QPoint(0, 0))),
                          QSizeF(dial.size()))
    dpr = dial.devicePixelRatioF()
    assert (image.width(), image.height()) == (round(dial.width() * dpr),
                                               round(dial.height() * dpr))
    assert view.input == (dial, rect)          # its pointer goes to it
    _, band = view.layers["text"]
    assert band.contains(QRectF(title.geometry()))
    assert not band.intersects(QRectF(dial.geometry()).adjusted(
        0, 40, 0, 0))                           # (the dial is its own)
    assert view.holds == set()                 # nothing needs a still
    card.close()


def test_the_headline_layer_is_clear_round_its_text(app, vigil, monkeypatch):
    """The card's own (QSS) fill stays out of it: the sky shows round
    the words."""
    card, title, _, _, view = _card(app, monkeypatch)
    card.setStyleSheet("PatternCard { background: #335577; }")
    title.setText("Ready to isolate now")
    _pump(app)
    image, band = view.layers["text"]
    assert image.pixelColor(2, 2).alpha() == 0
    alphas = {image.pixelColor(x, image.height() // 2).alpha()
              for x in range(0, image.width(), 3)}
    assert 0 in alphas and max(alphas) > 0     # clear, and the words
    card.close()


def test_what_changes_on_the_card_redraws_its_layer(app, vigil, monkeypatch):
    from PyQt6.QtCore import QRectF
    card, title, error, dial, view = _card(app, monkeypatch)
    before = view.layers["text"][0].cacheKey()
    title.setText("Isolating your voice")
    _pump(app)
    assert view.layers["text"][0].cacheKey() != before
    band = view.layers["text"][1]
    error.setVisible(True)
    _pump(app)
    grown = view.layers["text"][1]
    assert grown.contains(QRectF(error.geometry())) and grown != band
    error.setVisible(False)
    _pump(app)
    assert not view.layers["text"][1].contains(QRectF(error.geometry()))
    # The error line moved the dial: its layer and pointer followed.
    _, rect = view.layers["dial"]
    assert rect.topLeft().toPoint() == dial.pos()
    card.close()


def test_the_dial_draws_on_the_view_not_under_it(app, vigil, monkeypatch):
    card, _, _, dial, view = _card(app, monkeypatch)
    before = view.layers["dial"][0].cacheKey()
    dial.update()                              # (its own paint: nothing)
    _pump(app)
    assert view.layers["dial"][0].cacheKey() != before
    card.close()


def test_the_mirror_image_is_what_the_dial_paints(app, vigil):
    from PyQt6.QtCore import QPoint
    from PyQt6.QtGui import QImage, QPainter, QRegion
    from stream_denoiser.gui.widgets.dial import DialButton
    dial = DialButton()
    dial.resize(dial.sizeHint())
    now = dial._ms()
    dial._ms = lambda: now                     # one moment for both
    painted = QImage(dial.size(), QImage.Format.Format_ARGB32_Premultiplied)
    painted.fill(0)
    p = QPainter(painted)
    dial.render(p, QPoint(), QRegion(), dial.RenderFlag.DrawChildren)
    p.end()
    calls = []
    dial.set_mirror(lambda: calls.append(1))
    mirrored = dial.mirror_image()
    assert mirrored.convertToFormat(painted.format()) == painted
    dial.update()
    assert calls                               # updates ask the mirror
    dial.deleteLater()


def test_an_entrance_effect_holds_the_view_till_it_lands(app, vigil,
                                                         monkeypatch):
    card, _, _, _, view = _card(app, monkeypatch, effect=True)
    assert view.holds == {"entrance"}          # ("showing" let go)
    card.setGraphicsEffect(None)
    _pump(app, 0.2)
    assert view.holds == set()
    card.close()


_CLICK_CHECK = """
import sys, time
sys.path.insert(0, {root!r})
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
app = QApplication([])
from stream_denoiser.gui import themes
themes.set_current("vigil")
from stream_denoiser.gui.widgets.dial import DialButton
from stream_denoiser.gui.widgets.pattern_card import PatternCard
window = QWidget()
window.resize(1000, 600)
card = PatternCard(window)
card.setGeometry(40, 40, 900, 520)
layout = QVBoxLayout(card)
layout.addWidget(QLabel("Ready to isolate"))
dial = DialButton()
layout.addWidget(dial, alignment=Qt.AlignmentFlag.AlignHCenter)
card.set_ping_origin(dial)
window.show()
def pump(secs):
    end = time.time() + secs
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)
pump(2.5)
view = card._view
if view is None:
    print("skip: no GPU sky here"); sys.exit()
quick = view.quickWindow()
toggled = []
dial.toggled_state.connect(toggled.append)
at = dial.mapTo(window, dial.rect().center()) - view._box.pos()
QTest.mouseClick(quick, Qt.MouseButton.LeftButton,
                 Qt.KeyboardModifier.NoModifier, at)
pump(0.3)
from PyQt6.QtCore import QRect
over = view._box.geometry() == QRect(card.mapTo(window, QPoint(0, 0)),
                                     card.size())
print("result", view._box.isVisible(), view.held, view._masked, over,
      toggled, dial.hasFocus())
"""


@pytest.mark.skipif(sys.platform != "win32", reason="the GPU sky's home")
def test_a_click_on_the_view_reaches_the_dial():
    """On the real platform: the view shows (unmasked) right over the
    card, and a click on the dial's place in it starts the dial and
    focuses it."""
    env = dict(os.environ, QT_QPA_PLATFORM="windows")
    env.pop("POISE_SKY_RASTER", None)
    run = subprocess.run(
        [sys.executable, "-c", _CLICK_CHECK.format(root=str(ROOT))],
        capture_output=True, text=True, timeout=60, env=env)
    out = run.stdout.strip().splitlines()
    assert run.returncode == 0 and out, run.stderr
    if out[-1].startswith("skip:"):
        pytest.skip(out[-1][6:])
    assert out[-1] == "result True False False True [True] True"
