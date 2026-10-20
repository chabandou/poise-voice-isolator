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
