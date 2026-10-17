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


def test_settings_are_isolated_from_the_users_config(window):
    from conftest import _TEST_CONFIG_HOME
    path = os.path.normcase(os.path.abspath(window.settings._settings.fileName()))
    assert path.startswith(os.path.normcase(os.path.abspath(_TEST_CONFIG_HOME)))


def test_dial_starts_at_the_saved_attenuation(window):
    assert window.power_btn.strength_db() == int(window.settings.atten_lim_db)


def test_legacy_attenuation_is_clamped_to_the_dial(window):
    window.settings.atten_lim_db = -72.0        # saved by an older build
    assert window._saved_atten_db() == -50


class _Host:
    """Stands in for the audio process (AudioHost): records live changes."""

    def __init__(self):
        self.sent = []

    def set(self, **values):
        self.sent.append(values)


def test_dial_changes_reach_the_audio_process(window):
    host = _Host()
    window.worker._host = host
    try:
        window.power_btn._user_set_strength(-17)
    finally:
        window.worker._host = None
    assert host.sent == [{"atten_lim_db": -17.0}]
    assert window.worker.atten_lim_db == -17.0


def test_threshold_changes_reach_the_audio_process(window):
    host = _Host()
    window.aad_switch.setChecked(True)
    window.worker._host = host
    try:
        window.thresh_slider.setValue(-52)
    finally:
        window.worker._host = None
    assert host.sent == [{"aad_threshold_db": -52.0}]
    assert window.worker.aad_threshold == -52.0
    assert float(window.settings.aad_threshold) == -52.0


def test_threshold_without_an_audio_process_is_only_stored(window):
    window.worker._host = None         # nothing started yet
    window.worker.set_aad_threshold(-45.0)
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


def test_threshold_follows_the_silence_switch(window):
    window.aad_switch.setChecked(False)
    assert not window.thresh_slider.isEnabled()
    window.aad_switch.setChecked(True)
    window.thresh_slider.setValue(-33)
    assert window.thresh_val_label.text() == "-33 dB"


def test_home_and_settings_model_pickers_stay_in_step(window):
    """Home's dropdown and Settings' cards show and save one choice."""
    usable = [m for m, c in window.model_cards._cards.items()
              if c.isEnabled()]
    assert window.model_selector.models() == usable
    assert window.model_selector.currentText() == window.model_cards.currentText()
    for model in usable:                     # Settings -> Home
        window.model_cards.setCurrentText(model)
        assert window.model_selector.currentText() == model
        assert window.settings.model == model
    for model in reversed(usable):           # Home -> Settings
        window.model_selector.setCurrentText(model)
        assert window.model_cards.currentText() == model
        assert window.settings.model == model


def test_controls_lock_while_running(window):
    output, model = window.output_selector, window.model_selector
    window._set_controls_enabled(False)
    assert output.is_locked and output._refresh_btn.isHidden()
    assert model.is_locked
    assert not window.model_cards.isEnabled()
    # Each card's caption says why.
    assert output._subtitle.text() == "Locked while running"
    assert model._subtitle.text() == "Locked while running"
    window._set_controls_enabled(True)
    assert not output.is_locked and not output._refresh_btn.isHidden()
    assert not model.is_locked
    assert window.model_cards.isEnabled()
    assert output._subtitle.text() == "Where the clean audio plays"
    assert model._subtitle.text() == model.CAPTION


@pytest.fixture()
def no_dwell(monkeypatch):
    """Status-bar steps show at once (wording, not pacing)."""
    from stream_denoiser.gui.widgets import stats_bar
    monkeypatch.setattr(stats_bar, "STEP_MIN_MS", 0)
    monkeypatch.setenv("POISE_NO_ANIM", "1")


def test_status_messages_drive_headline_and_status_bar(window, no_dwell):
    """Home keeps only the headline; the status bar tells each step in
    full. Errors also get a line under the headline."""
    from stream_denoiser.gui.main_window import HOME_TITLES
    bar = window.stats_bar
    window.update_status("Starting...")
    assert window.home_title.text() == HOME_TITLES["starting"]
    assert bar.status_shown == "starting…"
    assert window.status_label.isHidden()          # no status line
    window.update_status("Output: Speakers (Realtek(R) Audio)")
    assert window.home_title.text() == HOME_TITLES["starting"]
    assert bar.status_shown == "output: Speakers (Realtek(R) Audio)"
    window.update_status("Loading GTCRN...")
    assert bar.status_shown == "loading GTCRN…"
    window.update_status("Isolating audio")
    assert window.home_title.text() == HOME_TITLES["isolating"]
    assert bar.status_shown == "isolating"
    # The worker's loop says "Processing" after that; Home must stay put.
    window.update_status("Processing")
    assert window.home_title.text() == HOME_TITLES["isolating"]
    assert bar.status_shown == "isolating"
    window.update_status("Stopping...")
    assert window.home_title.text() == HOME_TITLES["stopping"]
    window.update_status("Restored playback to Speakers (Realtek(R) Audio)")
    assert window.home_title.text() == HOME_TITLES["stopping"]
    assert bar.status_shown.startswith("restored playback to Speakers")
    window.update_status("Error: boom")
    assert window.home_title.text() == HOME_TITLES["error"]
    assert window.status_label.text() == "boom"
    assert not window.status_label.isHidden()
    assert bar.status_shown == "error: boom"
    window.update_status("Ready")
    assert window.home_title.text() == HOME_TITLES["ready"]
    assert window.status_label.isHidden()
    assert bar.status_shown == "ready"


def test_the_error_stays_up_while_the_worker_cleans_up(window, no_dwell):
    """After a failed start the worker still says "Restored playback..."
    and "Stopped": the error must stay until the next start."""
    from stream_denoiser.gui.main_window import HOME_TITLES
    window._error_state = True
    window.update_status("Error: VB-CABLE: automatic switch failed.")
    window._on_worker_status("Restored playback to Speakers")
    window._on_worker_status("Stopped")
    assert window.home_title.text() == HOME_TITLES["error"]
    assert window.status_label.text() == (
        "VB-CABLE: automatic switch failed.")
    assert window.stats_bar.status_shown.startswith("error: VB-CABLE")
    window._error_state = False
    window._on_worker_status("Starting...")
    assert window.home_title.text() == HOME_TITLES["starting"]
    assert window.status_label.isHidden()


def test_clicking_the_status_opens_the_log(app, window):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    window._on_page_requested(0)
    area = window.stats_bar._status
    QTest.mouseClick(area, Qt.MouseButton.LeftButton,
                     pos=area.rect().center())
    _pump(app, 0.6)
    assert window.stack.currentIndex() == 2
    window._on_page_requested(0)
    _pump(app, 0.6)


def test_headline_changes_fade_and_coalesce(app, window, monkeypatch):
    """The headline fades between messages; a burst shows only the
    newest."""
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
    window.update_status("Isolating audio")      # arrives during the fade-out
    _pump(app, 0.5)
    assert window.home_title.text() == HOME_TITLES["isolating"]
    assert window.home_title.graphicsEffect() is None   # effect dropped


def test_home_only_keeps_the_everyday_controls(window):
    """Silence/tray controls live in Settings; Home has the dial and,
    under it, the output device and model cards."""
    from stream_denoiser.gui.widgets.slider import HoverSlider
    home = window.stack.widget(0)
    assert home.isAncestorOf(window.power_btn)
    assert home.isAncestorOf(window.output_selector)
    assert home.isAncestorOf(window.model_selector)
    assert window._home_layout.indexOf(window._stage) == 0
    cards = window._cards_layout
    assert cards.itemAt(0).widget().isAncestorOf(window.output_selector)
    assert cards.itemAt(1).widget().isAncestorOf(window.model_selector)
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


# -- Reset to defaults ----------------------------------------------------------------
def _move_everything_off_default(window):
    from stream_denoiser.gui import themes
    window.aad_switch.setChecked(False)
    window.thresh_slider.setValue(-63)
    window.min_tray_switch.setChecked(False)
    window.power_btn._user_set_strength(-18)
    other = next(i for i, t in enumerate(themes.theme_ids()) if t != "abyss")
    window.theme_group.button(other).setChecked(True)
    window._on_theme_changed(other)
    window.settings.output_device = 7
    return themes.theme_ids()[other]


def test_reset_restores_defaults_but_keeps_device_and_theme(window,
                                                           monkeypatch):
    from stream_denoiser.gui import themes
    monkeypatch.setenv("POISE_NO_ANIM", "1")
    s = window.settings
    picked = _move_everything_off_default(window)
    try:
        window.reset_to_defaults()
        assert window.aad_switch.isChecked() and s.aad_enabled is True
        assert window.thresh_slider.value() == -40 and s.aad_threshold == -40.0
        assert window.thresh_slider.isEnabled()
        assert window.min_tray_switch.isChecked() and s.minimize_to_tray
        # Default strength is the dial's strongest (ring full).
        assert window.power_btn.strength_db() == -50 and s.atten_lim_db == -50.0
        assert s.theme == picked and themes.current_id() == picked
        assert s.output_device == 7                 # hardware choice stays
    finally:
        s.output_device = None
        abyss = themes.theme_ids().index("abyss")
        window.theme_group.button(abyss).setChecked(True)
        window._on_theme_changed(abyss)


def test_fresh_install_starts_at_full_strength(window):
    from stream_denoiser.gui.widgets import dial
    s = window.settings
    s.remove(s.KEY_ATTEN_LIM_DB)
    assert s.atten_lim_db == float(dial.ATTEN_STRONG)
    assert window._saved_atten_db() == dial.ATTEN_STRONG
    assert dial.DialButton().strength_db() == dial.ATTEN_STRONG


def test_reset_asks_first(window, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setenv("POISE_NO_ANIM", "1")
    window.thresh_slider.setValue(-63)
    answer = QMessageBox.StandardButton.No
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: answer)
    window.reset_btn.click()
    assert window.thresh_slider.value() == -63      # declined: untouched
    answer = QMessageBox.StandardButton.Yes
    window.reset_btn.click()
    assert window.thresh_slider.value() == -40


def test_reset_is_locked_while_running(window, monkeypatch):
    monkeypatch.setattr(window, "tray", None)
    window._on_worker_started()
    assert not window.reset_btn.isEnabled()
    assert window._reset_row._sub.text() == "Locked while running"
    window._on_worker_stopped()
    assert window.reset_btn.isEnabled()
