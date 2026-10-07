"""Tooltip manager behavior (needs Qt; skipped without it)."""
import os
import time

import pytest

pytest.importorskip("PyQt6.QtWidgets")


@pytest.fixture(scope="module")
def app():
    # Forced offscreen (not setdefault): deterministic geometry.
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _manager(app, parent=None, delay=30):
    from stream_denoiser.gui.tooltip import TipManager
    return TipManager(app, parent, show_delay_ms=delay)


def _pump(app, secs=0.4):
    end = time.time() + secs
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def test_tooltip_event_is_accepted_and_shown(app):
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QHelpEvent
    from PyQt6.QtWidgets import QPushButton
    mgr = _manager(app)
    btn = QPushButton("x")
    btn.setToolTip("hello tip")
    btn.resize(100, 30)
    btn.show()
    ev = QHelpEvent(QEvent.Type.ToolTip, btn.rect().center(),
                    btn.mapToGlobal(btn.rect().center()))
    assert mgr.eventFilter(btn, ev) is True
    assert ev.isAccepted()
    _pump(app, 0.3)
    assert mgr._tip.isVisible()
    assert mgr._tip.text() == "hello tip"
    btn.close()


def test_empty_tip_hides(app):
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QHelpEvent
    from PyQt6.QtWidgets import QPushButton
    mgr = _manager(app)
    btn = QPushButton("x")
    btn.resize(100, 30)
    btn.show()
    mgr._arm("stale")
    _pump(app, 0.2)
    assert mgr._tip.isVisible()
    ev = QHelpEvent(QEvent.Type.ToolTip, btn.rect().center(),
                    btn.mapToGlobal(btn.rect().center()))
    assert mgr.eventFilter(btn, ev) is False
    _pump(app, 0.3)
    assert not mgr._tip.isVisible()
    btn.close()


def test_press_and_leave_hide(app):
    from PyQt6.QtCore import QEvent
    mgr = _manager(app)
    mgr._arm("transient")
    _pump(app, 0.3)
    assert mgr._tip.isVisible()
    mgr.eventFilter(mgr._tip, QEvent(QEvent.Type.Leave))
    _pump(app, 0.3)
    assert not mgr._tip.isVisible()
    mgr._arm("transient")
    _pump(app, 0.3)
    assert mgr._tip.isVisible()
    mgr.eventFilter(mgr._tip, QEvent(QEvent.Type.MouseButtonPress))
    _pump(app, 0.3)
    assert not mgr._tip.isVisible()


def test_reduced_motion_is_instant(app, monkeypatch):
    monkeypatch.setenv("POISE_NO_ANIM", "1")
    mgr = _manager(app)
    assert mgr._motion_ok() is False
    mgr._arm("instant")
    _pump(app, 0.3)
    assert mgr._tip.isVisible()
    assert mgr._tip.text() == "instant"
    assert mgr._anim is None
    mgr._hide_tip(cancel_armed=True)
    assert not mgr._tip.isVisible()
