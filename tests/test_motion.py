"""Motion: eased state blends, hover fades and the theme crossfade (needs Qt)."""
import os
import re
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
        time.sleep(0.01)


def _enter(widget):
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QEnterEvent
    pt = QPointF(3, 3)
    widget.enterEvent(QEnterEvent(pt, pt, pt))


def _leave(widget):
    from PyQt6.QtCore import QEvent
    widget.leaveEvent(QEvent(QEvent.Type.Leave))


# -- Blend ------------------------------------------------------------------------
def test_blend_glides_then_lands(app):
    from PyQt6.QtCore import QObject
    from stream_denoiser.gui.animations import Blend
    owner = QObject()
    steps = []
    blend = Blend(owner, lambda: steps.append(blend.value), 120)
    blend.set_target(1.0)
    assert blend.running and blend.target == 1.0 and blend.value < 1.0
    _pump(app, 0.35)
    assert blend.value == pytest.approx(1.0) and not blend.running
    # Glided: values in between, read from the steps rather than at a set
    # time (a 50 ms window missed every tick when a GC pass landed in it).
    assert len(steps) > 2 and any(0.0 < v < 1.0 for v in steps)
    blend.set_target(1.0)                # same target: no restart
    assert not blend.running


def test_blend_snaps_under_reduced_motion(app, monkeypatch):
    from PyQt6.QtCore import QObject
    from stream_denoiser.gui.animations import Blend
    monkeypatch.setenv("POISE_NO_ANIM", "1")
    owner = QObject()
    blend = Blend(owner, lambda: None, 200)
    blend.set_target(1.0)
    assert blend.value == 1.0 and not blend.running
    blend.set_target(0.0)
    assert blend.value == 0.0


# -- QSS hover crossfade ----------------------------------------------------------------
def _styled_ghost(app):
    from PyQt6.QtWidgets import QPushButton, QVBoxLayout, QWidget
    from stream_denoiser.gui import themes
    from stream_denoiser.gui.animations import install_hover_fades
    from stream_denoiser.gui.fonts import load_fonts
    from stream_denoiser.gui.styles import get_stylesheet
    themes.set_current("abyss")
    load_fonts()
    root = QWidget()
    root.setStyleSheet(get_stylesheet())
    lay = QVBoxLayout(root)
    btn = QPushButton("Open settings")
    btn.setObjectName("ghost")
    lay.addWidget(btn)
    root.show()
    _pump(app, 0.2)
    assert install_hover_fades(root) == 1
    return root, btn


def _rgba(sheet):
    m = re.search(r"rgba\((\d+), (\d+), (\d+), ([\d.]+)\)", sheet)
    return tuple(float(g) for g in m.groups())


def test_ghost_hover_fades_between_rest_and_secondary(app):
    from PyQt6.QtGui import QColor
    from stream_denoiser.gui import themes
    root, btn = _styled_ghost(app)
    fade = btn._hover_fade
    secondary = QColor(themes.current()["secondary"])
    fade._begin(1.0)
    # Pinned to the rest colour at once (no one-frame flash of :hover).
    assert btn.styleSheet().startswith("QPushButton#ghost")
    assert _rgba(btn.styleSheet())[:3] == (148.0, 163.0, 184.0)
    _pump(app, 0.06)
    r, g, b, _a = _rgba(btn.styleSheet())
    assert 148 < r <= secondary.red() and g <= 196 + 1
    _pump(app, 0.4)
    assert btn.styleSheet() == ""        # settled: plain QSS :hover applies
    fade._begin(0.0)
    assert _rgba(btn.styleSheet())[:3] == (
        float(secondary.red()), float(secondary.green()),
        float(secondary.blue()))         # starts from the hover colour
    _pump(app, 0.45)
    assert btn.styleSheet() == ""
    root.close()


def test_hover_fade_snaps_under_reduced_motion(app, monkeypatch):
    root, btn = _styled_ghost(app)
    monkeypatch.setenv("POISE_NO_ANIM", "1")
    btn._hover_fade._begin(1.0)
    assert btn.styleSheet() == ""
    root.close()


def test_main_window_wires_hover_fades(app):
    from PyQt6.QtWidgets import QComboBox, QPushButton
    from stream_denoiser.gui.main_window import MainWindow
    win = MainWindow()
    wired = {w.objectName() for w in win.findChildren(QPushButton)
             if getattr(w, "_hover_fade", None) is not None}
    assert {"ghost", "icon-btn"} <= wired
    combos = [w for w in win.findChildren(QComboBox)
              if w.objectName() == "device-combo"]
    assert combos and all(c._hover_fade is not None for c in combos)
    win.close()


# -- painted widgets ---------------------------------------------------------------------
def test_nav_hover_wash_fades_in_and_yields_to_the_active_wash(app):
    from stream_denoiser.gui.widgets.sidebar import NavButton
    nav = NavButton(1, "gear", "Settings")
    nav.show()
    _pump(app, 0.1)
    _enter(nav)
    assert nav._hover_blend.target == 1.0
    assert nav._hover_blend.running            # eased, not instant
    _pump(app, 0.4)
    assert nav._hover_blend.value == pytest.approx(1.0)
    nav.set_active(True)                       # the active wash takes over
    assert nav._hover_blend.target == 0.0
    _leave(nav)
    _pump(app, 0.4)
    assert nav._hover_blend.value == pytest.approx(0.0)
    nav.close()


def test_model_card_surface_transitions(app):
    from stream_denoiser.gui.widgets.model_cards import ModelCards
    cards = ModelCards()
    cards.show()
    _pump(app, 0.2)
    first = next(c for c in cards._cards.values() if c.isEnabled())
    assert first._check.value == 1.0 and not first._check.running  # restored: snapped
    other = next((c for c in cards._cards.values()
                  if c.isEnabled() and c is not first), None)
    if other is not None:
        other.click()
        assert other._check.target == 1.0 and other._check.running
        assert first._check.target == 0.0
        _pump(app, 0.4)
        assert other._check.value == pytest.approx(1.0)
        assert first._check.value == pytest.approx(0.0)
        _leave(first)                          # offscreen pointer sits at (0, 0)
        _pump(app, 0.3)
        _enter(first)
        assert first._hover.target == 1.0 and first._hover.running
        _leave(first)
        assert first._hover.target == 0.0
    cards.grab()                               # paints cleanly mid/after
    cards.close()


def test_settings_row_wash_is_eased(app):
    from PyQt6.QtWidgets import QPushButton
    from stream_denoiser.gui.widgets.settings_row import SettingsRow
    row = SettingsRow("Title", "caption", QPushButton("x"))
    row.set_position(True, True)
    row.show()
    _pump(app, 0.2)
    _leave(row)                                # offscreen pointer sits at (0, 0)
    _pump(app, 0.3)
    _enter(row)
    assert row._lit_blend.target == 1.0 and row._lit_blend.running
    _pump(app, 0.4)
    assert row._lit_blend.value == pytest.approx(1.0)
    _leave(row)
    _pump(app, 0.4)
    assert row._lit_blend.value == pytest.approx(0.0)
    row.close()


def test_dial_head_needle_glow_is_eased(app):
    from PyQt6.QtCore import QPoint
    from stream_denoiser.gui.widgets.dial import DialButton
    btn = DialButton()
    btn.show()
    _pump(app, 0.1)
    btn._update_hover_cursor(QPoint(btn.width() // 2, btn.height() // 2))
    assert btn._hot_blend.target == 1.0 and btn._hot_blend.running
    _pump(app, 0.3)
    assert btn._hot_blend.value == pytest.approx(1.0)
    btn._update_hover_cursor(QPoint(1, 1))
    assert btn._hot_blend.target == 0.0
    btn.close()


# -- theme crossfade --------------------------------------------------------------------------
def _fade_overlays(win):
    from PyQt6.QtWidgets import QLabel
    return [c for c in win.children()
            if isinstance(c, QLabel) and c.pixmap() is not None
            and not c.pixmap().isNull()]


def test_theme_switch_crossfades_from_a_snapshot(app):
    from stream_denoiser.gui import themes
    from stream_denoiser.gui.main_window import MainWindow
    win = MainWindow()
    win.resize(1180, 760)
    win.show()
    _pump(app, 0.6)
    original = win.settings.theme
    target = "verdant" if original != "verdant" else "abyss"
    try:
        win._apply_theme(target)
        assert len(_fade_overlays(win)) == 1
        _pump(app, 0.6)
        assert _fade_overlays(win) == []         # detached when done
    finally:
        win._apply_theme(original)
        win.close()
    assert themes.current_id() == original


def test_theme_switch_is_instant_under_reduced_motion(app, monkeypatch):
    from stream_denoiser.gui.main_window import MainWindow
    win = MainWindow()
    win.show()
    _pump(app, 0.4)
    original = win.settings.theme
    monkeypatch.setenv("POISE_NO_ANIM", "1")
    target = "verdant" if original != "verdant" else "abyss"
    win._apply_theme(target)
    assert _fade_overlays(win) == []
    win._apply_theme(original)
    win.close()


# -- TextSwap (status line fades) ----------------------------------------------------
@pytest.fixture()
def shown_label(app, monkeypatch):
    from PyQt6.QtWidgets import QLabel
    monkeypatch.delenv("POISE_NO_ANIM", raising=False)
    monkeypatch.delenv("POISE_REDUCE_MOTION", raising=False)
    label = QLabel("old")
    label.show()
    _pump(app, 0.05)
    yield label
    label.close()


def test_text_swap_fades_out_then_in_and_drops_the_effect(app, shown_label):
    from stream_denoiser.gui.animations import TextSwap
    swap = TextSwap(shown_label)
    settled = []
    swap.settled.connect(lambda: settled.append(shown_label.text()))
    applied = []
    swap.set_text("new", on_apply=lambda: applied.append(shown_label.text()))
    assert shown_label.text() == "old" and swap.busy and swap.text() == "new"
    assert applied == []                     # not while "old" fades out
    _pump(app, 0.5)
    assert shown_label.text() == "new" and not swap.busy
    assert applied == ["old"]                # ran just before "new" appeared
    assert settled == ["new"]
    assert shown_label.graphicsEffect() is None


def test_text_swap_coalesces_a_burst(app, shown_label):
    from stream_denoiser.gui.animations import TextSwap
    swap = TextSwap(shown_label)
    seen = []
    swap.settled.connect(lambda: seen.append(shown_label.text()))
    for text in ("one", "two", "three"):
        swap.set_text(text)
    _pump(app, 0.5)
    assert shown_label.text() == "three" and seen == ["three"]


def test_text_swap_is_instant_when_hidden_reduced_or_effect_taken(
        app, shown_label, monkeypatch):
    from PyQt6.QtWidgets import QGraphicsOpacityEffect, QLabel
    from stream_denoiser.gui.animations import TextSwap
    hidden = QLabel("old")
    TextSwap(hidden).set_text("new")
    assert hidden.text() == "new"
    pulse = QGraphicsOpacityEffect(shown_label)    # someone else's fade
    shown_label.setGraphicsEffect(pulse)
    swap = TextSwap(shown_label)
    swap.set_text("new")
    assert shown_label.text() == "new" and not swap.busy
    assert shown_label.graphicsEffect() is pulse   # left alone, no nesting
    shown_label.setGraphicsEffect(None)
    monkeypatch.setenv("POISE_NO_ANIM", "1")
    swap.set_text("instant")
    assert shown_label.text() == "instant"
