"""FrameTimer: the ambient loops share one clock, so they fire together."""
import os
import time

import pytest

pytest.importorskip("PyQt6.QtWidgets")


@pytest.fixture(scope="module")
def app():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _pump(app, secs):
    end = time.time() + secs
    while time.time() < end:
        app.processEvents()
        time.sleep(0.002)


def test_loops_fire_on_the_same_ticks(app):
    from stream_denoiser.gui.animations import FrameTimer, _clock
    fast, slow = FrameTimer(), FrameTimer()
    ticks = {"fast": [], "slow": []}
    fast.timeout.connect(lambda: ticks["fast"].append(time.perf_counter()))
    slow.timeout.connect(lambda: ticks["slow"].append(time.perf_counter()))
    fast.start(16)
    slow.start(33)
    assert fast.isActive() and slow.interval() == 33
    _pump(app, 0.6)
    fast.stop()
    slow.stop()
    # Off the clock (other tests' widgets may still have loops on it).
    assert not fast.isActive()
    assert id(fast) not in _clock()._running
    assert id(slow) not in _clock()._running
    assert len(ticks["slow"]) >= 5
    assert len(ticks["fast"]) > len(ticks["slow"])
    # Each slow tick came with a fast one, on the same clock tick (ticks
    # themselves are at least 15 ms apart).
    for t in ticks["slow"]:
        assert min(abs(t - f) for f in ticks["fast"]) < 0.002


def _count(app, loop, secs):
    fired = []
    loop.timeout.connect(lambda: fired.append(1))
    _pump(app, secs)
    loop.timeout.disconnect()
    return len(fired)


def test_steady_loops_slow_while_another_app_is_in_front(app):
    from PyQt6.QtCore import Qt
    from stream_denoiser.gui.animations import (
        BACKGROUND_PACE, FrameTimer, _clock)
    clock = _clock()
    steady, transition = FrameTimer(), FrameTimer()
    steady.start(50)
    transition.start(16)
    try:
        clock._on_state(Qt.ApplicationState.ApplicationActive)
        in_front = _count(app, steady, 1.0)
        clock._on_state(Qt.ApplicationState.ApplicationInactive)
        assert clock.interval_of(steady) == 50 * BACKGROUND_PACE
        assert clock.interval_of(transition) == 16
        behind = _count(app, steady, 1.0)
        fast_behind = _count(app, transition, 0.5)
    finally:
        clock._on_state(app.applicationState())
        steady.stop()
        transition.stop()
    assert 16 <= in_front <= 21              # ~20 a second
    assert 8 <= behind <= 11                 # ~10
    assert fast_behind >= 20                 # still ~one a clock tick


def test_a_stopped_loop_stays_quiet(app):
    from stream_denoiser.gui.animations import FrameTimer
    quiet = FrameTimer()
    fired = []
    quiet.timeout.connect(lambda: fired.append(1))
    quiet.start(16)
    quiet.stop()
    _pump(app, 0.1)
    assert fired == []


def test_a_loop_gone_with_its_widget_is_dropped(app):
    from PyQt6 import sip
    from PyQt6.QtWidgets import QWidget
    from stream_denoiser.gui.animations import FrameTimer, _clock
    owner = QWidget()
    loop = FrameTimer(owner)
    loop.start(16)
    key = id(loop)
    sip.delete(owner)                     # the loop goes with it
    _pump(app, 0.1)
    assert key not in _clock()._running


def test_transitions_tick_on_a_precise_clock(app, monkeypatch):
    """A 16 ms loop must not land on Windows' 15.6 ms ticks (16 or 31 ms,
    by turns); steady loops stay coarse."""
    from PyQt6.QtCore import Qt
    from stream_denoiser.gui import animations
    asked = []
    monkeypatch.setattr(animations, "_fine_timers", asked.append)
    clock = animations._clock()
    steady = animations.FrameTimer()
    steady.start(50)
    try:
        assert clock._timer.timerType() == Qt.TimerType.CoarseTimer
        assert asked[-1] is False
        fast = animations.FrameTimer()
        fast.start(16)
        assert clock._timer.timerType() == Qt.TimerType.PreciseTimer
        assert asked[-1] is True
        fast.stop()
        assert clock._timer.timerType() == Qt.TimerType.CoarseTimer
        assert asked[-1] is False
    finally:
        steady.stop()
