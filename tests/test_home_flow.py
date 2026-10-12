"""Home/Settings wiring after the redesign (needs Qt; skipped without it)."""
import os
import time

import pytest

pytest.importorskip("PyQt6.QtWidgets")


@pytest.fixture(scope="module")
def app():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _pump(app, secs=0.3):
    end = time.time() + secs
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


@pytest.fixture()
def window(app):
    from stream_denoiser.gui.main_window import MainWindow
    win = MainWindow()
    win.resize(1180, 760)
    win.show()
    _pump(app)
    saved = (win.settings.atten_lim_db, win.settings.aad_enabled,
             win.settings.aad_threshold, win.settings.model)
    yield win
    (win.settings.atten_lim_db, win.settings.aad_enabled,
     win.settings.aad_threshold, win.settings.model) = saved
    win.close()


def test_dial_ring_persists_attenuation(window):
    window.power_btn._user_set_strength(-72)
    assert float(window.settings.atten_lim_db) == -72.0


def test_dial_starts_at_the_saved_attenuation(window):
    assert window.power_btn.strength_db() == int(window.settings.atten_lim_db)


def test_summary_follows_settings_changes(window):
    window.aad_switch.setChecked(False)
    assert window.setup_summary._aad_value.text() == "Off"
    assert not window.thresh_slider.isEnabled()
    window.aad_switch.setChecked(True)
    window.thresh_slider.setValue(-33)
    assert window.setup_summary._aad_value.text() == "On"
    assert "-33 dB" in window.setup_summary._aad_sub.text()
    assert window.thresh_val_label.text() == "-33 dB"


def test_model_cards_drive_the_summary(window):
    usable = [m for m, c in window.model_cards._cards.items()
              if c.isEnabled()]
    for model in usable:
        window.model_cards.setCurrentText(model)
        label = window.setup_summary._model_value.text()
        assert label and label != "-"
        assert window.settings.model == model


def test_controls_lock_while_running(window):
    window._set_controls_enabled(False)
    assert not window.output_selector.isEnabled()
    assert not window.model_cards.isEnabled()
    # The lock is explained once in the routing note, not the subtitle.
    subtitle = "Where the clean audio plays"
    assert window.output_selector._subtitle.text() == subtitle
    window._set_controls_enabled(True)
    assert window.output_selector.isEnabled()
    assert window.model_cards.isEnabled()
    assert window.output_selector._subtitle.text() == subtitle


def test_status_messages_drive_headline_and_status_bar(window):
    from stream_denoiser.gui.main_window import HOME_TITLES
    window.update_status("Starting...")
    assert window.home_title.text() == HOME_TITLES["starting"]
    window.update_status("Isolating audio")
    assert window.home_title.text() == HOME_TITLES["isolating"]
    assert window.stats_bar._state.text() == "isolating"
    window.update_status("Error: boom")
    assert window.home_title.text() == HOME_TITLES["error"]
    assert window.status_label.text() == "Error: boom"
    window.update_status("Ready")
    assert window.home_title.text() == HOME_TITLES["ready"]
    assert window.stats_bar._state.text() == "standby"


def test_home_only_keeps_the_everyday_controls(window):
    """Silence/model/tray controls live in Settings; Home has the dial,
    the output device and the read-only summary."""
    from stream_denoiser.gui.widgets.slider import HoverSlider
    home = window.stack.widget(0)
    assert home.isAncestorOf(window.power_btn)
    assert home.isAncestorOf(window.output_selector)
    assert home.isAncestorOf(window.setup_summary)
    assert not home.isAncestorOf(window.aad_switch)
    assert not home.isAncestorOf(window.model_cards)
    assert not home.findChildren(HoverSlider)


def test_every_theme_switch_applies_cleanly(app, window):
    from stream_denoiser.gui import themes as theme_store
    original = window.settings.theme
    try:
        for index, theme_id in enumerate(theme_store.theme_ids()):
            window._on_theme_changed(index)
            _pump(app, 0.1)
            assert theme_store.current_id() == theme_id
            assert theme_store.current()["secondary"].lower() in \
                window.styleSheet().lower()
            window.grab()          # every custom paint path runs
    finally:
        ids = theme_store.theme_ids()
        window._on_theme_changed(ids.index(original))
