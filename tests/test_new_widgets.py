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
    themes.set_current("abyss")
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
    themes.set_current("abyss")
    sel = DeviceSelector("Output device", "output")
    assert sel._refresh_icon._color == themes.current()["secondary"]
    themes.set_current("ember")
    sel.refresh_theme()
    assert sel._refresh_icon._color == themes.current()["secondary"]
    themes.set_current("abyss")


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
    themes.set_current("abyss")
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
