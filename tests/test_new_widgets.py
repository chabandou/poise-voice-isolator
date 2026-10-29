"""Status-bar stats, model cards, settings rows, the setup summary and
the first-launch notice."""
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
         "aad_bypass_active": True, "input_buffer": 2, "output_buffer": 2}


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
    assert bar._values["skip"].text() == "on"
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
    assert bar._state.text() == "ready"
    bar.set_state("processing", "loading GTCRN…")
    assert bar._dot.property("state") == "processing"
    assert bar._state.text() == "loading GTCRN…"
    bar.set_state("processing")
    assert bar._state.text() == "isolating"
    bar.set_state("error")
    assert bar._state.text() == "error"
    assert bar._state.property("state") == "error"   # red text


@pytest.mark.parametrize("state,message,text", [
    ("ready", "Ready", "ready"),
    ("ready", "Stopped", "ready"),
    ("error", "Error: boom", "error: boom"),
    ("error", "Error: boom\nTraceback (most recent call last):", "error: boom"),
    ("processing", "Initializing...", "initializing…"),
    ("processing", "Starting...", "starting…"),
    ("processing", "Loading GTCRN...", "loading GTCRN…"),
    ("processing", "Output: Speakers (Realtek(R) Audio)",
     "output: Speakers (Realtek(R) Audio)"),
    ("processing", "Switching audio device...", "switching audio device…"),
    ("processing", "Switched to VB-Cable (CABLE Input)",
     "switched to VB-Cable (CABLE Input)"),
    ("processing", "Installing AudioDeviceCmdlets... First time may take a "
     "few seconds...", "installing AudioDeviceCmdlets… First time may "
     "take a few seconds…"),
    ("processing", "VB-CABLE: odd", "VB-CABLE: odd"),     # acronym kept
    ("processing", "Isolating audio", "isolating"),
    ("processing", "Processing", "isolating"),
    ("processing", "Stopping...", "stopping…"),
    ("processing", "Restored playback to Speakers",
     "restored playback to Speakers"),
])
def test_status_text_tells_the_step_in_full(state, message, text):
    from stream_denoiser.gui.widgets.stats_bar import status_text
    assert status_text(state, message) == text


def test_quick_steps_stay_up_long_enough_to_read(app):
    """Each step is up at least STEP_MIN_MS; later ones queue behind it.
    An error doesn't wait (and drops what's queued)."""
    from stream_denoiser.gui.widgets import stats_bar
    bar = stats_bar.StatsBar()
    bar.show_status("processing", "Switching audio device...")
    bar.show_status("processing", "Loading GTCRN...")
    bar.show_status("processing", "Isolating audio")
    assert bar.status_shown == "switching audio device…"
    _pump(app, stats_bar.STEP_MIN_MS / 1000.0 + 0.15)
    assert bar.status_shown == "loading GTCRN…"
    _pump(app, stats_bar.STEP_MIN_MS / 1000.0 + 0.15)
    assert bar.status_shown == "isolating"
    bar.show_status("processing", "Stopping...")
    bar.show_status("ready", "Ready")
    bar.show_status("error", "Error: boom")
    assert bar.status_shown == "error: boom" and not bar._queue
    bar.close()


def _row_click(row, x, y, release_at=None):
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    from PyQt6.QtCore import QEvent
    left, none = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    for kind, pt in ((QEvent.Type.MouseButtonPress, (x, y)),
                     (QEvent.Type.MouseButtonRelease, release_at or (x, y))):
        pos = QPointF(*pt)
        event = QMouseEvent(kind, pos, row.mapToGlobal(pos), left,
                            left if kind == QEvent.Type.MouseButtonPress
                            else Qt.MouseButton.NoButton, none)
        if kind == QEvent.Type.MouseButtonPress:
            row.mousePressEvent(event)
        else:
            row.mouseReleaseEvent(event)


def test_settings_row_toggles_from_anywhere(app):
    from stream_denoiser.gui.widgets.settings_row import SettingsRow
    from stream_denoiser.gui.widgets.switch import ToggleSwitch
    from PyQt6.QtWidgets import QWidget
    host = QWidget()        # a child row (a window keeps its cursor flag)
    switch = ToggleSwitch(checked=False)
    flips = []
    switch.toggled.connect(flips.append)
    row = SettingsRow("Title", "caption", switch, parent=host)
    row.resize(900, 78)
    host.resize(900, 78)
    host.show()
    _pump(app)
    assert row.toggle is switch
    _row_click(row, 60, 30)                       # on the title
    assert switch.isChecked() and flips == [True]
    _row_click(row, 450, 70)                      # empty middle of the row
    assert not switch.isChecked() and flips == [True, False]
    # Pressed on the row but let go off it: nothing (like a button).
    _row_click(row, 60, 30, release_at=(60, 200))
    assert flips == [True, False]
    # A real click on the title/subtitle labels reaches the row.
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    QTest.mouseClick(row._title, Qt.MouseButton.LeftButton)
    QTest.mouseClick(row._sub, Qt.MouseButton.LeftButton)
    assert flips == [True, False, True, False]
    # Clicking the switch itself flips it once (not again via the row).
    QTest.mouseClick(switch, Qt.MouseButton.LeftButton)
    assert flips == [True, False, True, False, True]
    flips[:] = [True, False]
    switch.blockSignals(True)
    switch.setChecked(False)
    switch.blockSignals(False)
    # Locked: the row does nothing and loses the hand cursor.
    row.set_locked(True)
    assert not row.testAttribute(Qt.WidgetAttribute.WA_SetCursor)
    _row_click(row, 60, 30)
    assert flips == [True, False]
    row.set_locked(False)
    assert row.testAttribute(Qt.WidgetAttribute.WA_SetCursor)
    _row_click(row, 60, 30)
    assert flips == [True, False, True]
    host.close()


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


def test_model_selector_surface_and_lock(app):
    from stream_denoiser.gui.widgets.model_selector import ModelSelector
    selector = ModelSelector()
    picked = []
    selector.currentTextChanged.connect(picked.append)
    models = selector.models()
    assert models
    # The open list shows each engine's Settings blurb under its name.
    from stream_denoiser.constants import MODEL_INFO
    from stream_denoiser.gui.widgets.combo import BLURB_ROLE
    for row, model in enumerate(models):
        assert selector._combo.itemData(row, BLURB_ROLE) == (
            MODEL_INFO[model].get("card_blurb")
            or MODEL_INFO[model].get("picker_blurb", ""))
    selector.setCurrentText(models[-1])
    assert selector.currentText() == models[-1]
    selector.setCurrentText("no-such-model")        # ignored
    assert selector.currentText() == models[-1]
    if len(models) > 1:
        assert picked == [models[-1]]
    selector.set_locked(True)
    assert selector.is_locked
    assert selector._subtitle.text() == "Locked while running"
    selector.set_locked(False)
    assert not selector.is_locked
    assert selector._subtitle.text() == selector.CAPTION


def test_install_button_reaches_the_bundled_installer(app, monkeypatch):
    """Regression: the dialog imported a module path that does not exist,
    so Install VB-Cable always fell back to the website."""
    import stream_denoiser.backends.platform.windows as win
    from stream_denoiser.gui.widgets import vb_cable_dialog as dlg

    calls = []
    monkeypatch.setattr(win, "is_vbcable_installed", lambda: bool(calls))
    monkeypatch.setattr(win, "find_bundled_vbcable_setup",
                        lambda *a, **k: "C:/setup.exe")
    monkeypatch.setattr(win, "install_vbcable_driver",
                        lambda *a, **k: calls.append("install") or 0)
    monkeypatch.setattr(dlg.QMessageBox, "information",
                        staticmethod(lambda *a, **k: None))
    opened = []
    monkeypatch.setattr(dlg, "_open_cable_website",
                        lambda: opened.append(True))

    class Button:
        def setEnabled(self, _):
            pass

    dlg._on_install_vb_cable(None, Button())
    assert calls == ["install"]
    assert opened == []


def test_install_button_falls_back_to_website_without_a_bundled_setup(
        app, monkeypatch):
    import stream_denoiser.backends.platform.windows as win
    from stream_denoiser.gui.widgets import vb_cable_dialog as dlg

    monkeypatch.setattr(win, "is_vbcable_installed", lambda: False)
    monkeypatch.setattr(win, "find_bundled_vbcable_setup",
                        lambda *a, **k: None)
    opened = []
    monkeypatch.setattr(dlg, "_open_cable_website",
                        lambda: opened.append(True))
    dlg._on_install_vb_cable(None, object())
    assert opened == [True]


def test_about_credits_vb_audio_with_an_embedded_link(app, monkeypatch):
    """VB-CABLE is third-party donationware: credit it, and link VB-Audio's
    name in place (with an external-link arrow), not as a separate button."""
    from PyQt6.QtWidgets import QPushButton
    from stream_denoiser.gui import main_window as mw
    window = mw.MainWindow()
    window.show()
    _pump(app)
    label = window.about_credits
    html = label.text()
    assert f'href="{mw.VB_AUDIO_URL}"' in html
    assert "VB-Audio Software \u2197" in html          # name + arrow
    assert "VB-CABLE by" in html and "donationware" in html
    assert not any(b.text() == "VB-Audio"
                   for b in window.findChildren(QPushButton))
    opened = []
    monkeypatch.setattr(mw.QDesktopServices, "openUrl",
                        staticmethod(lambda url: opened.append(url.toString())))
    label.linkActivated.emit(mw.VB_AUDIO_URL)
    assert opened == ["https://vb-audio.com/"]
    # Underlines on hover only, and follows the theme accent.
    assert "text-decoration:none" in html
    label.linkHovered.emit(mw.VB_AUDIO_URL)
    assert "text-decoration:underline" in label.text()
    label.linkHovered.emit("")
    assert "text-decoration:none" in label.text()
    window.close()


def test_donate_button_is_hidden_until_a_url_is_set(app):
    from stream_denoiser.gui import main_window as mw
    assert mw.DONATE_URL == "" or mw.DONATE_URL.startswith("https://")
    window = mw.MainWindow()
    assert window.donate_btn.isHidden() == (not mw.DONATE_URL)
    window.close()


def test_pattern_card_pings_stay_off_under_reduced_motion(app, monkeypatch):
    monkeypatch.setenv("POISE_NO_ANIM", "1")
    from stream_denoiser.gui.widgets.pattern_card import PatternCard
    card = PatternCard()
    card.start_pings()
    assert card._ping_at is None


def test_notice_covers_its_host_and_closes(app):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QWidget
    from stream_denoiser.gui.widgets.notice import NoticeOverlay
    host = QWidget()
    host.resize(900, 600)
    host.show()
    notice = NoticeOverlay(host, "Title", "Some long body text " * 8)
    notice.open()
    _pump(app)
    assert notice.geometry() == host.rect()
    host.resize(1000, 700)
    _pump(app)
    assert notice.geometry() == host.rect()       # follows the window
    QTest.keyClick(notice.button, Qt.Key.Key_Escape)
    _pump(app, 0.5)
    assert not host.findChildren(NoticeOverlay)
    host.close()
