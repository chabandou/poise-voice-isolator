"""Slider handle guards (needs Qt; skipped without it).

The AAD/attenuation handle must be a true circle that never changes
geometry on hover: growing it clipped it against the widget height and
the wrong border-radius made it a rounded square. Regression test.
"""
import os

import pytest

pytest.importorskip("PyQt6.QtWidgets")


@pytest.fixture(scope="module")
def app():
    # Forced offscreen (not setdefault): on native platforms grabs come
    # back scaled and the test would be about Qt's HiDPI path instead
    # of our stylesheet. Offscreen keeps everything in logical pixels.
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_slider(scale=1.0):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QSlider, QStyleFactory
    from stream_denoiser.gui.styles import get_stylesheet
    slider = QSlider(Qt.Orientation.Horizontal)
    # Pin Fusion: host style overrides (e.g. Kvantum) measure/paint
    # subcontrols differently and would make this test about them.
    fusion = QStyleFactory.create("Fusion")
    if fusion is not None:
        slider.setStyle(fusion)
    slider.setStyleSheet(get_stylesheet(scale=scale, theme="abyss"))
    slider.setRange(-80, -10)
    slider.setValue(-40)
    slider.resize(400, 100)
    slider.show()
    return slider


def _handle_rect(slider):
    from PyQt6.QtWidgets import QStyle, QStyleOptionSlider
    opt = QStyleOptionSlider()
    slider.initStyleOption(opt)
    return slider.style().subControlRect(
        QStyle.ComplexControl.CC_Slider, opt,
        QStyle.SubControl.SC_SliderHandle, slider)


def _grab(slider):
    """Grab + the device pixel ratio (Wayland/HiDPI render scaled)."""
    img = slider.grab().toImage()
    return img, img.width() / max(1, slider.width())


def _scaled(rect, dpr):
    from PyQt6.QtCore import QRect
    return QRect(round(rect.x() * dpr), round(rect.y() * dpr),
                 round(rect.width() * dpr), round(rect.height() * dpr))
    from PyQt6.QtCore import QRect
    return QRect(round(rect.x() * dpr), round(rect.y() * dpr),
                 round(rect.width() * dpr), round(rect.height() * dpr))


def _is_circle(slider, img, rect):
    """Handle box is square with hollow corners and a filled center."""
    if rect.width() != rect.height() or rect.width() <= 0:
        return False
    corner = img.pixelColor(rect.x() + 1, rect.y() + 1)
    center = img.pixelColor(rect.center().x(), rect.center().y())
    # Corner must not be handle fill (rounded, not square)...
    if corner == center:
        return False
    # ...and the center must be opaque fill (not background showing).
    return center.alpha() == 255


def test_handle_hover_changes_no_geometry(app):
    """Hover restyles color only: no geometry props in the hover rule."""
    import re
    from stream_denoiser.gui.styles import get_stylesheet
    css = get_stylesheet(scale=1.0, theme="abyss")
    hover = re.search(
        r"QSlider::handle:horizontal:hover\s*\{([^}]*)\}", css)
    assert hover, "hover rule missing"
    for prop in ("width", "height", "margin", "min-", "max-", "padding",
                 "border-width", "top", "left"):
        assert prop not in hover.group(1), prop
    # ...and the resting handle renders as a true circle.
    slider = _make_slider()
    assert slider.minimumHeight() == 30
    rest = _handle_rect(slider)
    img, dpr = _grab(slider)
    assert _is_circle(slider, img, _scaled(rest, dpr))
    slider.close()


@pytest.mark.parametrize(
    "scale", [0.8, 1.0, 1.0417, 1.25, 1.5, 1.75, 2.0])
def test_handle_radius_safe_at_all_scales(app, scale):
    """Rounding must never push border-radius past half the handle box.

    Qt drops (not clamps) an overflowing radius and renders a square:
    12px * 1.0417 rounded to 13 > 24/2 did exactly that on the live
    machine. Radius 11 stays at or under half the box across the whole
    supported range.

    Pure arithmetic on the rendered stylesheet (no pixels involved):
    Fusion allocates the handle box as content + 4px wide and
    groove + 2*|margin| tall (observed on 6.8/6.11, anchored by the
    render test above at scale 1.0).
    """
    import re
    from stream_denoiser.gui.styles import get_stylesheet
    css = get_stylesheet(scale=scale, theme="abyss")
    handle = re.search(
        r"QSlider::handle:horizontal\s*\{([^}]*)\}", css)
    groove = re.search(
        r"QSlider::groove:horizontal\s*\{([^}]*)\}", css)
    assert handle and groove, scale

    def num(block, name):
        m = re.search(rf"{name}:\s*(-?\d+(?:\.\d+)?)px", block)
        assert m, (scale, name)
        return float(m.group(1))

    content = num(handle.group(1), "width")
    margin = abs(num(handle.group(1), "margin"))
    radius = num(handle.group(1), "border-radius")
    groove_h = num(groove.group(1), "height")
    box_w, box_h = content + 4.0, groove_h + 2.0 * margin
    assert 2.0 * radius <= min(box_w, box_h), \
        (scale, radius, box_w, box_h)


def _make_hover_slider():
    from PyQt6.QtCore import Qt
    from stream_denoiser.gui import themes
    from stream_denoiser.gui.widgets.slider import HoverSlider
    themes.set_current("abyss")
    slider = HoverSlider(Qt.Orientation.Horizontal)
    slider.setRange(-80, -10)
    slider.setValue(-40)
    slider.resize(400, 100)
    slider.show()
    return slider


def _pump(app, secs=0.5):
    import time
    end = time.time() + secs
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def test_hover_crossfade_midpoint_is_blended(app):
    """Mid-anim the sheet holds a true midpoint, not an endpoint snap."""
    from stream_denoiser.gui.widgets.slider import _mix
    from PyQt6.QtGui import QColor
    slider = _make_hover_slider()
    slider._hoverT = 0.5
    slider._apply_hover()
    sheet = slider.styleSheet()
    assert sheet, "hover sheet must be installed mid-fade"
    mid = _mix(QColor("#f8fafc"), QColor("#a5f3fc"), 0.5).name()
    assert mid in sheet, (mid, sheet)
    assert "#f8fafc" not in sheet and "#a5f3fc" not in sheet
    slider.close()


def test_hover_settles_and_clears(app):
    """Hover on installs the sheet; hover off removes it entirely."""
    slider = _make_hover_slider()
    assert slider.styleSheet() == ""
    slider._target_hover(True)
    _pump(app)
    assert slider.styleSheet() != ""
    slider._target_hover(False)
    _pump(app)
    assert slider.styleSheet() == ""
    slider.close()


def test_hover_respects_disabled_and_reduced_motion(app, monkeypatch):
    """Disabled sliders and reduced motion never install a sheet."""
    slider = _make_hover_slider()
    slider.setEnabled(False)
    slider._target_hover(True)
    _pump(app, 0.3)
    assert slider.styleSheet() == ""
    slider.setEnabled(True)
    monkeypatch.setenv("POISE_NO_ANIM", "1")
    slider._target_hover(True)
    _pump(app, 0.3)
    assert slider.styleSheet() == ""
    slider.close()
