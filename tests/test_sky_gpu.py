"""The night sky on the GPU (widgets/sky_gpu.py, assets/sky/)."""
import importlib.util
import os
import re
import subprocess
import sys
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


def _bake_tool():
    spec = importlib.util.spec_from_file_location(
        "bake_sky_shader", ROOT / "tools" / "bake_sky_shader.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _shader_uniforms():
    frag = (SKY / "sky.frag").read_text(encoding="utf-8")
    return {name for _, name in _bake_tool().uniforms(frag)}


def _live_frame(app, cycle):
    from PyQt6.QtCore import QPointF, QRectF
    from PyQt6.QtGui import QColor
    from stream_denoiser.gui.widgets.sky import NightSky
    box = QRectF(1, 1, 910, 405)
    return box, NightSky().frame(box, QPointF(455, 210), 1.0, 1.0, 5000.0, {
        "live": 1.0, "gather": 0.0, "error": 0.0, "reveal": 1.0,
        "gather_ms": 0.0, "cycle": cycle, "stopped": None,
        "gain": lambda index: 1.0, "moving": True,
        "secondary": QColor("#E6CD8A"), "accent": QColor("#b9a6ff"),
        "accent_light": QColor("#e4dcff")})


def _meteor_frame(app):
    """An idle sky as a shooting star is at its brightest (the first span
    with room for one)."""
    from PyQt6.QtCore import QPointF, QRectF
    from PyQt6.QtGui import QColor
    from stream_denoiser.gui.widgets import sky
    box = QRectF(1, 1, 910, 405)
    look = {"live": 0.0, "gather": 0.0, "error": 0.0, "reveal": 1.0,
            "gather_ms": 0.0, "cycle": None, "stopped": None,
            "gain": lambda index: 1.0, "moving": True,
            "secondary": QColor("#E6CD8A"), "accent": QColor("#b9a6ff"),
            "accent_light": QColor("#e4dcff")}
    night = sky.NightSky()
    for index in range(30):
        start, _ = sky.meteor_flight(index * sky.METEOR_EVERY_MS + 1.0)
        frame = night.frame(box, QPointF(455, 230), 0.8, 1.0,
                            start + 0.56 * sky.METEOR_MS, look)
        if frame["meteor"] is not None:
            return box, frame
    raise AssertionError("no shooting star with room to fly")


def _base():
    from PyQt6.QtGui import QColor
    from stream_denoiser.gui import themes
    from stream_denoiser.gui.widgets.sky_gpu import card_base
    vigil = themes.get_theme("vigil")
    return card_base((912, 407), 16, 1, QColor(190, 170, 255, 46),
                     vigil["card_fill"], vigil["window_fill"], (240, 26),
                     (1180, 760))


def test_the_qml_has_a_property_per_uniform():
    frag = (SKY / "sky.frag").read_text(encoding="utf-8")
    assert (SKY / "sky.qml").read_text(encoding="utf-8") == \
        _bake_tool().qml(frag), "run tools/bake_sky_shader.py"
    assert (SKY / "sky.frag.qsb").stat().st_size > 0


def test_every_uniform_is_sent_and_none_clashes_with_qml(app):
    from PyQt6.QtQuick import QQuickItem
    from stream_denoiser.gui.widgets.sky_gpu import frame_uniforms
    box, frame = _live_frame(app, 300.0)       # a pulse in flight
    # Each frame and the card's base, plus the dial's ring (show_ring,
    # show_breath, place_ring).
    sent = (set(frame_uniforms(frame, box)) | set(_base())
            | {"tickRing", "tickBreath", "tickAt"})
    assert sent == _shader_uniforms() - {"size"}
    # A uniform named like an Item property (clip, opacity...) would
    # set that property instead of reaching the shader.
    meta = QQuickItem().metaObject()
    item = {meta.property(i).name() for i in range(meta.propertyCount())}
    frag = (SKY / "sky.frag").read_text(encoding="utf-8")
    assert not ((_shader_uniforms() | set(_bake_tool().samplers(frag)))
                & item)


def _breathing_dial(phase: str):
    """A Vigil dial, its ring fully drawn, long into `phase` (live: the
    lit ticks glow; idle: they breathe), and its theme to restore."""
    from stream_denoiser.gui import themes
    from stream_denoiser.gui.widgets.dial import DialButton
    before = themes.current_id()
    themes.set_current("vigil")
    dial = DialButton()
    dial._sweep_at = None                      # the ring fully drawn
    dial._phase = phase
    dial._phase_at -= 20.0                     # long after the bloom
    return dial, before


def _ring_strokes(app, phase="live"):
    """A breathing dial's strokes (glows, ticks and the needle)."""
    from stream_denoiser.gui import themes
    dial, before = _breathing_dial(phase)
    try:
        over, strokes, _ = dial.ring_frame()
        dial.deleteLater()
    finally:
        themes.set_current(before)
    return over, strokes


def test_the_ring_packs_into_its_texture(app):
    from stream_denoiser.gui.widgets.dial import TICKS
    from stream_denoiser.gui.widgets.sky_gpu import (
        RING_COLUMNS, RING_ROWS, ring_image, ring_uniform)
    over, strokes = _ring_strokes(app)
    idle = _ring_strokes(app, "idle")[1]
    assert any(stroke[6] for stroke in idle)   # the lit ticks breathe
    assert not any(stroke[6] for stroke in strokes)
    # Two breathing ticks (and their glows) among the live ones.
    strokes = (tuple(s for s in idle if s[5] < 4)
               + tuple(s for s in strokes if s[5] >= 4))
    slots = [stroke[5] for stroke in strokes]
    assert len(set(slots)) == len(slots)       # one stroke per slot
    assert 2 * TICKS + 1 in slots              # the needle is there
    image = ring_image(strokes)
    assert (image.width(), image.height()) == (RING_COLUMNS, RING_ROWS)

    def texel(column, row):
        c = image.pixelColor(column, row)
        return c.red(), c.green(), c.blue()

    for angle, r0, r1, rgba, width, slot, breathes in strokes:
        column, glow = slot // 2, slot % 2 == 0
        assert texel(column, 1 if glow else 0) == (
            (rgba >> 16) & 0xFF, (rgba >> 8) & 0xFF, rgba & 0xFF)
        assert texel(column, 2)[1 if glow else 0] == (rgba >> 24) & 0xFF
        assert bool(texel(column, 2)[2] & (64 if glow else 128)) == breathes
        hi, lo, _ = texel(column, 5 if glow else 3)
        assert abs((hi * 256 + lo) / 256 - r0) <= 1 / 512
        hi, lo, _ = texel(column, 6 if glow else 4)
        assert abs((hi * 256 + lo) / 256 - r1) <= 1 / 512
    needle = [s for s in strokes if s[5] == 2 * TICKS][0]
    u = ring_uniform(over, strokes)
    assert (u.y(), u.z(), u.w()) == (pytest.approx(needle[0]),
                                     needle[4], 1.0)


def test_the_dial_hands_its_ring_to_a_sink(app):
    from stream_denoiser.gui import themes
    from stream_denoiser.gui.widgets.dial import DialButton
    before = themes.current_id()
    themes.set_current("vigil")
    try:
        dial = DialButton()
        got = []
        dial.set_ring_sink(lambda over, strokes, breath:
                           got.append(strokes))
        drawn = []
        draw = dial._draw_ring
        dial._draw_ring = lambda *a: drawn.append(1) or draw(*a)
        dial.grab()
        assert got and not drawn               # handed over, not painted
        dial.set_ring_sink(None)
        dial._ring_key = None
        dial.grab()
        assert drawn                           # painted here again
        dial.deleteLater()
    finally:
        themes.set_current(before)


def test_the_idle_breath_scales_the_strokes_it_leaves_out(app):
    """Lifted out (for the shader's tickBreath), the idle breath leaves
    the strokes still, and scaling those it marks draws what the dial
    paints itself."""
    from PyQt6.QtGui import QColor
    from stream_denoiser.gui import themes
    from stream_denoiser.gui.themes import current
    dial, before = _breathing_dial("idle")
    try:
        col, t = dial._colours(current()), dial._ms()
        dial._idle_breath = lambda: 1.0
        still = dial._ring_strokes(col, t, True)
        dial._idle_breath = lambda: 0.84
        assert dial._ring_strokes(col, t, True) == still
        painted = dial._ring_strokes(col, t)
        dial.deleteLater()
    finally:
        themes.set_current(before)
    assert [s[5] for s in painted] == [s[5] for s in still]
    for lifted, own in zip(still, painted):
        a, b = QColor.fromRgba(lifted[3]), QColor.fromRgba(own[3])
        assert (a.red(), a.green(), a.blue()) == (b.red(), b.green(), b.blue())
        scale = 0.84 if lifted[6] else 1.0
        assert abs(a.alphaF() * scale - b.alphaF()) <= 1.5 / 255
        assert lifted[:3] == own[:3] and lifted[4:6] == own[4:6]
        assert not own[6]


def test_a_pulse_reaches_the_shader(app):
    from stream_denoiser.gui.widgets.sky_gpu import frame_uniforms
    box, frame = _live_frame(app, 300.0)
    u = frame_uniforms(frame, box)
    assert u["band"].x() > 0                   # the band is out
    assert u["halo0"].w() == 1.0               # a halo left the disc
    assert u["flare"].w() > 0                  # the beads flare
    assert sum(u[f"s{i}"].w() > 0 for i in range(26)) > 10
    off = frame_uniforms(None, box)            # not revealed yet
    assert all(v.isNull() for v in off.values())


def test_a_shooting_star_reaches_the_shader(app):
    from stream_denoiser.gui.widgets.sky_gpu import frame_uniforms
    from stream_denoiser.gui.widgets import sky
    box, frame = _meteor_frame(app)
    m = frame["meteor"]
    u = frame_uniforms(frame, box)

    def values(v):
        return (v.x(), v.y(), v.z(), v.w())

    a, b, c = m["arc"]
    assert values(u["meteor"]) == pytest.approx(
        (a.x(), a.y(), b.x(), b.y()), abs=1e-3)
    assert values(u["meteorEnd"]) == pytest.approx(
        (c.x(), c.y(), m["s0"], m["s1"]), abs=1e-3)
    assert u["meteorRgba"].w() == pytest.approx(m["colour"].alphaF(),
                                                abs=1e-3)
    assert values(u["meteorGeo"]) == pytest.approx(
        (m["width"], m["glow"], m["head_r"], m["head_glow"]), abs=1e-3)
    assert values(u["meteorHead"]) == pytest.approx(
        (m["head"], m["white"], 0.0, 1.0), abs=1e-3)
    assert values(u["meteorStyle"]) == pytest.approx(
        (sky.METEOR_TAPER, sky.METEOR_WHITE, sky.METEOR_GLOW_ALPHA,
         sky.METEOR_HEAD_GLOW_ALPHA), abs=1e-6)
    frame["meteor"] = None                     # none in flight: off
    assert frame_uniforms(frame, box)["meteorHead"].isNull()


def test_qss_gradients_are_read():
    from stream_denoiser.gui import themes
    from stream_denoiser.gui.widgets.sky_gpu import qss_radial, qss_stops
    vigil = themes.get_theme("vigil")
    stops = qss_stops(vigil["window_fill"])
    assert [at for at, _ in stops] == [0.0, 0.45, 0.75, 1.0]
    assert stops[0][1].name() == "#181440"
    assert qss_radial(vigil["window_fill"]) == (0.62, 0.28, 0.95)
    assert qss_stops("#0a0920")[0][1].name() == "#0a0920"


_DRAW_CHECK = """
import sys, time
sys.path.insert(0, {root!r})
sys.path.insert(0, {tests!r})
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from PyQt6.QtQuick import QSGRendererInterface
from stream_denoiser.gui.widgets.sky_gpu import SkyView
from test_sky_gpu import _base, _live_frame
box, frame = _live_frame(app, 7600.0)          # charged, between pulses
view = SkyView()
if not view.ok:
    print("skip: the shader does not load"); sys.exit()
view.resize(912, 407)
view.show_frame(None, box, _base())
view.show()
end = time.time() + 1.0
while time.time() < end:
    app.processEvents()
api = view.quickWindow().rendererInterface().graphicsApi()
if api in (QSGRendererInterface.GraphicsApi.Software,
           QSGRendererInterface.GraphicsApi.Unknown):
    print("skip: no GPU API for Qt Quick"); sys.exit()
bare = view.grabFramebuffer()
view.show_frame(frame, box, _base())
lit = view.grabFramebuffer()
# On the ring (168 above the dial's centre) the sky adds light.
x, y = round(455 * lit.width() / 912), round(42 * lit.height() / 407)
print("lightness", bare.pixelColor(x, y).lightness(),
      lit.pixelColor(x, y).lightness())
"""


@pytest.mark.skipif(sys.platform != "win32", reason="the GPU sky's home")
def test_the_view_draws_the_sky():
    """On the real platform (the suite runs offscreen, where Qt Quick
    has no GPU API): the shader draws the sky."""
    env = dict(os.environ, QT_QPA_PLATFORM="windows")
    run = subprocess.run(
        [sys.executable, "-c", _DRAW_CHECK.format(
            root=str(ROOT), tests=str(ROOT / "tests"))],
        capture_output=True, text=True, timeout=60, env=env)
    out = run.stdout.strip().splitlines()
    assert run.returncode == 0 and out, run.stderr
    if out[-1].startswith("skip:"):
        pytest.skip(out[-1][6:])
    _, bare, lit = out[-1].split()
    assert int(lit) > int(bare)


_METEOR_CHECK = """
import sys, time
sys.path.insert(0, {root!r})
sys.path.insert(0, {tests!r})
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from PyQt6.QtQuick import QSGRendererInterface
from stream_denoiser.gui.widgets.sky_gpu import SkyView
from test_sky_gpu import _base, _meteor_frame
box, frame = _meteor_frame(app)
head = frame["meteor"]["front"]
view = SkyView()
if not view.ok:
    print("skip: the shader does not load"); sys.exit()
view.resize(912, 407)
view.show_frame(frame, box, _base())
view.show()
end = time.time() + 1.0
while time.time() < end:
    app.processEvents()
api = view.quickWindow().rendererInterface().graphicsApi()
if api in (QSGRendererInterface.GraphicsApi.Software,
           QSGRendererInterface.GraphicsApi.Unknown):
    print("skip: no GPU API for Qt Quick"); sys.exit()
lit = view.grabFramebuffer()
frame["meteor"] = None
view.show_frame(frame, box, _base())
bare = view.grabFramebuffer()
x = round(head.x() * lit.width() / 912)
y = round(head.y() * lit.height() / 407)
print("lightness", bare.pixelColor(x, y).lightness(),
      lit.pixelColor(x, y).lightness())
"""


@pytest.mark.skipif(sys.platform != "win32", reason="the GPU sky's home")
def test_the_view_draws_the_shooting_star():
    env = dict(os.environ, QT_QPA_PLATFORM="windows")
    run = subprocess.run(
        [sys.executable, "-c", _METEOR_CHECK.format(
            root=str(ROOT), tests=str(ROOT / "tests"))],
        capture_output=True, text=True, timeout=60, env=env)
    out = run.stdout.strip().splitlines()
    assert run.returncode == 0 and out, run.stderr
    if out[-1].startswith("skip:"):
        pytest.skip(out[-1][6:])
    _, bare, lit = out[-1].split()
    assert int(lit) > int(bare) + 40


def test_raster_sky_when_asked(app, monkeypatch):
    from PyQt6.QtWidgets import QVBoxLayout, QWidget
    from stream_denoiser.gui import themes
    from stream_denoiser.gui.widgets.pattern_card import PatternCard
    monkeypatch.setenv("POISE_SKY_RASTER", "1")
    before = themes.current_id()
    themes.set_current("vigil")
    try:
        card = PatternCard()
        card.resize(900, 520)
        origin = QWidget()
        origin.setFixedSize(300, 300)
        QVBoxLayout(card).addWidget(origin)
        card.set_ping_origin(origin)
        card.show()
        app.processEvents()
        assert card._view is None and card._view_failed
        card.grab()                            # painted with QPainter
        card.close()
    finally:
        themes.set_current(before)


def test_bake_tool_reads_the_uniform_block():
    names = [n for _, n in _bake_tool().uniforms(
        "layout(std140, binding = 0) uniform buf {\n"
        "    mat4 qt_Matrix;  // the item\n    float qt_Opacity;\n"
        "    vec2 size;\n    vec4 a; vec4 b;\n};")]
    assert names == ["size", "a", "b"]
    frag = (SKY / "sky.frag").read_text(encoding="utf-8")
    assert re.search(r"property size size: Qt.size\(width, height\)",
                     _bake_tool().qml(frag))
