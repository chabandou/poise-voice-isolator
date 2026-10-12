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
    window.power_btn._user_set_strength(-42)
    assert float(window.settings.atten_lim_db) == -42.0


def test_dial_starts_at_the_saved_attenuation(window):
    assert window.power_btn.strength_db() == int(window.settings.atten_lim_db)


def test_legacy_attenuation_is_clamped_to_the_dial(window):
    window.settings.atten_lim_db = -72.0        # saved by an older build
    assert window._saved_atten_db() == -50


def test_dial_changes_reach_a_running_engine(window):
    seen = []

    class Engine:
        def set_atten_lim_db(self, db):
            seen.append(db)

    window.worker._engine = Engine()
    try:
        window.power_btn._user_set_strength(-17)
    finally:
        window.worker._engine = None
    assert seen == [-17.0]
    assert window.worker.atten_lim_db == -17.0


def test_threshold_changes_reach_a_running_detector(window):
    seen = []

    class Detector:
        def set_threshold(self, db):
            seen.append(db)

    class Processor:
        aad = Detector()

    window.aad_switch.setChecked(True)
    window.worker._processor = Processor()
    try:
        window.thresh_slider.setValue(-52)
    finally:
        window.worker._processor = None
    assert seen == [-52.0]
    assert window.worker.aad_threshold == -52.0
    assert float(window.settings.aad_threshold) == -52.0


def test_threshold_without_a_detector_is_only_stored(window):
    class Processor:
        aad = None                     # run started with skipping off

    window.worker._processor = Processor()
    try:
        window.worker.set_aad_threshold(-45.0)
    finally:
        window.worker._processor = None
    assert window.worker.aad_threshold == -45.0


def test_skip_silence_switch_locks_while_running(window, monkeypatch):
    monkeypatch.setattr(window, "tray", None)
    switch_done = window.settings.device_switch_done
    try:
        window.aad_switch.setChecked(True)
        window._on_worker_started()
        assert not window.aad_switch.isEnabled()
        assert window._aad_row._sub.text() == "Locked while running"
        assert window.thresh_slider.isEnabled()   # threshold stays live
        window._on_worker_stopped()
        assert window.aad_switch.isEnabled()
        assert window._aad_row._sub.text().startswith("Audio Activity")
    finally:
        window.settings.device_switch_done = switch_done


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


def test_status_messages_drive_headline_and_status_bar(window, monkeypatch):
    from stream_denoiser.gui.main_window import HOME_TITLES
    monkeypatch.setenv("POISE_NO_ANIM", "1")       # wording, not motion
    window.update_status("Starting...")
    assert window.home_title.text() == HOME_TITLES["starting"]
    assert window.stats_bar._state.text() == "starting…"
    window.update_status("Loading model...")
    assert window.stats_bar._state.text() == "loading model…"
    window.update_status("Isolating audio")
    assert window.home_title.text() == HOME_TITLES["isolating"]
    assert window.stats_bar._state.text() == "processing"
    # The worker's loop says "Processing" after that; Home must stay put.
    window.update_status("Processing")
    assert window.home_title.text() == HOME_TITLES["isolating"]
    assert window.stats_bar._state.text() == "processing"
    window.update_status("Error: boom")
    assert window.home_title.text() == HOME_TITLES["error"]
    assert window.status_label.text() == "Error: boom"
    window.update_status("Ready")
    assert window.home_title.text() == HOME_TITLES["ready"]
    assert window.stats_bar._state.text() == "ready"


def test_status_changes_fade_and_coalesce(app, window, monkeypatch):
    """Home's headline/status line fade between messages; a burst of
    messages shows only the newest; the isolating pulse waits its turn."""
    from PyQt6.QtWidgets import QGraphicsOpacityEffect
    from stream_denoiser.gui.main_window import HOME_TITLES
    monkeypatch.delenv("POISE_NO_ANIM", raising=False)
    monkeypatch.delenv("POISE_REDUCE_MOTION", raising=False)
    window._on_page_requested(0)
    _pump(app)
    window.update_status("Initializing...")
    # Mid-fade: the old text is still up, fading out.
    assert window.home_title.text() == HOME_TITLES["ready"]
    assert isinstance(window.home_title.graphicsEffect(), QGraphicsOpacityEffect)
    window.update_status("Loading model...")    # arrives during the fade-out
    _pump(app, 0.5)
    assert window.home_title.text() == HOME_TITLES["starting"]
    assert window.status_label.text() == "Loading model..."
    assert window.home_title.graphicsEffect() is None   # effect dropped
    assert window.stats_bar._state.text() == "loading model…"

    # Running: the pulse starts only after "Isolating" has faded in.
    window.update_status("Isolating audio")
    window._start_status_pulse()
    assert window._status_pulse is None and window._status_swap.busy
    _pump(app, 0.5)
    assert window.status_label.text() == "Processing"
    assert window._status_pulse is not None
    assert window.status_label.graphicsEffect() is window._status_pulse_eff

    # Leaving the isolating line stops the pulse so the swap can fade.
    window.update_status("Stopping...")
    assert window._status_pulse is None
    _pump(app, 0.5)
    assert window.status_label.text() == "Stopping..."
    assert window.status_label.graphicsEffect() is None
    window._stop_status_pulse()


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


# -- Logs page ----------------------------------------------------------------------
@pytest.fixture()
def session_log():
    from stream_denoiser import logging_config
    handler = logging_config.enable_memory_log()
    yield handler
    logging_config._reset_memory_log_for_tests()


def test_logs_page_follows_the_session_log_live(app, window, session_log):
    from stream_denoiser.logging_config import get_logger
    window._on_page_requested(2)
    assert window._log_timer.isActive()
    log = get_logger("test-poise-logs-page")
    log.info("dial moved to -30 dB")
    log.error("stream failed: device unplugged")
    _pump(app, 0.8)                                  # > one poll interval
    text = window.log_view.toPlainText()
    assert "dial moved to -30 dB" in text
    assert "stream failed: device unplugged" in text
    window._on_page_requested(0)
    assert not window._log_timer.isActive()


def test_logs_page_colours_errors(window, session_log):
    from PyQt6.QtGui import QColor
    from stream_denoiser.gui import themes
    from stream_denoiser.logging_config import get_logger
    get_logger("test-poise-logs-colour").error("boom-colour")
    window._refresh_logs()
    doc = window.log_view.document()
    block = doc.findBlock(0)
    while block.isValid() and "boom-colour" not in block.text():
        block = block.next()
    assert block.isValid()
    colour = block.begin().fragment().charFormat().foreground().color()
    assert colour == QColor(themes.current()["error"])


def test_logs_copy_and_save_export_the_session(window, session_log, tmp_path,
                                               monkeypatch):
    from PyQt6.QtWidgets import QApplication, QFileDialog
    from stream_denoiser.logging_config import get_logger
    get_logger("test-poise-logs-export").warning("export-me")
    window._copy_logs()
    assert "export-me" in QApplication.clipboard().text()
    assert window.log_copy_btn.text() == "Copied"
    target = tmp_path / "poise-log.txt"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *a, **k: (str(target), ""))
    window._save_logs()
    assert "export-me" in target.read_text(encoding="utf-8")


def test_logs_folder_button_only_with_a_log_file(window, tmp_path):
    from stream_denoiser import logging_config
    logging_config._reset_file_logging_for_tests()
    try:
        window._update_log_source()
        assert window.log_folder_btn.isHidden()
        assert "not saved to disk" in window.log_path_label.text()
        logging_config.ensure_file_logging(log_file=tmp_path / "poise.log")
        window._update_log_source()
        assert not window.log_folder_btn.isHidden()
        assert window.log_path_label.text() == str(tmp_path / "poise.log")
    finally:
        logging_config._reset_file_logging_for_tests()
