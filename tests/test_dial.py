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
    now = _time.perf_counter()
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


# -- the ring's cached layers ---------------------------------------------------
def _settled(app, theme, phase):
    """A dial long settled in `phase` under `theme`, its clock frozen."""
    from stream_denoiser.gui import themes
    themes.set_current(theme)
    btn = _make(app)
    btn._sweep_at = None                  # the ring fully drawn
    if phase == "live":
        btn.set_active(True)
    btn._phase_at -= 60.0                 # long after the bloom / ignite
    t = btn._ms()
    btn._ms = lambda: t
    btn._idle_breath = lambda: 0.7
    return btn, t


@pytest.mark.parametrize("theme,phase", [
    ("abyss", "live"), ("vigil", "live"), ("vigil", "idle")])
def test_a_pulse_alone_redraws_no_ring(app, motion, theme, phase):
    """The alpha the lit ticks share (the live charge, the breath) is
    drawn as the opacity of cached images, not into them."""
    from stream_denoiser.gui import themes
    before = themes.current_id()
    try:
        btn, _ = _settled(app, theme, phase)
        drawn = []
        draw = btn._draw_ring
        btn._draw_ring = lambda *a: drawn.append(1) or draw(*a)
        btn._live_alpha = lambda t: 0.8
        btn.grab()
        assert drawn
        first = len(drawn)
        btn._live_alpha = lambda t: 0.95
        btn._idle_breath = lambda: 0.9
        btn.grab()
        assert len(drawn) == first
        btn.close()
    finally:
        themes.set_current(before)


@pytest.mark.parametrize("theme,phase", [
    ("abyss", "live"), ("vigil", "live"), ("vigil", "idle")])
def test_the_layered_ring_looks_as_drawn_whole(app, motion, theme, phase):
    import math as m
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QImage, QPainter
    from stream_denoiser.gui import themes
    from stream_denoiser.gui.themes import current
    before = themes.current_id()
    try:
        btn, t = _settled(app, theme, phase)
        btn._live_alpha = lambda t: 0.83
        col = btn._colours(current())
        w, h, dpr = btn.width(), btn.height(), btn.devicePixelRatioF()
        whole = btn._draw_ring(w, h, dpr, btn._ring_strokes(col, t))
        layered = QImage(m.ceil(w * dpr), m.ceil(h * dpr),
                         QImage.Format.Format_ARGB32_Premultiplied)
        layered.setDevicePixelRatio(dpr)
        layered.fill(Qt.GlobalColor.transparent)
        p = QPainter(layered)
        btn._paint_ring(p, col, t)
        p.end()
        assert len(btn._ring) >= 2        # the pulse has its own layers
        worst = 0
        for y in range(0, layered.height(), 2):
            for x in range(0, layered.width(), 2):
                a, b = whole.pixel(x, y), layered.pixel(x, y)
                worst = max(worst, *(abs(((a >> s) & 255) - ((b >> s) & 255))
                                     for s in (0, 8, 16, 24)))
        assert worst <= 3
        btn.close()
    finally:
        themes.set_current(before)


@pytest.mark.parametrize("theme", ["abyss", "vigil"])
def test_the_cached_disc_looks_as_drawn_and_a_charge_redraws_none(
        app, motion, theme):
    import math as m
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QImage, QPainter
    from stream_denoiser.gui import themes
    from stream_denoiser.gui.themes import current
    from stream_denoiser.gui.widgets.dial import REF
    before = themes.current_id()
    try:
        btn, _ = _settled(app, theme, "live")
        col = btn._colours(current())
        w, h, dpr = btn.width(), btn.height(), btn.devicePixelRatioF()
        paint = (btn._paint_disc_breath if theme == "vigil"
                 else btn._paint_disc)

        def render(cached, charge):
            image = QImage(m.ceil(w * dpr), m.ceil(h * dpr),
                           QImage.Format.Format_ARGB32_Premultiplied)
            image.setDevicePixelRatio(dpr)
            image.fill(Qt.GlobalColor.transparent)
            p = QPainter(image)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            k, c = min(w, h) / REF, REF / 2
            p.translate(w / 2, h / 2)
            p.scale(k, k)
            p.translate(-c, -c)
            if cached:
                btn._paint_disc_cached(p, col, charge, 0.0, paint)
            else:
                paint(p, col, charge, 0.0)
            p.end()
            return image

        worst = 0
        whole, parts = render(False, 0.6), render(True, 0.6)
        for y in range(0, whole.height(), 2):
            for x in range(0, whole.width(), 2):
                a, b = whole.pixel(x, y), parts.pixel(x, y)
                worst = max(worst, *(abs(((a >> s) & 255) - ((b >> s) & 255))
                                     for s in (0, 8, 16, 24)))
        assert worst <= 3
        images = {part: entry[1] for part, entry in btn._disc_parts.items()}
        assert set(images) == {"glow", "face", "inner", "rim"}
        render(True, 0.25)                  # the charge moves on
        assert all(btn._disc_parts[part][1] is image
                   for part, image in images.items())
        btn.close()
    finally:
        themes.set_current(before)


def test_the_clock_waits_for_the_first_sweep(app, motion):
    """Before the ring starts sweeping on, nothing in the dial moves: no
    frames (an entrance effect over it would redraw for each)."""
    btn = _make(app)
    assert btn._sweep_at is not None and btn._since(btn._sweep_at) < 0
    assert not btn._clock.isActive()
    assert btn._sweeping()                      # (its ticks hide till then)
    btn._sweep_at -= btn._sweep_ms()[0] / 1000.0  # it starts
    btn._run_clock()
    assert btn._clock.isActive()
    btn.close()


def test_the_sweep_starts_when_its_timer_fires_early(app, motion):
    """Timers can fire a few ms before they are due: the sweep starts
    then all the same, so its clock runs (else the ring only drew on as
    other repaints came)."""
    btn = _make(app)
    btn._sweep_at = time.perf_counter() + 0.004
    btn._begin_sweep()                          # fired 4 ms before it was due
    assert btn._since(btn._sweep_at) >= 0
    assert btn._clock.isActive()
    btn.close()


def test_home_holds_the_sweep_till_its_entrance(app, motion):
    """The window puts the first sweep off for Home's entrance: the
    dial's own timer then does nothing, and sweep_on_in starts it."""
    from stream_denoiser.gui.widgets import dial as d
    btn = _make(app)
    btn.hold_sweep()
    btn._begin_sweep()                          # the dial's own timer
    assert btn._since(btn._sweep_at) < -1000    # still held
    assert not btn._clock.isActive()
    btn.sweep_on_in(0)
    btn._begin_sweep()
    assert btn._sweep_moving() and btn._clock.isActive()
    started = btn._sweep_at
    btn.sweep_on_in(500)                        # too late: it has begun
    assert btn._sweep_at == started
    assert d.SWEEP_HOLD_MS >= 2000
    btn.close()


def test_a_crest_leads_the_first_sweep(app, motion):
    """Tactile themes: the ticks just reached are brightest, the crest
    fades behind them, and it is gone when the sweep ends."""
    from stream_denoiser.gui.widgets import dial as d
    btn = _make(app)
    btn._sweep_at = time.perf_counter() - d.SWEEP_MS * 0.3 / 1000.0
    crest = [btn._sweep_crest(i) for i in range(d.TICKS)]
    shown = [btn._sweep_visibility(i) for i in range(d.TICKS)]
    head = max(i for i in range(d.TICKS) if shown[i] > 0)
    assert 0 < head < d.TICKS - 1
    assert crest[0] == 0.0 and crest[head + 1] == 0.0
    assert max(crest) > 0.9
    assert crest.index(max(crest)) > head - 4  # at the front
    btn._sweep_at = time.perf_counter() - d.SWEEP_MS / 1000.0
    assert not any(btn._sweep_crest(i) for i in range(d.TICKS))
    assert all(btn._sweep_visibility(i) == 1.0 for i in range(d.TICKS))
    btn.close()
