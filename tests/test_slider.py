"""Slider handle guards (needs Qt; skipped without it).

The handle is a rounded square in the theme's secondary colour that must
never change geometry on hover (growing it clipped against the widget
height), and its radius must stay within half the box at every UI scale
or Qt drops it and paints a hard square.
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


def _is_rounded_square(slider, img, rect):
    """Handle box is square with rounded (hollow) corners, filled centre."""
    if rect.width() != rect.height() or rect.width() <= 0:
        return False
    corner = img.pixelColor(rect.x() + 1, rect.y() + 1)
    center = img.pixelColor(rect.center().x(), rect.center().y())
    # Corner must not be handle fill (rounded, not a hard square)...
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
    # ...and the resting handle renders as a rounded square.
    slider = _make_slider()
    assert slider.minimumHeight() == 30
    rest = _handle_rect(slider)
    img, dpr = _grab(slider)
    assert _is_rounded_square(slider, img, _scaled(rest, dpr))
    slider.close()


@pytest.mark.parametrize(
    "scale", [0.8, 1.0, 1.0417, 1.25, 1.5, 1.75, 2.0])
def test_handle_radius_safe_at_all_scales(app, scale):
    """Rounding must never push border-radius past half the handle box.

    Qt drops (not clamps) an overflowing radius and renders a square: a
    radius that rounds up past half the box did exactly that on a live
    machine. Radius 4 on a 14px handle stays well under half across the
    whole supported range.

    Pure arithmetic on the rendered stylesheet (no pixels involved):
    Fusion allocates the handle box as content + 2*border wide and
    groove + 2*|margin| tall (anchored by the render test above at
    scale 1.0).
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
    border = re.search(r"border:\s*(\d+(?:\.\d+)?)px\s+solid",
                       handle.group(1))
    border_w = float(border.group(1)) if border else 0.0
    box_w, box_h = content + 2.0 * border_w, groove_h + 2.0 * margin
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
    # Handle fill glides from the secondary colour toward the text colour
    # (half way at full hover), so mid-fade is a quarter of the way.
    mid = _mix(QColor("#E8C468"), QColor("#f8fafc"), 0.25).name()
    assert mid in sheet, (mid, sheet)
    assert "#e8c468" not in sheet.lower() and "#f8fafc" not in sheet.lower()
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
