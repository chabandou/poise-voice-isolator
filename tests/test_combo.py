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


def test_selection_api_unchanged(app):
    combo = _make_combo()
    combo.setCurrentIndex(2)
    assert combo.currentText() == "RNNoise (row text)"
    assert combo.currentData() == "rnnoise"
    combo.close()


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


def test_titles_fall_back_to_the_row_text(app, still):
    from stream_denoiser.gui.widgets.combo import AnimatedComboBox
    combo = AnimatedComboBox()
    combo.addItems(["Speakers", "Headphones"])
    combo.show()
    popup = _open(app, combo)
    assert [c.title for c in popup.cards] == ["Speakers", "Headphones"]
    assert all(c.blurb == "" for c in popup.cards)
    combo.hidePopup()
    combo.close()


def test_popup_hangs_under_the_button(app, still):
    from stream_denoiser.gui.scaling import sp
    from stream_denoiser.gui.widgets.combo import POPUP_GAP
    combo = _make_combo()
    popup = _open(app, combo)
    panel = popup.panel
    top_left = panel.mapToGlobal(panel.rect().topLeft())
    combo_left = combo.mapToGlobal(combo.rect().topLeft())
    assert top_left.y() == combo_left.y() + combo.height() + sp(POPUP_GAP)
    assert top_left.x() == combo_left.x()
    assert panel.width() == combo.width()
    combo.hidePopup()
    combo.close()


def test_popup_flips_above_when_no_room(app, still):
    from PyQt6.QtWidgets import QApplication
    from stream_denoiser.gui.scaling import sp
    from stream_denoiser.gui.widgets.combo import POPUP_GAP
    avail = QApplication.primaryScreen().availableGeometry()
    combo = _make_combo()
    combo.move(100, avail.bottom() - 60)
    popup = _open(app, combo)
    panel = popup.panel
    bottom = panel.mapToGlobal(panel.rect().bottomLeft()).y() + 1
    top = combo.mapToGlobal(combo.rect().topLeft()).y()
    assert bottom == top - sp(POPUP_GAP)
    combo.hidePopup()
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


def test_card_hover_clears_on_leave(app, still):
    """The hover glow used to stay after the pointer left a card."""
    from PyQt6.QtCore import QEvent, QPointF, Qt
    from PyQt6.QtGui import QEnterEvent
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication
    combo = _make_combo(current=0)
    popup = _open(app, combo)
    card = popup.cards[2]
    centre = QPointF(card.rect().center())
    QApplication.sendEvent(card, QEnterEvent(centre, centre,
                                             QPointF(card.mapToGlobal(
                                                 card.rect().center()))))
    assert popup.active_row == 2 and card._hover.value == 1.0
    QApplication.sendEvent(card, QEvent(QEvent.Type.Leave))
    assert popup.active_row is None and card._hover.value == 0.0
    # A keyboard highlight elsewhere isn't cleared by an unrelated leave.
    QTest.keyClick(popup, Qt.Key.Key_Down)
    assert popup.active_row == 1
    QApplication.sendEvent(card, QEvent(QEvent.Type.Leave))
    assert popup.active_row == 1 and popup.cards[1]._hover.value == 1.0
    combo.hidePopup()
    combo.close()


def test_a_click_outside_closes_without_picking(app, still):
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest
    combo = _make_combo(current=1)
    popup = _open(app, combo)
    # In the panel's padding: stays open.
    QTest.mouseClick(popup, Qt.MouseButton.LeftButton,
                     pos=popup.panel.geometry().topLeft() + QPoint(3, 3))
    assert popup.isVisible()
    # In the shadow margin (outside the panel): closes, choice kept.
    QTest.mouseClick(popup, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
    _pump(app, 0.1)
    assert not popup.isVisible() and combo.currentIndex() == 1
    combo.close()


def test_the_entrance_fades_in_and_rises(app, monkeypatch):
    monkeypatch.delenv("POISE_NO_ANIM", raising=False)
    monkeypatch.delenv("POISE_REDUCE_MOTION", raising=False)
    combo = _make_combo()
    _pump(app, 0.1)
    combo.showPopup()
    popup = combo.popup()
    panel, rest = popup.panel, popup._rest
    app.processEvents()
    # First frames: faint, and still low if the clock has started (the
    # rise and growth are painted from a snapshot; the live panel waits
    # at rest, empty).
    assert popup.shown_opacity < 0.5
    assert panel.opacity == 0.0 and panel.pos() == rest
    assert popup._frame is None or popup._frame[1] < 1.0
    # The ghost is already on screen, empty, ready for the close.
    ghost = combo._ghost
    assert ghost is not None and ghost.isVisible() and not ghost.fading
    _pump(app, 0.6)
    assert panel.opacity == 1.0 and panel.pos() == rest
    assert combo._chevron.value == 1.0
    # Closing hands the snapshot to the ghost and hides at once, leaving
    # an empty last frame behind.
    combo.hidePopup()
    assert not popup.isVisible()
    assert ghost.isVisible() and ghost.fading
    assert panel.opacity == 0.0
    _pump(app, 0.4)
    assert not ghost.isVisible() and not ghost.fading
    combo.close()


def _moving(monkeypatch):
    monkeypatch.delenv("POISE_NO_ANIM", raising=False)
    monkeypatch.delenv("POISE_REDUCE_MOTION", raising=False)


def test_the_entrance_grows_from_a_round_snapshot(app, monkeypatch):
    """Widgets can't scale, so the entrance paints a snapshot of the
    finished panel growing from START_SCALE; its corners stay round."""
    from stream_denoiser.gui.widgets.combo import START_SCALE
    _moving(monkeypatch)
    combo = _make_combo()
    _pump(app, 0.1)
    combo.showPopup()
    popup = combo.popup()
    still = popup._still.toImage()
    assert still.pixelColor(1, 1).alpha() == 0            # round corner
    assert still.pixelColor(still.width() // 2,
                            still.height() // 2).alpha() == 255
    scales = []
    end = time.time() + 0.6
    while time.time() < end:
        app.processEvents()
        if popup._frame is not None:
            scales.append(START_SCALE
                          + (1 - START_SCALE) * popup._frame[1])
        time.sleep(0.005)
    assert scales and min(scales) < 0.98 and scales == sorted(scales)
    # At rest the live panel is back and the snapshot is gone.
    assert popup._frame is None and popup._still is None
    assert popup.panel.opacity == 1.0
    combo.hidePopup()
    _pump(app, 0.3)
    combo.close()


def test_the_close_is_the_opening_played_backwards(app, monkeypatch):
    """Same speed as the opening (a quicker close felt abrupt), and from
    wherever the entrance is when closed mid-way (no jump)."""
    from stream_denoiser.gui.widgets.combo import (
        CLOSE_MS, OPEN_MS, _entrance_frame)
    _moving(monkeypatch)
    assert CLOSE_MS == OPEN_MS
    combo = _make_combo()
    popup = _open(app, combo)
    combo.hidePopup()
    ghost = combo._ghost
    assert ghost.fading and ghost._t == 1.0
    assert ghost._anim.duration() == CLOSE_MS
    _pump(app, CLOSE_MS / 2000.0)
    opacity, scale, lift = _entrance_frame(ghost._t)
    assert 0.0 < ghost._t < 1.0
    assert scale < 1.0 and lift > 0.0          # shrinking and sinking
    _pump(app, CLOSE_MS / 1000.0)
    assert not ghost.isVisible()
    # Closed mid-entrance: the reverse starts from there.
    combo.showPopup()
    _pump(app, 0.12)
    shown = popup._progress
    assert 0.0 < shown < 1.0
    combo.hidePopup()
    assert abs(ghost._t - shown) < 0.15
    assert ghost._anim.duration() < CLOSE_MS
    _pump(app, 0.3)
    combo.close()


def test_the_snapshot_hands_over_without_a_jump(app, monkeypatch):
    """The entrance's last snapshot frame and the live panel match."""
    from PyQt6.QtCore import QEasingCurve
    _moving(monkeypatch)
    combo = _make_combo()
    _pump(app, 0.1)
    combo.showPopup()
    popup = combo.popup()
    popup._stop_anim()
    popup._snapshot_panel()
    popup._set_progress(1.0, QEasingCurve(QEasingCurve.Type.OutQuad))
    assert popup._frame is not None
    snap = popup.grab().toImage()
    popup._set_progress(None)
    live = popup.grab().toImage()
    worst = 0
    for y in range(0, snap.height(), 3):
        for x in range(0, snap.width(), 3):
            a, b = snap.pixelColor(x, y), live.pixelColor(x, y)
            worst = max(worst, abs(a.red() - b.red()),
                        abs(a.green() - b.green()),
                        abs(a.blue() - b.blue()),
                        abs(a.alpha() - b.alpha()))
    assert worst <= 8, worst
    combo.hidePopup()
    _pump(app, 0.3)
    combo.close()


def test_a_pick_plays_the_switch_then_closes(app, monkeypatch):
    """Like Settings' cards: the choice applies at once, the gold edge,
    tint and diamond glide from the old card to the new one, and the
    list closes only once that lands (its fading snapshot shows the
    new choice)."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from stream_denoiser.gui.widgets.combo import SWITCH_HOLD_MS, SWITCH_MS
    _moving(monkeypatch)
    combo = _make_combo(current=0)
    popup = _open(app, combo)
    card = popup.cards[2]
    QTest.mouseClick(card, Qt.MouseButton.LeftButton,
                     pos=card.rect().center())
    assert combo.currentIndex() == 2          # applied at once
    assert popup.isVisible() and popup.switching
    _pump(app, SWITCH_MS / 2000.0)
    old, new = popup.cards[0]._check.value, popup.cards[2]._check.value
    assert 0.0 < old < 1.0 and 0.0 < new < 1.0      # mid-glide
    # Nothing else is picked while it plays.
    QTest.mouseClick(popup.cards[1], Qt.MouseButton.LeftButton,
                     pos=popup.cards[1].rect().center())
    QTest.keyClick(popup, Qt.Key.Key_Up)
    assert combo.currentIndex() == 2 and popup.active_row == 2
    _pump(app, (SWITCH_MS + SWITCH_HOLD_MS) / 1000.0)
    assert not popup.isVisible() and not popup.switching
    assert [c._check.value for c in popup.cards] == [0.0, 0.0, 1.0]
    _pump(app, 0.3)
    combo.close()


def test_closing_mid_switch_snaps_to_the_new_choice(app, monkeypatch):
    """Escape (or a click outside) mid-glide still fades out showing the
    new choice, not the old one lit."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    _moving(monkeypatch)
    combo = _make_combo(current=0)
    popup = _open(app, combo)
    popup.choose(1)
    _pump(app, 0.05)
    QTest.keyClick(popup, Qt.Key.Key_Escape)
    assert not popup.isVisible() and not popup.switching
    assert combo.currentIndex() == 1
    assert [c._check.value for c in popup.cards] == [0.0, 1.0, 0.0]
    assert combo._ghost.fading
    _pump(app, 0.3)
    combo.close()


def test_repicking_the_current_choice_just_closes(app, monkeypatch):
    _moving(monkeypatch)
    combo = _make_combo(current=1)
    popup = _open(app, combo)
    popup.choose(1)
    assert not popup.isVisible() and not popup.switching
    _pump(app, 0.3)
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


def test_the_ring_holds_through_open_and_close(app, still):
    """Hover lights the ring; the popup taking the mouse (a Leave) keeps
    it lit; closing with the pointer still on the button keeps it lit
    (Qt sends no Enter until the next move) until the pointer leaves."""
    from PyQt6.QtCore import QEvent, QPoint
    from PyQt6.QtGui import QCursor
    from PyQt6.QtWidgets import QApplication
    combo = _make_combo()
    _pump(app, 0.1)
    assert combo._ring.value == 0.0
    _hover(combo)
    assert combo._ring.value == 1.0
    # Painted in the theme's secondary (the ghost buttons' hover colour).
    from PyQt6.QtGui import QColor
    from stream_denoiser.gui import themes
    img = combo.grab().toImage()
    edge = img.pixelColor(img.width() // 2, 0)
    gold = QColor(themes.get_theme("halcyon")["secondary"])
    assert (abs(edge.red() - gold.red()) < 24
            and abs(edge.green() - gold.green()) < 24
            and abs(edge.blue() - gold.blue()) < 24), edge.name()
    combo.showPopup()
    QApplication.sendEvent(combo, QEvent(QEvent.Type.Leave))  # popup grab
    assert combo._ring.value == 1.0
    _pump(app, 0.2)
    combo.hidePopup()             # e.g. a click on the button itself
    assert combo._ring.value == 1.0
    _pump(app, 0.2)
    assert combo._ring.value == 1.0
    # The pointer goes without a Leave (none comes after a popup).
    QCursor.setPos(combo.mapToGlobal(QPoint(-200, -200)))
    _pump(app, 0.2)
    assert combo._ring.value == 0.0
    combo.close()


def test_the_ring_goes_when_closing_elsewhere_or_disabled(app, still):
    combo = _make_combo()
    _pump(app, 0.1)
    _hover(combo, inside=False)
    combo.showPopup()
    assert combo._ring.value == 1.0          # open lights it
    combo.hidePopup()                        # pointer far away
    assert combo._ring.value == 0.0
    _hover(combo)
    combo.setEnabled(False)
    assert combo._ring.value == 0.0
    combo.close()


def test_reopening_reuses_the_cards(app, still):
    """A reopen's first frame once painted the previous cards (queued for
    deletion, still visible) at full strength: cards are kept until the
    rows change, and replaced ones are hidden at once."""
    from stream_denoiser.gui.widgets.combo import TITLE_ROLE
    combo = _make_combo()
    popup = _open(app, combo)
    first = popup.cards
    combo.hidePopup()
    combo.setCurrentIndex(0)
    popup = _open(app, combo)
    assert popup.cards == first
    assert [c._check.value for c in first] == [1.0, 0.0, 0.0]
    combo.hidePopup()
    combo.setItemData(1, "Renamed", TITLE_ROLE)
    popup = _open(app, combo)
    assert popup.cards[1].title == "Renamed"
    assert all(c.parent() is None and c.isHidden() for c in first)
    combo.hidePopup()
    combo.close()


def test_reduced_motion_is_instant(app, still):
    combo = _make_combo()
    popup = _open(app, combo)
    assert popup._anim is None and popup.panel.opacity == 1.0
    combo.hidePopup()
    assert combo._ghost is None and not popup.isVisible()
    combo.close()


def test_long_lists_scroll(app, still):
    from stream_denoiser.gui.widgets.combo import MAX_VISIBLE
    items = [(f"d{n}", f"Device {n}", "Realtek(R) Audio") for n in range(12)]
    combo = _make_combo(items=items, current=10)
    popup = _open(app, combo)
    bar = popup._scroll.verticalScrollBar()
    assert bar.maximum() > 0
    shown = popup._scroll.viewport().height()
    card_h = popup.cards[0].height()
    assert card_h * MAX_VISIBLE < shown < card_h * (MAX_VISIBLE + 1)
    # The current card was scrolled into view.
    current = popup.cards[10].geometry()
    assert bar.value() <= current.top()
    assert current.bottom() <= bar.value() + shown
    combo.hidePopup()
    combo.close()


def test_panel_is_a_rounded_card_surface(app, still):
    from stream_denoiser.gui import themes
    combo = _make_combo()
    popup = _open(app, combo)
    img = popup.grab().toImage()
    ratio = img.devicePixelRatio()
    geo = popup.panel.geometry()

    def px(x, y):
        return img.pixelColor(int(x * ratio), int(y * ratio))

    assert px(1, 1).alpha() == 0            # shadow room stays clear
    assert px(geo.left() + 1, geo.top() + 1).alpha() < 255   # round corner
    body = px(geo.right() - 3, geo.center().y())
    from stream_denoiser.gui.widgets.combo import PANEL_FILL
    assert body.name() == themes.get_theme("halcyon")[PANEL_FILL].lower()
    combo.hidePopup()
    combo.close()


def test_disabled_or_empty_combos_do_not_open(app, still):
    from stream_denoiser.gui.widgets.combo import AnimatedComboBox
    combo = _make_combo()
    combo.setEnabled(False)
    combo.showPopup()
    assert not combo.is_open()
    empty = AnimatedComboBox()
    empty.show()
    empty.showPopup()
    assert not empty.is_open()
    combo.close()
    empty.close()


def test_a_changing_list_closes_the_popup(app, still):
    combo = _make_combo()
    popup = _open(app, combo)
    combo.clear()
    assert not popup.isVisible()
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
