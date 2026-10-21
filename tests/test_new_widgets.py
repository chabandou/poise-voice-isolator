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


def test_stats_hint_only_while_idle(app):
    """"stats appear when running" is noise beside a step or an error."""
    from stream_denoiser.gui.widgets.stats_bar import StatsBar
    bar = StatsBar()
    bar.show()
    _pump(app)
    assert bar._hint.isVisible()
    bar.set_state("processing", "loading GTCRN…")
    assert not bar._hint.isVisible()
    bar.set_state("error", "error: boom")
    bar.reset()                         # the worker stopped after the error
    assert not bar._hint.isVisible()
    bar.set_state("ready")
    assert bar._hint.isVisible()
    bar.close()


def test_long_status_is_cut_short_with_the_full_text_on_hover(app):
    from stream_denoiser.gui.widgets.stats_bar import LOG_HINT, StatsBar
    bar = StatsBar()
    long = "Error: " + "VB-CABLE: default playback is still somewhere " * 4
    bar.show_status("error", long)
    _pump(app, 0.4)
    assert bar._state.text().endswith("…")
    assert len(bar._state.text()) < len(bar.status_shown)
    assert bar.status_shown in bar._status.toolTip()
    assert LOG_HINT in bar._status.toolTip()
    bar.close()


def test_stats_bar_skip_is_live_and_hidden_without_aad(app):
    from stream_denoiser.gui.widgets.stats_bar import StatsBar
    bar = StatsBar()
    bar.show()
    bar.update_stats(STATS)
    _pump(app)
    assert bar._pairs["skip"].isVisible() and bar._values["skip"].text() == "on"
    bar.update_stats(dict(STATS, aad_bypass_active=False))   # audio arrived
    assert bar._values["skip"].text() == "off"
    no_aad = {k: v for k, v in STATS.items() if not k.startswith("aad_")}
    bar.update_stats(no_aad)                                   # skipping disabled
    _pump(app)
    assert not bar._pairs["skip"].isVisible()
    bar.reset()
    bar.update_stats(STATS)
    _pump(app)
    assert bar._pairs["skip"].isVisible()
    bar.close()


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


def test_settings_row_click_does_nothing_without_a_toggle(app):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QPushButton
    from stream_denoiser.gui.widgets.settings_row import SettingsRow
    from PyQt6.QtWidgets import QWidget
    host = QWidget()
    button = QPushButton("Reset")
    clicks = []
    button.clicked.connect(lambda: clicks.append(1))
    row = SettingsRow("Title", "caption", button, parent=host)
    row.resize(900, 78)
    host.show()
    _pump(app)
    assert row.toggle is None
    assert not row.testAttribute(Qt.WidgetAttribute.WA_SetCursor)
    _row_click(row, 60, 30)
    assert clicks == []
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


def _lit_row_image(app, first, last):
    from PyQt6.QtWidgets import QPushButton
    from stream_denoiser.gui.widgets.settings_row import SettingsRow
    row = SettingsRow("Title", "caption", QPushButton("x"))
    row.set_position(first, last)
    row.resize(900, 78)
    row.show()
    _pump(app)
    row._hover = False
    row._lit_blend.snap(0.0)          # the wash is eased; jump to the ends
    unlit = row.grab().toImage()
    row._hover = True
    row._lit_blend.snap(1.0)
    lit = row.grab().toImage()
    row.close()
    return unlit, lit


@pytest.mark.parametrize("first,last", [(True, False), (False, False),
                                        (False, True), (True, True)])
def test_row_highlight_covers_the_whole_row_height(app, first, last):
    """Regression: an odd-even clip path left the overlap of the rounded
    rect and the squaring rects unpainted, so rows lit only part-way."""
    unlit, lit = _lit_row_image(app, first, last)
    x = 120
    for y in (12, 39, 66):                       # top, middle, bottom
        assert lit.pixelColor(x, y) != unlit.pixelColor(x, y), (
            first, last, y)


def test_row_highlight_grows_while_it_fades_in(app):
    """The wash fades in as its front travels from part-way across to its
    full reach (never wiping on from nothing), and back on the way out."""
    from PyQt6.QtWidgets import QPushButton
    from stream_denoiser.gui.widgets import settings_row as sr
    row = sr.SettingsRow("Title", "caption", QPushButton("x"))
    row.set_position(True, True)
    row.resize(900, 78)
    row.show()
    _pump(app)
    row._hover = False
    reach = 900 * sr.WASH_REACH
    assert 0.25 <= sr.WASH_FROM <= 0.6
    assert row.wash_front(0.0) == pytest.approx(reach * sr.WASH_FROM)
    assert row.wash_front(1.0) == pytest.approx(reach)
    assert row.wash_front(0.3) < row.wash_front(0.6) < row.wash_front(1.0)

    def at(value):
        row._lit_blend.snap(value)
        return row.grab().toImage()

    unlit, low, half, full = at(0.0), at(0.25), at(0.5), at(1.0)
    row.close()
    y = 72                                      # below the text

    def glow(img, x):
        c, base = img.pixelColor(x, y), unlit.pixelColor(x, y)
        return (abs(c.red() - base.red()) + abs(c.green() - base.green())
                + abs(c.blue() - base.blue()))

    # Fades in: the left edge brightens steadily with the light level.
    assert 0 < glow(low, 20) < glow(half, 20) < glow(full, 20)
    # Grows: just short of full reach is dark at a low level, lit at full.
    past = int(row.wash_front(0.25)) + 20
    assert glow(low, past) == 0 and glow(full, past) > 0
    # Nothing beyond the reach, even fully lit.
    assert glow(full, int(reach) + 10) == 0


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


def test_toggle_is_a_rounded_square_outline_with_an_accent_knob(app):
    """Off: quiet outline + muted knob on the left. On: accent outline,
    faint accent wash and an accent knob on the right."""
    from PyQt6.QtGui import QColor
    from stream_denoiser.gui import themes
    from stream_denoiser.gui.widgets.switch import ToggleSwitch
    themes.set_current("halcyon")
    accent = QColor(themes.current()["accent"])
    off = ToggleSwitch(checked=False)
    on = ToggleSwitch(checked=True)
    for sw in (off, on):
        sw.show()
    _pump(app)
    assert (on.width(), on.height()) == (off.width(), off.height())
    w, h = off.width(), off.height()
    left, right = h // 2, w - h // 2
    img_off, img_on = off.grab().toImage(), on.grab().toImage()

    def near(c, ref, tol=6):
        return (abs(c.red() - ref.red()) <= tol
                and abs(c.green() - ref.green()) <= tol
                and abs(c.blue() - ref.blue()) <= tol)

    # On: knob right, filled with the accent; left side is only wash.
    assert near(img_on.pixelColor(right, h // 2), accent)
    assert not near(img_on.pixelColor(left, h // 2), accent)
    # Off: knob left and NOT accent coloured.
    assert not near(img_off.pixelColor(left, h // 2), accent)
    assert not near(img_off.pixelColor(right, h // 2), accent)
    # Square-ish track: the outer corner pixel is not painted.
    assert img_on.pixelColor(0, 0).alpha() == 0 or \
        img_on.pixelColor(0, 0) != img_on.pixelColor(w // 2, h // 2)
    off.close()
    on.close()


def test_disabled_toggle_greys_out_and_drops_the_hand_cursor(app):
    """Locked while running: an 'on' switch must not keep its accent knob."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QColor
    from stream_denoiser.gui import themes
    from stream_denoiser.gui.widgets.switch import ToggleSwitch
    themes.set_current("halcyon")
    accent = QColor(themes.current()["accent"])
    sw = ToggleSwitch(checked=True)
    sw.show()
    _pump(app)
    h, right = sw.height(), sw.width() - sw.height() // 2
    assert sw.grab().toImage().pixelColor(right, h // 2) == accent
    sw.setEnabled(False)
    _pump(app)
    knob = sw.grab().toImage().pixelColor(right, h // 2)
    assert abs(knob.blue() - accent.blue()) > 30 or \
        abs(knob.green() - accent.green()) > 30, knob.name()
    assert sw.cursor().shape() == Qt.CursorShape.ArrowCursor
    sw.setEnabled(True)
    assert sw.cursor().shape() != Qt.CursorShape.ArrowCursor
    sw.close()


def test_toggle_knob_springs_past_the_end_and_settles(app):
    """The slide's bounce: position is unclamped (overshoots), but the
    colour blend stays clamped so it never flashes."""
    from stream_denoiser.gui.widgets.switch import ToggleSwitch
    sw = ToggleSwitch(checked=True)
    sw.show()
    _pump(app)
    rest_x, side = sw.knob_geometry()
    sw._knob = 1.1                     # OutBack overshoot
    over_x, _ = sw.knob_geometry()
    assert over_x > rest_x
    assert over_x + side < sw.width()  # still inside the track
    sw._knob = 0.0
    start_x, _ = sw.knob_geometry()
    sw._knob = -0.1                    # and past the start on the way back
    assert sw.knob_geometry()[0] < start_x
    sw.grab()                          # paints without error at overshoot
    sw.close()


def test_power_button_hover_lights_the_head_needle_like_the_ring(app):
    from PyQt6.QtCore import QPoint
    btn = _dial(app)
    k = btn.width() / 300.0
    centre = QPoint(btn.width() // 2, btn.height() // 2)
    ring = QPoint(int(btn.width() / 2 + 125 * k), btn.height() // 2)
    corner = QPoint(1, 1)
    btn._update_hover_cursor(centre)
    assert btn._hot is True
    btn._update_hover_cursor(ring)
    assert btn._hot is True
    btn._update_hover_cursor(corner)
    assert btn._hot is False
    btn.close()


def _dial(app):
    from stream_denoiser.gui.widgets.dial import DialButton
    btn = DialButton()
    btn.show()
    _pump(app)
    return btn


def test_rescan_arrow_follows_the_secondary_colour(app):
    from stream_denoiser.gui import themes
    from stream_denoiser.gui.widgets.device_selector import DeviceSelector
    themes.set_current("halcyon")
    sel = DeviceSelector("Output device", "output")
    assert sel._refresh_icon._color == themes.current()["secondary"]
    themes.set_current("ember")
    sel.refresh_theme()
    assert sel._refresh_icon._color == themes.current()["secondary"]
    themes.set_current("halcyon")


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


def test_donate_button_is_filled_with_a_hover_ring(app, monkeypatch):
    """Idle: secondary fill + dark label. Hover: a text-colour ring set off
    from the fill by a gap (not a colour swap)."""
    import re
    from PyQt6.QtGui import QColor
    from stream_denoiser.gui import main_window as mw
    from stream_denoiser.gui import themes
    from stream_denoiser.gui.scaling import sp
    from stream_denoiser.gui.widgets.donate_button import (
        DonateButton, RING_GAP, RING_WIDTH)
    monkeypatch.setattr(mw, "DONATE_URL", "https://example.org/donate")
    themes.set_current("halcyon")
    window = mw.MainWindow()
    window.show()
    _pump(app)
    btn = window.donate_btn
    assert isinstance(btn, DonateButton) and not btn.isHidden()
    assert btn.text() == "Donate" and btn.objectName() == "donate"
    pal = themes.current()

    css = window.styleSheet().lower()
    block = re.search(r"qpushbutton#donate\s*\{([^}]*)\}", css).group(1)
    assert "background-color: transparent" in block        # fill is painted
    assert re.search(rf"[^-]color: {pal['bg'].lower()}", block)   # dark label
    assert (btn, "heart", "bg") in window._icon_buttons    # dark heart

    btn.resize(btn.sizeHint())
    inset = sp(RING_WIDTH + RING_GAP)
    fill = QColor(pal["secondary"])
    ring = QColor(pal["text"])

    def close(c, ref, tol=4):
        return (abs(c.red() - ref.red()) <= tol
                and abs(c.green() - ref.green()) <= tol
                and abs(c.blue() - ref.blue()) <= tol)

    btn._ring.snap(0.0)
    idle = btn.grab().toImage()
    assert close(idle.pixelColor(inset + 4, btn.height() // 2), fill)
    assert idle.pixelColor(btn.width() // 2, 0).alpha() == 0     # no ring
    btn._ring.snap(1.0)
    hot = btn.grab().toImage()
    assert close(hot.pixelColor(inset + 4, btn.height() // 2), fill)
    assert close(hot.pixelColor(btn.width() // 2, 0), ring)       # the ring
    gap = hot.pixelColor(btn.width() // 2, sp(RING_WIDTH) + 1)    # the gap
    assert gap.alpha() == 0

    opened = []
    monkeypatch.setattr(mw.QDesktopServices, "openUrl",
                        staticmethod(lambda url: opened.append(url.toString())))
    btn.click()
    assert opened == ["https://example.org/donate"]
    window.close()


def test_donate_ring_eases_in_and_out(app):
    from stream_denoiser.gui.widgets.donate_button import DonateButton
    btn = DonateButton("Donate")
    btn.show()
    _pump(app, 0.1)
    _leave(btn)                                  # offscreen pointer at (0, 0)
    _pump(app, 0.3)
    _enter(btn)
    assert btn._ring.target == 1.0 and btn._ring.running
    _pump(app, 0.4)
    assert btn._ring.value == pytest.approx(1.0)
    _leave(btn)
    assert btn._ring.target == 0.0
    btn.close()


def _enter(widget):
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QEnterEvent
    pt = QPointF(3, 3)
    widget.enterEvent(QEnterEvent(pt, pt, pt))


def _leave(widget):
    from PyQt6.QtCore import QEvent
    widget.leaveEvent(QEvent(QEvent.Type.Leave))


# -- D motion: lattice pings, icon motion, locked combos, status halo ----------
@pytest.fixture
def motion(monkeypatch):
    monkeypatch.delenv("POISE_NO_ANIM", raising=False)
    monkeypatch.delenv("POISE_REDUCE_MOTION", raising=False)


def test_pattern_card_pings_from_its_origin_until_stopped(app, motion):
    from PyQt6.QtWidgets import QVBoxLayout, QWidget
    from stream_denoiser.gui.widgets.pattern_card import PatternCard
    card = PatternCard()
    card.resize(600, 400)
    origin = QWidget()
    origin.setFixedSize(100, 100)
    QVBoxLayout(card).addWidget(origin)
    card.set_ping_origin(origin)
    card.show()
    _pump(app, 0.05)
    card.set_live(True)
    card.start_pings()
    assert card._ping_frame() is not None
    assert card._ping_centre() is not None
    card.grab()                                   # paints the ring
    card.set_live(False, animated=False)          # no fade: gone at once
    assert card._ping_at is None and card._ping_frame() is None
    card.close()


def _ping_card(app):
    from PyQt6.QtWidgets import QVBoxLayout, QWidget
    from stream_denoiser.gui.widgets.pattern_card import PatternCard
    card = PatternCard()
    card.resize(600, 400)
    origin = QWidget()
    origin.setFixedSize(100, 100)
    QVBoxLayout(card).addWidget(origin)
    card.set_ping_origin(origin)
    card.show()
    _pump(app, 0.05)
    card.set_live(True)
    card.start_pings()
    return card


def test_stopping_fades_the_ring_out(app, motion):
    """Stop mid-ring: the ring fades away (it used to vanish in a frame)
    and the card sends no more."""
    from stream_denoiser.gui.widgets.pattern_card import PING_FADE_MS
    card = _ping_card(app)
    _pump(app, 0.15)
    _, before = card._ping_frame()
    card.stop_pings()
    assert not card.pinging                       # nothing more scheduled
    assert card._ping_frame() is not None         # ...but the ring lingers
    _pump(app, PING_FADE_MS / 2000)
    _, mid = card._ping_frame()
    assert 0 < mid < before
    _pump(app, PING_FADE_MS / 1000)
    assert card._ping_frame() is None and card._ping_at is None
    card.close()


def test_no_ring_goes_out_after_stop(app, motion):
    """Stop between rings (e.g. the app is still stopping when the next
    one is due): no ring goes out."""
    import time
    from stream_denoiser.gui.widgets import pattern_card as pc
    card = _ping_card(app)
    # Just before the second ring is due; nothing on screen.
    card._ping_at = time.perf_counter() - (pc.PING_PERIOD_MS - 60) / 1000
    assert card._ping_frame() is None
    card.stop_pings()
    assert card._ping_at is None
    _pump(app, 0.2)
    assert card._ping_frame() is None
    # The same with a fading ring on screen when the next is due.
    card.start_pings()
    card.stop_pings()
    card._ping_at -= pc.PING_PERIOD_MS / 1000     # next ring "now"
    card._ping_end -= pc.PING_PERIOD_MS / 1000 - 0.05
    assert card._ping_frame() is None
    card.close()


def test_stopping_mid_charge_fades_the_dial_glow(app, motion):
    """The dial charges before each later ping. Stop mid-charge: the glow
    fades out instead of cutting off, and no new charge starts."""
    import time
    from stream_denoiser.gui.widgets import dial as d
    dial = d.DialButton()
    dial.show()
    _pump(app, 0.05)
    dial.set_active(True)
    assert dial.phase() == "live"
    # Put the live phase half-way into the first charge.
    t = dial._ignite_end() + d.PING_PERIOD_MS - d.CHARGE_LEAD_MS / 2
    dial._phase_at = time.perf_counter() - t / 1000
    charge = dial._charge(dial._ms())
    assert charge > 0.1
    dial._on_clicked()                            # Stop pressed...
    dial.set_transitioning(True)                  # ...and stopping
    assert dial.phase() == "stopping"
    assert dial._charge(dial._ms()) == pytest.approx(charge, abs=0.05)
    _pump(app, d.CHARGE_DROP_MS / 2000)
    assert 0 < dial._charge(dial._ms()) < charge
    _pump(app, d.CHARGE_DROP_MS / 1000)
    assert dial._charge(dial._ms()) == 0.0
    # Still stopping a ping period later: no new charge.
    dial._phase_at -= d.PING_PERIOD_MS / 1000
    assert dial._charge(dial._ms()) == 0.0
    dial.close()


def test_pattern_card_pings_stay_off_under_reduced_motion(app, monkeypatch):
    monkeypatch.setenv("POISE_NO_ANIM", "1")
    from stream_denoiser.gui.widgets.pattern_card import PatternCard
    card = PatternCard()
    card.start_pings()
    assert card._ping_at is None


def test_motion_icon_plays_then_rests_and_the_gear_turns(app, motion):
    from stream_denoiser.gui.widgets.phosphor import MotionIcon
    bars = MotionIcon("waveform", size=20)
    bars.show()
    bars.play()
    assert bars._moving_ms() is not None
    bars.grab()                                   # paints the parts
    _pump(app, 1.0)
    assert bars._moving_ms() is None
    gear = MotionIcon("gear", size=20)
    gear.show()
    gear.hover(True)
    _pump(app, 0.8)
    assert gear._angle == pytest.approx(60.0, abs=0.5)
    gear.hover(False)
    _pump(app, 0.8)
    assert gear._angle == pytest.approx(0.0, abs=0.5)
    bars.close()
    gear.close()


def test_locked_combo_click_jiggles_and_flashes_the_caption(app, motion):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from stream_denoiser.gui.widgets.model_selector import ModelSelector
    selector = ModelSelector()
    selector.resize(420, 140)
    selector.show()
    _pump(app, 0.1)
    selector.set_locked(True)
    _pump(app, 0.4)
    assert selector._combo._lock.value == pytest.approx(1.0)
    QTest.mouseClick(selector, Qt.MouseButton.LeftButton,
                     pos=selector._combo.geometry().center())
    assert selector._combo._jiggle_ms() is not None
    assert "color" in selector._subtitle.styleSheet()
    _pump(app, 1.7)
    assert selector._subtitle.styleSheet() == ""     # back to its own colour
    selector.set_locked(False)
    _pump(app, 0.4)
    assert selector._combo._lock.value == pytest.approx(0.0)
    selector.close()


def test_status_halo_runs_only_while_isolating(app, motion):
    from stream_denoiser.gui.widgets.stats_bar import StatsBar
    bar = StatsBar()
    bar.show()
    bar.set_state("processing", "loading GTCRN…")
    assert bar._halo_at is None
    bar.set_state("processing")                   # "isolating"
    assert bar._halo_at is not None and bar._halo.isActive()
    bar.grab()
    bar.set_state("ready")
    assert bar._halo_at is None and not bar._halo.isActive()
    bar.close()


def test_an_entrance_pictures_its_widget_once(app, monkeypatch):
    """A rising widget is painted once and its picture moved, not
    painted again every frame; it is live again once it lands."""
    monkeypatch.delenv("POISE_NO_ANIM", raising=False)
    monkeypatch.delenv("POISE_REDUCE_MOTION", raising=False)
    from PyQt6.QtWidgets import QWidget, QFrame
    from stream_denoiser.gui import animations

    class Counted(QFrame):
        paints = 0

        def paintEvent(self, event):  # noqa: N802
            Counted.paints += 1
            super().paintEvent(event)

    host = QWidget()
    host.resize(200, 200)
    card = Counted(host)
    card.setGeometry(20, 20, 120, 120)
    animations.hold_hidden(card, rise=14)
    host.show()
    _pump(app, 0.05)
    assert Counted.paints == 0                 # hidden: not painted at all
    animations.rise_in(card, duration_ms=300, rise=14)
    _pump(app, 0.15)
    assert card.graphicsEffect() is not None   # mid-rise
    assert Counted.paints <= 2                 # pictured, then moved
    _pump(app, 0.4)
    assert card.graphicsEffect() is None       # landed: live again
    host.close()
