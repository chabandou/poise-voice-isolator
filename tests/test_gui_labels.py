"""AAD product naming guards (needs Qt; skipped without it).

The detector is named AAD ("Audio Activity detection") everywhere,
including identifiers and persisted keys (legacy vad_* settings keys
migrate on first read; old --vad-* CLI flags still work as aliases).
"""
import os
import time

import pytest

pytest.importorskip("PyQt6.QtWidgets")


@pytest.fixture(scope="module")
def app():
    # Forced offscreen (not setdefault): deterministic rendering.
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _pump(app, secs=0.4):
    end = time.time() + secs
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def _labels(window):
    from PyQt6.QtWidgets import QLabel
    return [w.text() for w in window.findChildren(QLabel)]


def test_settings_row_uses_aad_naming(app):
    from stream_denoiser.gui.main_window import MainWindow
    window = MainWindow()
    window.show()
    _pump(app)
    texts = _labels(window)
    # Friendly title, formal AAD name kept in the caption.
    assert "Skip silence" in texts
    assert any("Audio Activity detection" in t for t in texts)
    assert "VAD BYPASS" not in texts
    joined = "\n".join(texts)
    assert "VAD" not in joined and "Voice Activity" not in joined
    window.close()


def test_stats_bar_has_no_vad_wording(app):
    from PyQt6.QtWidgets import QLabel
    from stream_denoiser.gui.widgets.stats_bar import StatsBar
    bar = StatsBar()
    bar.show()
    _pump(app)
    bar.update_stats({"rtf": 0.11, "avg_time_ms": 1.2,
                      "aad_bypass_ratio": 0.38,
                      "input_buffer": 2, "output_buffer": 2})
    texts = [w.text() for w in bar.findChildren(QLabel)]
    assert "skipped" in texts
    assert "38%" in texts
    assert not any("VAD" in t for t in texts)
