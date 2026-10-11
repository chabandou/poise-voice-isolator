"""Status-bar stats, model cards, settings rows and the setup summary."""
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


STATS = {"rtf": 0.11, "avg_time_ms": 1.2, "aad_bypass_ratio": 0.38,
         "input_buffer": 2, "output_buffer": 2}


def test_stats_bar_idle_then_live_then_reset(app):
    from stream_denoiser.gui.widgets.stats_bar import StatsBar
    bar = StatsBar()
    bar.show()
    _pump(app)
    assert bar._hint.isVisible() and not bar._stats.isVisible()
    bar.update_stats(STATS)
    _pump(app)
    assert bar._stats.isVisible() and not bar._hint.isVisible()
    assert bar._values["load"].text() == "0.11x"
    assert bar._values["frame"].text() == "1.2 ms"
    assert bar._values["skipped"].text() == "38%"
    assert bar._values["buffer"].text() == "2/2"
    bar.reset()
    _pump(app)
    assert bar._hint.isVisible() and not bar._stats.isVisible()
    assert bar._values["load"].objectName() == "sb-value"
    bar.close()


@pytest.mark.parametrize("rtf,name", [(0.3, "sb-good"), (0.85, "sb-warn"),
                                      (1.4, "sb-bad")])
def test_stats_bar_load_colour_thresholds(app, rtf, name):
    from stream_denoiser.gui.widgets.stats_bar import StatsBar
    bar = StatsBar()
    bar.update_stats(dict(STATS, rtf=rtf))
    assert bar._values["load"].objectName() == name


def test_stats_bar_state_dot(app):
    from stream_denoiser.gui.widgets.stats_bar import StatsBar
    bar = StatsBar()
    bar.set_state("processing", "isolating")
    assert bar._dot.property("state") == "processing"
    assert bar._state.text() == "isolating"
    bar.set_state("error")
    assert bar._state.text() == "error"


def test_model_cards_select_and_signal(app):
    from stream_denoiser.gui.widgets.model_cards import ModelCards
    cards = ModelCards()
    cards.show()
    _pump(app)
    models = cards.models()
    assert "deepfilternet3" in models
    assert cards.currentText() in models
    seen = []
    cards.currentTextChanged.connect(seen.append)
    usable = [m for m in models if cards._cards[m].isEnabled()]
    other = next((m for m in usable if m != cards.currentText()), None)
    if other:
        cards.setCurrentText(other)
        assert cards.currentText() == other and seen == [other]
    cards.setCurrentText("not-a-model")          # ignored
    assert cards.currentText() in models
    cards.setEnabled(False)
    assert not any(c.isEnabled() for c in cards._cards.values())
    cards.close()


def test_settings_row_lights_on_hover_and_focus(app):
    from PyQt6.QtCore import QEvent
    from PyQt6.QtWidgets import QPushButton
    from stream_denoiser.gui.widgets.settings_row import SettingsRow
    ctl = QPushButton("x")
    row = SettingsRow("Title", "caption", ctl)
    row.set_position(True, True)
    row.show()
    _pump(app)
    # Offscreen puts the pointer at (0, 0), inside the row: clear that.
    row.leaveEvent(QEvent(QEvent.Type.Leave))
    assert not row.is_lit
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QEnterEvent
    pt = QPointF(2, 2)
    row.enterEvent(QEnterEvent(pt, pt, pt))
    assert row.is_lit
    row.leaveEvent(QEvent(QEvent.Type.Leave))
    assert not row.is_lit
    from PyQt6.QtGui import QFocusEvent
    from PyQt6.QtCore import Qt
    row.eventFilter(ctl, QFocusEvent(QEvent.Type.FocusIn,
                                     Qt.FocusReason.TabFocusReason))
    assert row.is_lit
    row.eventFilter(ctl, QFocusEvent(QEvent.Type.FocusOut,
                                     Qt.FocusReason.TabFocusReason))
    assert not row.is_lit
    # Programmatic/initial focus does not light the row.
    row.eventFilter(ctl, QFocusEvent(QEvent.Type.FocusIn,
                                     Qt.FocusReason.OtherFocusReason))
    assert not row.is_lit
    row.grab()                                   # paints without error
    row.close()


def test_settings_row_lock_note_swaps_subtitle_and_disables(app):
    from PyQt6.QtWidgets import QPushButton
    from stream_denoiser.gui.widgets.settings_row import SettingsRow
    ctl = QPushButton("x")
    row = SettingsRow("Title", "caption", ctl)
    row.set_locked(True)
    assert row._sub.text() == "Locked while running"
    assert not ctl.isEnabled()
    row.set_locked(False)
    assert row._sub.text() == "caption" and ctl.isEnabled()


def test_setup_summary_reflects_settings(app):
    from stream_denoiser.gui.widgets.setup_summary import SetupSummary
    summary = SetupSummary()
    opened = []
    summary.open_settings.connect(lambda: opened.append(True))
    summary.refresh("deepfilternet3", True, -45.0)
    assert summary._model_value.text() == "DeepFilterNet3"
    assert summary._aad_value.text() == "On"
    assert "-45 dB" in summary._aad_sub.text()
    summary.refresh("deepfilternet3", False, -45.0)
    assert summary._aad_value.text() == "Off"
    summary.settings_btn.click()
    assert opened == [True]
