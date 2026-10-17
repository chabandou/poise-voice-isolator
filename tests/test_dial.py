"""Dial button: reduction-ring maths and interaction (needs Qt)."""
import math
import os
import time

import pytest

pytest.importorskip("PyQt6.QtWidgets")


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


# -- pure geometry (no widget) ------------------------------------------------
def test_strength_mapping_endpoints_and_roundtrip(app):
    from stream_denoiser.gui.widgets import dial
    assert dial.strength_fraction(dial.ATTEN_GENTLE) == 0.0
    assert dial.strength_fraction(dial.ATTEN_STRONG) == 1.0
    assert dial.strength_fraction(-40) == pytest.approx(3 / 4)
    assert dial.strength_fraction(-5) == 0.0      # clamped
    assert dial.strength_fraction(-200) == 1.0    # clamped
    for db in range(dial.ATTEN_STRONG, dial.ATTEN_GENTLE + 1):
        assert dial.db_from_fraction(dial.strength_fraction(db)) == db


def test_angle_to_fraction_covers_the_open_ring(app):
    from stream_denoiser.gui.widgets import dial
    assert dial.angle_to_fraction(135.0) == pytest.approx(0.0)
    assert dial.angle_to_fraction(270.0) == pytest.approx(0.5)   # 12 o'clock
    assert dial.angle_to_fraction(405.0 % 360) == pytest.approx(1.0)
    # Bottom gap snaps to the nearer end, and pins when crossing it.
    assert dial.angle_to_fraction(60.0) == pytest.approx(1.0)
    assert dial.angle_to_fraction(120.0) == pytest.approx(0.0)
    assert dial.angle_to_fraction(90.0, previous=0.9) == pytest.approx(1.0)
    assert dial.angle_to_fraction(90.0, previous=0.1) == pytest.approx(0.0)


def test_tick_geometry_spans_the_arc(app):
    from stream_denoiser.gui.widgets import dial
    first, _, _ = dial.tick_geometry(0)
    last, _, _ = dial.tick_geometry(dial.TICKS - 1)
    assert first == dial.ARC_START
    assert last == dial.ARC_START + dial.ARC_SPAN
    majors = [i for i in range(dial.TICKS)
              if dial.tick_geometry(i)[1] == dial.R_IN_MAJOR]
    assert majors[:3] == [0, 9, 18]


# -- widget behaviour -----------------------------------------------------------
def _ring_pos(btn, deg, radius=125.0):
    from PyQt6.QtCore import QPoint
    k = btn.width() / 300.0
    rad = math.radians(deg)
    return QPoint(int(btn.width() / 2 + radius * k * math.cos(rad)),
                  int(btn.height() / 2 + radius * k * math.sin(rad)))


def _make(app):
    from stream_denoiser.gui.widgets.dial import DialButton
    btn = DialButton()
    btn.show()
    _pump(app)
    return btn


def test_set_strength_is_silent_and_user_changes_emit(app):
    btn = _make(app)
    seen = []
    btn.strength_changed.connect(seen.append)
    btn.set_strength_db(-45)
    assert btn.strength_db() == -45 and seen == []
    btn.set_strength_db(-500)                    # clamps
    assert btn.strength_db() == -50
    btn._user_set_strength(-30)
    assert seen == [-30]
    btn._user_set_strength(-30)                  # no change, no emit
    assert seen == [-30]
    btn.close()


def test_dragging_the_ring_sets_strength(app):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    btn = _make(app)
    seen = []
    btn.strength_changed.connect(seen.append)
    top = _ring_pos(btn, 270)                    # 12 o'clock -> halfway
    QTest.mousePress(btn, Qt.MouseButton.LeftButton, pos=top)
    assert seen and seen[-1] == -30
    right = _ring_pos(btn, 360)                  # 3 o'clock
    QTest.mouseMove(btn, right)
    QTest.mouseRelease(btn, Qt.MouseButton.LeftButton, pos=right)
    assert btn.strength_db() == -43              # 3 o clock: 225/270 of the arc
    btn.close()


def test_press_lands_anywhere_from_a_full_ring(app):
    """Full ring (the default): pressing the ring's first half must set
    the value, not be mistaken for a drag across the bottom gap."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from stream_denoiser.gui.widgets import dial
    btn = _make(app)
    btn.set_strength_db(dial.ATTEN_STRONG)
    pos = _ring_pos(btn, 180)                    # 9 o'clock: 45/270 of the arc
    QTest.mousePress(btn, Qt.MouseButton.LeftButton, pos=pos)
    QTest.mouseRelease(btn, Qt.MouseButton.LeftButton, pos=pos)
    assert btn.strength_db() == dial.db_from_fraction(45 / 270)
    btn.close()


def test_ring_press_does_not_toggle_but_disc_click_does(app):
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest
    btn = _make(app)
    toggles = []
    btn.toggled_state.connect(toggles.append)
    ring = _ring_pos(btn, 200)
    QTest.mouseClick(btn, Qt.MouseButton.LeftButton, pos=ring)
    assert toggles == []
    centre = QPoint(btn.width() // 2, btn.height() // 2)
    QTest.mouseClick(btn, Qt.MouseButton.LeftButton, pos=centre)
    assert len(toggles) == 1
    btn.close()


def test_keys_adjust_strength(app):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    btn = _make(app)
    btn.set_strength_db(-30)
    QTest.keyClick(btn, Qt.Key.Key_Right)
    assert btn.strength_db() == -31
    QTest.keyClick(btn, Qt.Key.Key_Left)
    QTest.keyClick(btn, Qt.Key.Key_Left)
    assert btn.strength_db() == -29
    QTest.keyClick(btn, Qt.Key.Key_PageUp)
    assert btn.strength_db() == -34
    QTest.keyClick(btn, Qt.Key.Key_Home)
    assert btn.strength_db() == -10
    QTest.keyClick(btn, Qt.Key.Key_End)
    assert btn.strength_db() == -50
    btn.close()


def test_wheel_up_is_stronger(app):
    from PyQt6.QtCore import QPoint, QPointF, Qt
    from PyQt6.QtGui import QWheelEvent
    from PyQt6.QtWidgets import QApplication
    btn = _make(app)
    btn.set_strength_db(-30)
    centre = QPointF(btn.width() / 2, btn.height() / 2)
    ev = QWheelEvent(centre, centre, QPoint(0, 0), QPoint(0, 120),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                     Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(btn, ev)
    assert btn.strength_db() == -32              # 2 dB per notch
    ctrl = QWheelEvent(centre, centre, QPoint(0, 0), QPoint(0, -120),
                       Qt.MouseButton.NoButton, Qt.KeyboardModifier.ControlModifier,
                       Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(btn, ctrl)
    assert btn.strength_db() == -22              # 10 dB with Ctrl, down = gentler
    btn.close()


def test_state_label_and_accessible_name(app):
    btn = _make(app)
    assert btn.state_label() == "Start"
    assert btn.accessibleName() == "Start isolating"
    btn.set_active(True)
    assert btn.state_label() == "Stop"
    assert btn.accessibleName() == "Stop isolating"
    btn.set_active(False)
    btn.set_error(True)
    assert btn.state_label() == "Retry"
    btn.close()


def test_dial_size_follows_responsive_requests(app):
    btn = _make(app)
    btn.set_dial_size(240)
    assert btn.width() == btn.height() == 240
    btn.close()


def test_transition_does_not_hand_focus_to_the_next_widget(app):
    """Disabling the focused dial on Start/Stop made Qt focus the next
    widget, and the page's scroll area jumped to it."""
    from PyQt6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget
    from stream_denoiser.gui.widgets.dial import DialButton
    host = QWidget()
    layout = QVBoxLayout(host)
    btn = DialButton()
    after = QPushButton("next in the tab chain")
    layout.addWidget(btn)
    layout.addWidget(after)
    host.show()
    host.activateWindow()
    _pump(app)
    btn.setFocus()
    _pump(app)
    assert btn.hasFocus()
    btn.set_transitioning(True)
    _pump(app)
    assert QApplication.focusWidget() is not after
    btn.set_transitioning(False)
    _pump(app)
    assert btn.hasFocus()                 # keyboard users keep their place
    host.close()


# -- motion: phases, ignition, snap, stretch ------------------------------------
@pytest.fixture
def motion(monkeypatch):
    monkeypatch.delenv("POISE_NO_ANIM", raising=False)
    monkeypatch.delenv("POISE_REDUCE_MOTION", raising=False)


def test_phases_follow_the_state_api(app, motion):
    btn = _make(app)
    assert btn.phase() == "idle"
    btn._is_active = True                 # a click flips it first
    btn.set_transitioning(True)
    assert btn.phase() == "starting"
    btn.set_transitioning(False)
    assert btn.phase() == "live"
    btn._is_active = False
    btn.set_transitioning(True)
    assert btn.phase() == "stopping"
    btn.set_transitioning(False)
    assert btn.phase() == "idle"
    btn.set_error(True)
    assert btn.phase() == "error"
    btn.close()


def test_live_sweep_closes_once_with_ignited(app, motion):
    btn = _make(app)
    fired = []
    btn.ignited.connect(lambda: fired.append(1))
    btn.set_active(True)
    assert btn.phase() == "live" and fired == []
    _pump(app, btn._ignite_end() / 1000.0 + 0.25)
    assert fired == [1]
    _pump(app, 0.2)
    assert fired == [1]                   # once per start
    btn.close()


def test_reduced_motion_ignites_at_once_and_keeps_still(app, monkeypatch):
    monkeypatch.setenv("POISE_NO_ANIM", "1")
    btn = _make(app)
    fired = []
    btn.ignited.connect(lambda: fired.append(1))
    btn.set_active(True)
    assert fired == [1]
    assert not btn._clock.isActive()
    btn.close()


def test_release_just_off_a_step_snaps_to_it(app, motion):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    btn = _make(app)
    seen = []
    btn.strength_changed.connect(seen.append)
    pos = _ring_pos(btn, 4.5)             # 0.85 of the arc: -44 dB
    QTest.mousePress(btn, Qt.MouseButton.LeftButton, pos=pos)
    assert btn.strength_db() == -44
    QTest.mouseRelease(btn, Qt.MouseButton.LeftButton, pos=pos)
    assert btn.strength_db() == -45 and seen[-1] == -45
    btn.close()


def test_ring_stretches_past_an_end_and_springs_back(app, motion):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from stream_denoiser.gui.widgets import dial
    assert dial.overshoot_degrees(270.0, 0.5) == 0.0
    past_strong = dial.overshoot_degrees(65.0, 1.0)      # into the gap
    assert 0 < past_strong <= dial.OVERSHOOT_MAX
    assert dial.overshoot_degrees(120.0, 0.0) < 0         # before gentle
    btn = _make(app)
    start = _ring_pos(btn, 30)
    QTest.mousePress(btn, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(btn, _ring_pos(btn, 60))              # past "strong"
    assert btn._over > 0 and btn.strength_db() == dial.ATTEN_STRONG
    QTest.mouseRelease(btn, Qt.MouseButton.LeftButton, pos=_ring_pos(btn, 60))
    _pump(app, 0.8)
    assert btn._over == pytest.approx(0.0, abs=0.05)
    btn.close()


def test_readout_digits_roll_to_the_value(app, motion):
    btn = _make(app)
    btn.set_strength_db(-37)
    _pump(app, 0.6)
    assert btn._tens.value == pytest.approx(3) and btn._ones.value == pytest.approx(7)
    btn.close()


# -- wheel / key steps: glide, trail, stretch ---------------------------------------
def _wheel(btn, notches=1, ctrl=False):
    from PyQt6.QtCore import QPoint, QPointF, Qt
    from PyQt6.QtGui import QWheelEvent
    from PyQt6.QtWidgets import QApplication
    centre = QPointF(btn.width() / 2, btn.height() / 2)
    mods = (Qt.KeyboardModifier.ControlModifier if ctrl
            else Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(btn, QWheelEvent(
        centre, centre, QPoint(0, 0), QPoint(0, 120 * notches),
        Qt.MouseButton.NoButton, mods, Qt.ScrollPhase.NoScrollPhase, False))


def test_wheel_step_glides_the_needle_and_shows_it(app, motion):
    """The value changes at once; the needle (and the lit edge) glide
    there, shown like a drag, then fade back after the last step."""
    from stream_denoiser.gui.widgets import dial as d
    btn = _make(app)
    btn.set_strength_db(-30)
    _pump(app, 0.1)
    start = btn._needle_pos.value
    assert start == d.lit_count(-30) - 1
    assert btn._needle(btn._ms())[0] < 0.5          # idle: needle hidden
    _wheel(btn, ctrl=True)                          # 10 dB stronger
    assert btn.strength_db() == -40
    target = d.lit_count(-40) - 1
    assert btn._needle_pos.target == target
    assert btn._needle_pos.value < target           # not jumped
    _pump(app, 0.08)
    assert start < btn._needle_pos.value < target   # mid-glide
    _pump(app, 0.25)
    assert btn._needle_pos.value == pytest.approx(target)
    assert btn._needle(btn._ms())[0] == pytest.approx(1.0)   # shown
    assert btn._strong_hot.target == 1.0            # heading strong
    _pump(app, (d.NUDGE_HOLD_MS + d.NUDGE_FADE_MS) / 1000 + 0.1)
    assert btn._nudge.value == pytest.approx(0.0)
    assert btn._needle(btn._ms())[0] < 0.5          # faded back
    assert btn._strong_hot.target == 0.0
    btn.close()


def test_wheel_step_leaves_a_trail_along_the_ticks_it_passes(app, motion):
    """Each tick the needle passes flashes (like the starting comet) in
    the order it passes them, then settles."""
    import time as _time
    from stream_denoiser.gui.widgets import dial as d
    btn = _make(app)
    btn.set_strength_db(-30)
    _pump(app, 0.1)
    before = d.lit_count(-30)
    _wheel(btn, ctrl=True)
    after = d.lit_count(-40)
    assert sorted(btn._trail) == list(range(before, after))  # newly lit
    stamps = [btn._trail[i] for i in range(before, after)]
    assert stamps == sorted(stamps)                 # in passing order
    assert stamps[-1] - stamps[0] <= d.NUDGE_GLIDE_MS / 1000
    _pump(app, 0.2)
    now = _time.monotonic()
    assert any(btn._trail_glow(i, now) > 0.2 for i in range(before, after))
    btn.grab()                                      # paints the trail
    _pump(app, (d.NUDGE_GLIDE_MS + d.TRAIL_MS) / 1000 + 0.1)
    assert not btn._trail                           # all settled
    # Gentler: the ticks going dark flash, from the old head down.
    _wheel(btn, -1)
    assert sorted(btn._trail) == list(range(d.lit_count(-38), after))
    stamps = [btn._trail[i] for i in range(after - 1, d.lit_count(-38) - 1,
                                               -1)]
    assert stamps == sorted(stamps)
    btn.close()


def test_stepping_past_an_end_stretches_the_ring(app, motion):
    from stream_denoiser.gui.widgets import dial as d
    btn = _make(app)
    btn.set_strength_db(d.ATTEN_STRONG)
    _pump(app, 0.1)
    _wheel(btn)                                     # stronger than strongest
    assert btn.strength_db() == d.ATTEN_STRONG
    assert btn._over > 0                            # gives at the strong end
    _pump(app, 0.8)
    assert btn._over == pytest.approx(0.0, abs=0.01)
    btn.set_strength_db(d.ATTEN_GENTLE)
    _wheel(btn, -1)
    assert btn._over < 0                            # ...and the gentle end
    btn.close()


def test_keys_step_like_the_wheel(app, motion):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from stream_denoiser.gui.widgets import dial as d
    btn = _make(app)
    btn.set_strength_db(-30)
    _pump(app, 0.1)
    QTest.keyClick(btn, Qt.Key.Key_End)
    assert btn.strength_db() == d.ATTEN_STRONG
    assert btn._needle_pos.value < d.TICKS - 1      # gliding, not jumped
    assert btn._trail
    btn.close()


def test_drags_and_reduced_motion_do_not_glide(app, monkeypatch):
    from stream_denoiser.gui.widgets import dial as d
    btn = _make(app)
    btn.set_strength_db(-30)
    btn._user_set_strength(-45)                     # drag-style change
    assert btn._needle_pos.value == d.lit_count(-45) - 1
    monkeypatch.setenv("POISE_NO_ANIM", "1")
    _wheel(btn, ctrl=True)
    assert btn.strength_db() == -50
    assert btn._needle_pos.value == d.lit_count(-50) - 1
    assert not btn._trail and btn._over == 0.0
    btn.close()
