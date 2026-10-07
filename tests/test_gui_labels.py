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


def test_home_card_uses_aad(app):
    from stream_denoiser.gui.main_window import MainWindow
    window = MainWindow()
    window.show()
    _pump(app)
    texts = _labels(window)
    assert "AAD" in texts
    assert "Audio Activity detection" in texts
    assert "VAD BYPASS" not in texts
    joined = "\n".join(texts)
    assert "VAD" not in joined and "Voice Activity" not in joined
    window.close()


def test_stats_panel_uses_aad(app):
    from PyQt6.QtWidgets import QLabel
    from stream_denoiser.gui.widgets.stats_panel import StatsPanel
    panel = StatsPanel()
    panel.show()
    _pump(app)
    texts = [w.text() for w in panel.findChildren(QLabel)]
    assert "AAD BYPASS" in texts
    assert not any("VAD" in t for t in texts)
