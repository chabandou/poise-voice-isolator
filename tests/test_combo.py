"""Card dropdown behavior (needs Qt; skipped without it).

The list opens as option cards like Settings' model cards: a name over
a blurb, the current one tinted with a diamond. It hangs under the
button (flipping above when there's no room), fades in while rising,
and closes on a choice, Escape or a click outside.
"""
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


@pytest.fixture
def still(monkeypatch):
    """Reduced motion: every state lands at once."""
    monkeypatch.setenv("POISE_NO_ANIM", "1")


ITEMS = (("deepfilternet3", "DeepFilterNet3", "Removes music."),
         ("gtcrn", "GTCRN", "Removes noise from speech."),
         ("rnnoise", "RNNoise", ""))


def _make_combo(items=ITEMS, current=1):
    from stream_denoiser.gui import themes
    from stream_denoiser.gui.styles import get_stylesheet
    from stream_denoiser.gui.widgets.combo import (
        BLURB_ROLE, TITLE_ROLE, AnimatedComboBox)
    themes.set_current("halcyon")
    combo = AnimatedComboBox()
    combo.setObjectName("device-combo")
    for model_id, title, blurb in items:
        combo.addItem(f"{title} (row text)", model_id)
        combo.setItemData(combo.count() - 1, title, TITLE_ROLE)
        if blurb:
            combo.setItemData(combo.count() - 1, blurb, BLURB_ROLE)
    combo.setCurrentIndex(current)
    combo.setStyleSheet(get_stylesheet(theme="halcyon"))
    combo.resize(420, 46)
    combo.move(100, 100)
    combo.show()
    return combo


def _pump(app, secs=0.3):
    end = time.time() + secs
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def _open(app, combo):
    _pump(app, 0.1)
    combo.showPopup()
    _pump(app, 0.5)
    return combo.popup()


def test_opens_one_card_per_row_with_title_and_blurb(app, still):
    combo = _make_combo()
    popup = _open(app, combo)
    assert popup.isVisible() and combo.is_open()
    assert combo.property("open") is True
    cards = popup.cards
    assert [c.title for c in cards] == ["DeepFilterNet3", "GTCRN", "RNNoise"]
    assert [c.blurb for c in cards] == ["Removes music.",
                                        "Removes noise from speech.", ""]
    # Only the current choice carries the tint and diamond.
    assert [c._check.value for c in cards] == [0.0, 1.0, 0.0]
    assert popup.active_row == 1
    combo.hidePopup()
    _pump(app, 0.1)
    assert not popup.isVisible() and combo.property("open") is False
    combo.close()


def test_clicking_a_card_picks_it_and_closes(app, still):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    combo = _make_combo(current=0)
    activated = []
    combo.activated.connect(activated.append)
    popup = _open(app, combo)
    card = popup.cards[2]
    QTest.mouseClick(card, Qt.MouseButton.LeftButton,
                     pos=card.rect().center())
    _pump(app, 0.1)
    assert combo.currentIndex() == 2 and activated == [2]
    assert not popup.isVisible()
    combo.close()


def test_keys_move_pick_and_dismiss(app, still):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    combo = _make_combo(current=0)
    popup = _open(app, combo)
    QTest.keyClick(popup, Qt.Key.Key_Down)
    QTest.keyClick(popup, Qt.Key.Key_Down)
    assert popup.active_row == 2
    assert popup.cards[2]._hover.value == 1.0
    assert popup.cards[0]._hover.value == 0.0
    QTest.keyClick(popup, Qt.Key.Key_Return)
    _pump(app, 0.1)
    assert combo.currentIndex() == 2 and not popup.isVisible()
    popup = _open(app, combo)
    QTest.keyClick(popup, Qt.Key.Key_Up)
    QTest.keyClick(popup, Qt.Key.Key_Escape)
    _pump(app, 0.1)
    assert combo.currentIndex() == 2 and not popup.isVisible()
    combo.close()


def _hover(combo, inside=True):
    """What Qt does on a real hover: the pointer moves, Enter/Leave."""
    from PyQt6.QtCore import QEvent, QPoint, QPointF
    from PyQt6.QtGui import QCursor, QEnterEvent
    from PyQt6.QtWidgets import QApplication
    if inside:
        centre = combo.mapToGlobal(combo.rect().center())
        QCursor.setPos(centre)
        local = QPointF(combo.rect().center())
        QApplication.sendEvent(combo, QEnterEvent(local, local,
                                                  QPointF(centre)))
    else:
        QCursor.setPos(combo.mapToGlobal(QPoint(-200, -200)))
        QApplication.sendEvent(combo, QEvent(QEvent.Type.Leave))


def test_reduced_motion_is_instant(app, still):
    combo = _make_combo()
    popup = _open(app, combo)
    assert popup._anim is None and popup.panel.opacity == 1.0
    combo.hidePopup()
    assert combo._ghost is None and not popup.isVisible()
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
