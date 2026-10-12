"""Dropdown popup behavior (needs Qt; skipped without it)."""
import os
import time

import pytest

pytest.importorskip("PyQt6.QtWidgets")


@pytest.fixture(scope="module")
def app():
    # Forced offscreen: deterministic grabs, no HiDPI disentangling.
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_combo(items=("deepfilternet3", "rnnoise")):
    from PyQt6.QtCore import Qt
    from stream_denoiser.gui import themes
    from stream_denoiser.gui.styles import get_stylesheet
    from stream_denoiser.gui.widgets.combo import AnimatedComboBox
    themes.set_current("abyss")
    combo = AnimatedComboBox()
    combo.setObjectName("settings-combo")
    combo.addItems(list(items))
    combo.setStyleSheet(get_stylesheet(theme="abyss"))
    combo.resize(400, 40)
    combo.show()
    return combo


def _pump(app, secs=0.4):
    end = time.time() + secs
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def test_popup_container_carries_own_card_sheet(app):
    """Top-level popup gets its own sheet (cascade never reaches it):
    card colour, hairline border, rounded corners; the pill palette stays
    as the fallback fill where translucency is unavailable."""
    from PyQt6.QtGui import QPalette
    from stream_denoiser.gui import themes
    combo = _make_combo()
    _pump(app, 0.2)
    combo.showPopup()
    _pump(app, 0.2)
    win = combo.view().window()
    sheet = win.styleSheet().lower()
    assert themes.current()["card"].lower() in sheet
    assert "border-radius" in sheet and "border: 1px solid" in sheet
    assert (win.palette().color(QPalette.ColorRole.Window).name()
            == themes.current()["pill"].lower())
    assert not win.autoFillBackground()   # corners stay see-through
    combo.hidePopup()
    _pump(app, 0.2)
    assert not win.isVisible()
    combo.close()


def test_delegate_sizes_rows_to_a_fixed_height(app):
    """Rows are airy and exactly ROW_H tall (the popup is sized from it)."""
    from stream_denoiser.gui.scaling import sp
    from stream_denoiser.gui.widgets.combo import PopupItemDelegate
    combo = _make_combo()
    _pump(app, 0.2)
    combo.showPopup()
    _pump(app, 0.2)
    view = combo.view()
    assert isinstance(view.itemDelegate(), PopupItemDelegate)
    for row in range(combo.count()):
        assert view.sizeHintForRow(row) == sp(PopupItemDelegate.ROW_H)
    combo.hidePopup()
    _pump(app, 0.2)
    combo.close()


def test_selection_api_unchanged(app):
    combo = _make_combo()
    combo.setCurrentIndex(1)
    assert combo.currentText() == "rnnoise"
    combo.close()


def test_popup_opens_directly_below_button(app):
    """Menu-style placement: popup hangs under the button, not over it."""
    from stream_denoiser.gui.widgets.combo import POPUP_GAP
    combo = _make_combo()
    _pump(app, 0.2)
    combo.showPopup()
    _pump(app, 0.2)
    win = combo.view().window()
    combo_bottom = combo.mapToGlobal(combo.rect().bottomLeft()).y()
    assert win.y() == combo_bottom + 1 + POPUP_GAP
    combo.hidePopup()
    _pump(app, 0.2)
    combo.close()


def test_popup_flips_above_when_no_room(app):
    """Near the screen bottom the popup hangs above instead."""
    from PyQt6.QtWidgets import QApplication
    from stream_denoiser.gui.widgets.combo import POPUP_GAP
    screen = QApplication.primaryScreen()
    avail = screen.availableGeometry()
    combo = _make_combo()
    combo.setParent(None)
    combo.move(100, avail.bottom() - 60)
    combo.show()
    _pump(app, 0.2)
    combo.showPopup()
    _pump(app, 0.3)
    win = combo.view().window()
    combo_top = combo.mapToGlobal(combo.rect().topLeft()).y()
    # Fits above (tall screen edge case aside, 110px popup always does).
    assert win.y() + win.height() == combo_top - POPUP_GAP
    combo.hidePopup()
    _pump(app, 0.2)
    combo.close()


def test_reduced_motion_popup_is_instant(app, monkeypatch):
    monkeypatch.setenv("POISE_NO_ANIM", "1")
    combo = _make_combo()
    _pump(app, 0.2)
    combo.showPopup()
    _pump(app, 0.2)
    assert combo.view().window().isVisible()
    assert combo._pop_anim is None
    combo.hidePopup()
    _pump(app, 0.2)
    assert not combo.view().window().isVisible()
    combo.close()


def test_wheel_over_dropdown_or_slider_passes_to_the_page(app):
    """A stock QComboBox/QSlider eats the wheel under the pointer: the
    page stopped scrolling and the output device (or threshold) changed.
    Ours ignore it, so Qt hands a real wheel event on to the scroll area.
    (Qt only propagates spontaneous wheel events, so the test checks the
    decline itself; the stock widgets show it would catch the bug.)"""
    from PyQt6.QtCore import QPoint, QPointF, Qt
    from PyQt6.QtGui import QWheelEvent
    from PyQt6.QtWidgets import QApplication, QComboBox, QSlider
    from stream_denoiser.gui.widgets.combo import AnimatedComboBox
    from stream_denoiser.gui.widgets.slider import HoverSlider

    def wheel(target):
        centre = QPointF(target.width() / 2, target.height() / 2)
        ev = QWheelEvent(centre, target.mapToGlobal(centre), QPoint(0, 0),
                         QPoint(0, -120), Qt.MouseButton.NoButton,
                         Qt.KeyboardModifier.NoModifier,
                         Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(target, ev)
        return ev.isAccepted()

    def combo(cls):
        box = cls()
        box.addItems(["Speakers", "Headphones", "Monitor"])
        box.show()
        return box

    def slider(cls):
        bar = cls(Qt.Orientation.Horizontal)
        bar.setRange(-80, -10)
        bar.setValue(-40)
        bar.show()
        return bar

    stock_combo, stock_slider = combo(QComboBox), slider(QSlider)
    ours_combo, ours_slider = combo(AnimatedComboBox), slider(HoverSlider)
    _pump(app)
    assert wheel(stock_combo) and stock_combo.currentIndex() == 1
    assert wheel(stock_slider) and stock_slider.value() != -40
    assert not wheel(ours_combo) and ours_combo.currentIndex() == 0
    assert not wheel(ours_slider) and ours_slider.value() == -40
    for widget in (ours_combo, ours_slider):     # no focus from the wheel
        assert widget.focusPolicy() == Qt.FocusPolicy.StrongFocus
    for widget in (stock_combo, stock_slider, ours_combo, ours_slider):
        widget.close()
