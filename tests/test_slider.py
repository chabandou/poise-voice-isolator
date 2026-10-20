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
    slider.setStyleSheet(get_stylesheet(scale=scale, theme="halcyon"))
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
    css = get_stylesheet(scale=1.0, theme="halcyon")
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
    css = get_stylesheet(scale=scale, theme="halcyon")
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
    themes.set_current("halcyon")
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


def _mouse(slider, kind, x, y=None, button=None, modifiers=None):
    from PyQt6.QtCore import QEvent, QPointF, Qt
    from PyQt6.QtGui import QEnterEvent, QMouseEvent
    pos = QPointF(x, slider.height() / 2 if y is None else y)
    if kind == "enter":
        slider.enterEvent(QEnterEvent(pos, pos, slider.mapToGlobal(pos)))
        return
    if kind == "leave":
        slider.leaveEvent(QEvent(QEvent.Type.Leave))
        return
    left, none = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
    types = {"press": QEvent.Type.MouseButtonPress,
             "move": QEvent.Type.MouseMove,
             "release": QEvent.Type.MouseButtonRelease}
    held = left if (kind in ("press", "move") and button) else none
    event = QMouseEvent(types[kind], pos, slider.mapToGlobal(pos),
                        none if kind == "move" else left,
                        held, modifiers or Qt.KeyboardModifier.NoModifier)
    {"press": slider.mousePressEvent, "move": slider.mouseMoveEvent,
     "release": slider.mouseReleaseEvent}[kind](event)


def _wheel(slider, notches=1, ctrl=False):
    from PyQt6.QtCore import QPoint, QPointF, Qt
    from PyQt6.QtGui import QWheelEvent
    from PyQt6.QtWidgets import QApplication
    centre = QPointF(slider.width() / 2, slider.height() / 2)
    mods = (Qt.KeyboardModifier.ControlModifier if ctrl
            else Qt.KeyboardModifier.NoModifier)
    ev = QWheelEvent(centre, slider.mapToGlobal(centre), QPoint(0, 0),
                     QPoint(0, 120 * notches), Qt.MouseButton.NoButton, mods,
                     Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(slider, ev)
    return ev.isAccepted()


def test_wheel_only_after_the_pointer_moves_over_it(app):
    """A page scroll sliding the slider under a still pointer keeps
    scrolling the page; once the pointer moves over it, the wheel steps
    the value (a page with Ctrl)."""
    slider = _make_hover_slider()
    _pump(app, 0.1)
    _mouse(slider, "enter", 200)
    assert not _wheel(slider) and slider.value() == -40   # not armed yet
    _mouse(slider, "move", 205)
    assert _wheel(slider) and slider.value() == -39       # up = higher
    assert _wheel(slider, -2) and slider.value() == -41
    assert _wheel(slider, ctrl=True) and slider.value() == -31
    _mouse(slider, "leave", 0)
    assert not _wheel(slider) and slider.value() == -31   # disarmed
    _mouse(slider, "enter", 200)
    _mouse(slider, "move", 210)
    slider.setEnabled(False)   # (Qt doesn't run a disabled widget's handlers)
    _wheel(slider)
    assert slider.value() == -31                          # locked
    slider.close()


def test_handle_glides_to_a_new_value(app):
    """The handle eases to each new value (a spring for jumps) instead of
    jumping, and always comes to rest exactly on it."""
    import time
    slider = _make_hover_slider()
    _pump(app, 0.1)
    slider.setValue(-20)
    assert slider.value() == -20
    assert slider.shown_value == pytest.approx(-40)       # not jumped
    seen = []
    end = time.time() + 0.6
    while time.time() < end:
        app.processEvents()
        seen.append(slider.shown_value)
        time.sleep(0.005)
    assert any(-39 < v < -21 for v in seen)               # in between
    assert max(seen) > -20                                # springs past
    assert slider.shown_value == pytest.approx(-20)
    slider.close()


def test_reduced_motion_puts_the_handle_straight_on_the_value(
        app, monkeypatch):
    monkeypatch.setenv("POISE_NO_ANIM", "1")
    slider = _make_hover_slider()
    _pump(app, 0.1)
    slider.setValue(-70)
    assert slider.shown_value == pytest.approx(-70)
    slider.close()


def test_drag_follows_and_settles_on_a_whole_value(app):
    slider = _make_hover_slider()
    _pump(app, 0.1)
    x0 = slider._x_for(slider.value())
    _mouse(slider, "enter", x0)
    _mouse(slider, "press", x0, button=True)
    assert slider.isSliderDown() and slider._press.target == 1.0
    _mouse(slider, "move", x0 + 80, button=True)
    moved = slider.value()
    assert moved > -40
    _pump(app, 0.2)
    assert slider.shown_value == pytest.approx(
        slider._value_at(x0 + 80), abs=0.6)               # follows, smooth
    _mouse(slider, "release", x0 + 80)
    assert not slider.isSliderDown() and slider._press.target == 0.0
    _pump(app, 0.4)
    assert slider.shown_value == pytest.approx(moved)     # settled
    slider.close()


def test_track_click_springs_there(app):
    slider = _make_hover_slider()
    _pump(app, 0.1)
    target_x = slider._x_for(-15)
    _mouse(slider, "press", target_x, button=True)
    _mouse(slider, "release", target_x)
    assert slider.value() == -15
    assert slider.shown_value < -16                       # on its way
    _pump(app, 0.6)
    assert slider.shown_value == pytest.approx(-15)
    slider.close()


def _handle_colour(slider):
    x = int(round(slider._x_for(slider.shown_value)))
    return slider.grab().toImage().pixelColor(x, slider.height() // 2)


def test_hover_lifts_the_handle_toward_the_text_colour(app):
    from PyQt6.QtGui import QColor
    from stream_denoiser.gui.widgets.slider import _mix
    slider = _make_hover_slider()
    _pump(app, 0.1)
    assert _handle_colour(slider).name() == "#e8c468"     # halcyon secondary
    slider._hover.snap(1.0)
    lifted = _mix(QColor("#E8C468"), QColor("#f8fafc"), 0.5)
    got = _handle_colour(slider)
    assert abs(got.red() - lifted.red()) <= 2
    assert abs(got.blue() - lifted.blue()) <= 2
    # Hovering the handle eases in; leaving eases out.
    slider._hover.snap(0.0)
    x = slider._x_for(slider.value())
    _mouse(slider, "enter", x)
    _mouse(slider, "move", x + 1)
    assert slider._hover.target == 1.0
    _mouse(slider, "leave", 0)
    assert slider._hover.target == 0.0
    slider.close()


def test_disabled_slider_is_grey_and_inert(app):
    slider = _make_hover_slider()
    _pump(app, 0.1)
    slider.setEnabled(False)
    x = slider._x_for(slider.value())
    _mouse(slider, "enter", x)
    _mouse(slider, "move", x + 1)
    _mouse(slider, "press", slider._x_for(-15), button=True)
    assert slider.value() == -40 and not slider.isSliderDown()
    assert slider._hover.target == 0.0
    assert _handle_colour(slider).name() == "#3f3f46"
    slider.close()


def test_rolling_number_rolls_and_bumps_like_the_dial(app):
    from PyQt6.QtCore import QVariantAnimation
    from stream_denoiser.gui.widgets.rolling_number import RollingNumber
    number = RollingNumber(-40, " dB")
    number.resize(80, 30)
    number.show()
    _pump(app, 0.1)
    assert number.text() == "-40 dB"
    number.set_value(-33)
    assert number.text() == "-33 dB"
    tens, ones = number._columns
    assert tens.running and ones.running                  # digits roll
    assert tens.target == 3 and ones.target == 3
    _pump(app, 0.6)
    assert tens.value == pytest.approx(3) and ones.value == pytest.approx(3)
    assert number._bump.state() != QVariantAnimation.State.Running
    number.set_value(-30)                                 # a ten: bump
    assert number._bump.state() == QVariantAnimation.State.Running
    number.grab()                                         # paints mid-roll
    number.close()


def test_rolling_number_snaps_when_hidden_or_reduced(app, monkeypatch):
    from stream_denoiser.gui.widgets.rolling_number import RollingNumber
    number = RollingNumber(-40, " dB")
    number.set_value(-52)                                 # not shown yet
    assert [c.value for c in number._columns] == [5, 2]
    number.show()
    _pump(app, 0.1)
    monkeypatch.setenv("POISE_NO_ANIM", "1")
    number.set_value(-61)
    assert [c.value for c in number._columns] == [6, 1]
    number.close()


def test_long_digit_rolls_settle_from_just_past(app):
    """OutBack overshoots in proportion to the travel: rolling 0 -> 7
    sprang a third of a digit past and half-hid the 7. The spring is
    softened for long rolls so every digit settles from just past."""
    import time
    from stream_denoiser.gui.widgets.rolling_number import (
        ROLL_SETTLE, RollingNumber,
    )
    number = RollingNumber(-40, " dB")
    number.resize(80, 30)
    number.show()
    _pump(app, 0.1)
    number.set_value(-37)                       # ones roll 0 -> 7
    ones = number._columns[1]
    peak = 0.0
    end = time.time() + 0.6
    while time.time() < end:
        app.processEvents()
        peak = max(peak, ones.value)
        time.sleep(0.005)
    assert 7.0 < peak <= 7.0 + 2 * ROLL_SETTLE  # a small settle, no more
    assert ones.value == pytest.approx(7.0)
    number.close()
