"""The Vigil Home card as one Qt Quick scene (widgets/home_scene.py)."""
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("PyQt6.QtQuickWidgets")

ROOT = Path(__file__).resolve().parent.parent
SKY = ROOT / "stream_denoiser" / "gui" / "assets" / "sky"


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def vigil():
    from stream_denoiser.gui import themes
    before = themes.current_id()
    themes.set_current("vigil")
    yield
    themes.set_current(before)


def _qml_properties(name: str) -> set:
    text = (SKY / name).read_text(encoding="utf-8")
    return set(re.findall(r"^\s*property\s+\w+\s+(\w+)", text, re.M))


def _disc_uniforms() -> set:
    frag = (SKY / "disc.frag").read_text(encoding="utf-8")
    block = re.search(r"uniform\s+buf\s*\{(.*?)\};", frag, re.S).group(1)
    block = re.sub(r"//[^\n]*", "", block)
    return {d.split()[1] for d in block.split(";") if d.strip()
            and not d.split()[1].startswith("qt_")}


def test_the_disc_shader_is_baked_and_declared():
    from stream_denoiser.gui.widgets.home_scene import DISC_UNIFORMS
    assert (SKY / "disc.frag.qsb").stat().st_size > 0
    assert _disc_uniforms() == DISC_UNIFORMS
    # HomeDial.qml's ShaderEffect declares each one (as a property).
    assert DISC_UNIFORMS <= _qml_properties("HomeDial.qml")


def test_the_dial_sends_what_the_scene_declares(app, vigil):
    """Every value face_state sends is a disc uniform or a property of
    HomeDial.qml, and every HomeDial property is sent; none of the
    disc's uniforms is named like an Item property (it would set that
    instead of reaching the shader)."""
    from PyQt6.QtQuick import QQuickItem
    from stream_denoiser.gui.widgets.dial import DialButton
    from stream_denoiser.gui.widgets.home_scene import DISC_UNIFORMS
    dial = DialButton()
    state = dial.face_state()
    dial.deleteLater()
    qml = _qml_properties("HomeDial.qml") - DISC_UNIFORMS
    assert set(state) == DISC_UNIFORMS | qml
    meta = QQuickItem().metaObject()
    item = {meta.property(i).name() for i in range(meta.propertyCount())}
    assert not (DISC_UNIFORMS & item)


def test_a_face_sink_takes_the_paints(app, vigil):
    """With a face sink the dial paints nothing: the repaints asked for
    in one pass of the event loop become one push of its look (and its
    ring); without one it paints again."""
    from stream_denoiser.gui.widgets.dial import DialButton
    dial = DialButton()
    dial.resize(300, 300)
    dial.show()
    faces, rings = [], []
    dial.set_ring_sink(lambda *ring: rings.append(ring))
    dial.set_face_sink(faces.append)
    end = time.time() + 0.2                   # the show's own paints
    while time.time() < end:
        app.processEvents()
    faces.clear()
    rings.clear()
    painted = []
    paint = dial._paint_core
    dial._paint_core = lambda *a: painted.append(1) or paint(*a)
    for _ in range(5):
        dial.update()
    app.processEvents()
    assert len(faces) == 1 and len(rings) == 1 and not painted
    dial.grab()                               # a paint Qt asks for
    app.processEvents()
    assert not painted and len(faces) == 2
    dial.hide()
    dial.update()
    app.processEvents()
    assert faces[-1] is None                  # hidden: no dial drawn
    dial.show()
    dial.set_face_sink(None)
    dial.set_ring_sink(None)
    dial.grab()
    assert painted                            # painted here again
    dial.close()


def test_the_dials_look_follows_its_state(app, vigil):
    from stream_denoiser.gui.widgets.dial import LABELS
    from stream_denoiser.gui.widgets.dial import DialButton
    dial = DialButton()
    idle = dial.face_state()
    assert [label[0] for label in idle["labels"]] == [LABELS[0]]
    assert idle["charge"] == 0.0 and idle["coreScale"] == 1.0
    assert idle["focusRgba"].alpha() == 0     # no keyboard focus
    texts = [d[0] for d in idle["digits"] if d[2] > 0.5]
    assert texts == ["5", "0"]                # -50 dB
    dial._press = 1.0
    assert dial.face_state()["coreScale"] == pytest.approx(0.93)
    dial.deleteLater()


def test_the_headline_is_mirrored(app, vigil):
    """mirror_text: the scene gets the label's text, font, colour, box
    and the swap's fade; the label stops painting."""
    from PyQt6.QtWidgets import QLabel, QVBoxLayout
    from stream_denoiser.gui.animations import TextSwap
    from stream_denoiser.gui.widgets.pattern_card import PatternCard

    class Scene:                              # stands in for HomeScene
        def __init__(self):
            self.shown = []

        def show_headline(self, state):
            self.shown.append(state)

        def show_dial(self, state):
            pass

        def __getattr__(self, name):          # show_frame, place_ring...
            return lambda *args: None

    card = PatternCard()
    label = QLabel("Ready to isolate")
    label.setWordWrap(True)
    QVBoxLayout(card).addWidget(label)
    card.resize(600, 300)
    card._view_failed = True                  # no real view
    card.show()
    app.processEvents()
    scene = Scene()
    card._view = scene
    swap = TextSwap(label, smoke=6.0)
    card.mirror_text(label, swap)
    state = scene.shown[-1]
    assert state["text"] == "Ready to isolate" and state["alpha"] == 1.0
    assert state["wrapMode"] == 1 and state["width"] == label.width()
    assert not label.updatesEnabled()
    # A page slide hides the page before its snapshot: the headline
    # stays in the scene (only hiding the label itself drops it).
    card.hide()
    assert scene.shown[-1] is not None
    card.show()
    label.hide()
    assert scene.shown[-1] is None
    label.show()
    swap.set_text("Isolating")
    end = time.time() + 2.0
    while swap.busy and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    fades = [s["alpha"] for s in scene.shown if s is not None]
    assert min(fades) < 0.5                   # the fade reached it
    assert scene.shown[-1]["text"] == "Isolating"
    assert scene.shown[-1]["alpha"] == 1.0
    card._hand_text(False)
    card._view = None
    assert label.updatesEnabled()
    card.close()


# -- on the real platform (the suite runs offscreen: no GPU API there) --------
_DRAW_CHECK = """
import sys, time
sys.path.insert(0, {root!r})
sys.path.insert(0, {tests!r})
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtQuick import QSGRendererInterface
from stream_denoiser.gui import themes
themes.set_current("vigil")
from stream_denoiser.gui.widgets.dial import DialButton
from stream_denoiser.gui.widgets.home_scene import HomeScene
from test_sky_gpu import _base
from PyQt6.QtCore import QRectF
warnings = []
view = HomeScene()
view.engine().warnings.connect(
    lambda errors: warnings.extend(e.toString() for e in errors))
if not view.ok:
    print("skip: the scene does not load"); sys.exit()
view.resize(912, 407)
view.show_frame(None, QRectF(1, 1, 910, 405), _base())
view.show()
def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
pump(1.0)
api = view.quickWindow().rendererInterface().graphicsApi()
if api in (QSGRendererInterface.GraphicsApi.Software,
           QSGRendererInterface.GraphicsApi.Unknown):
    print("skip: no GPU API for Qt Quick"); sys.exit()
bare = view.grabFramebuffer()
dial = DialButton()
view.place_dial(306.0, 80.0, 1.0)         # the dial's square at 306, 80
view.show_dial(dial.face_state())
font = QFont()
font.setPixelSize(36)
view.show_headline({{"text": "Ready to isolate", "font": font,
                     "color": QColor("#ffffff"), "x": 0.0, "y": 10.0,
                     "width": 912.0, "height": 50.0,
                     "horizontalAlignment": 4, "verticalAlignment": 128,
                     "wrapMode": 1, "alpha": 1.0, "spread": 0.0}})
pump(0.5)
drawn = view.grabFramebuffer()
s = drawn.width() / 912
def light(img, x, y):
    return img.pixelColor(round(x * s), round(y * s)).lightness()
# The glyph's stem (on the disc), the headline's band, the readout's "dB".
def row(img, y, x0, x1):
    return max(light(img, x, y) for x in range(x0, x1))
print("stem", light(bare, 456, 80 + 122), light(drawn, 456, 80 + 122))
print("title", row(bare, 35, 300, 610), row(drawn, 35, 300, 610))
print("readout", row(bare, 80 + 268, 400, 520),
      row(drawn, 80 + 268, 400, 520))
print("warnings", len(warnings), warnings[:3])
"""


@pytest.mark.skipif(sys.platform != "win32", reason="the GPU sky's home")
def test_the_scene_draws_the_dial_and_headline():
    env = dict(os.environ, QT_QPA_PLATFORM="windows")
    run = subprocess.run(
        [sys.executable, "-c", _DRAW_CHECK.format(
            root=str(ROOT), tests=str(ROOT / "tests"))],
        capture_output=True, text=True, timeout=60, env=env)
    out = run.stdout.strip().splitlines()
    assert run.returncode == 0 and out, run.stderr
    if out[-1].startswith("skip:"):
        pytest.skip(out[-1][6:])
    values = {line.split()[0]: line.split()[1:] for line in out}
    for name in ("stem", "title", "readout"):
        bare, drawn = map(int, values[name][:2])
        assert drawn > bare + 60, (name, bare, drawn)
    assert values["warnings"][0] == "0", out[-1]


_WINDOW_CHECK = """
import os, sys, tempfile, time
sys.path.insert(0, {root!r})
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication
app = QApplication([])
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                  tempfile.mkdtemp(prefix="poise-test-config-"))
seed = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                 "Poise", "VoiceIsolator")
seed.setValue("behavior/minimize_to_tray_asked", True)
seed.setValue("behavior/minimize_to_tray", True)
seed.setValue("appearance/reduce_motion", False)
seed.setValue("appearance/theme", "vigil")
seed.sync()
from stream_denoiser.gui.main_window import MainWindow
win = MainWindow()
win.resize(1180, 820)
win.show()
end = time.time() + 2.0
while time.time() < end:
    app.processEvents()
view = win._stage._view
print("view", type(view).__name__)
if type(view).__name__ != "HomeScene":
    sys.exit()
warnings = []
view.engine().warnings.connect(
    lambda errors: warnings.extend(e.toString() for e in errors))
dial = win.power_btn
print("sink", dial._face_sink is not None,
      win.home_title.updatesEnabled())
print("routed", type(win.childAt(dial.mapTo(win, dial.rect().center())))
      .__name__)
dial.set_active(True)
end = time.time() + 2.0
while time.time() < end:
    app.processEvents()
print("live", view._dial_sent.get("disc.glyphRgba") is not None,
      view._dial_sent.get("visible"))
win.update_status("Isolating audio")
end = time.time() + 2.0
while time.time() < end:
    app.processEvents()
print("title", view._text_sent.get("text"))
print("warnings", len(warnings), warnings[:3])
win.close()
"""


@pytest.mark.skipif(sys.platform != "win32", reason="the GPU sky's home")
def test_vigil_home_runs_as_one_scene():
    """The real window: Vigil's Home is a HomeScene, the dial and the
    headline hand it their looks, the pointer still lands on the dial,
    and nothing it is sent upsets the QML."""
    env = dict(os.environ, QT_QPA_PLATFORM="windows")
    env.pop("POISE_HOME_SCENE", None)
    run = subprocess.run(
        [sys.executable, "-c", _WINDOW_CHECK.format(root=str(ROOT))],
        capture_output=True, text=True, timeout=90, env=env)
    out = run.stdout.strip().splitlines()
    assert run.returncode == 0 and out, run.stderr
    values = {line.split()[0]: line.split(None, 1)[1] for line in out}
    if values["view"] != "HomeScene":
        pytest.skip(f"no scene here ({values['view']})")
    assert values["sink"] == "True False"
    assert values["routed"] == "DialButton"
    assert values["live"] == "True True"
    assert values["title"] != "Ready to isolate"
    assert values["warnings"].startswith("0"), values["warnings"]
