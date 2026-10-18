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
    sent = set(frame_uniforms(frame, box)) | set(_base())
    assert sent == _shader_uniforms() - {"size"}
    # A uniform named like an Item property (clip, opacity...) would
    # set that property instead of reaching the shader.
    meta = QQuickItem().metaObject()
    item = {meta.property(i).name() for i in range(meta.propertyCount())}
    assert not (_shader_uniforms() & item)


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
