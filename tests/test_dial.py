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
    assert btn.strength_db() == -31
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
