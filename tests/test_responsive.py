"""Responsive layout modes (needs Qt; skipped without it).

Home is the dial card over two cards in every mode. Wide keeps the cards
side by side; compact tightens chrome (and stacks them below 1000 px);
narrow re-grids theme tiles, shrinks the dial and collapses the sidebar
to an icon rail.
"""
import os
import time

import pytest

pytest.importorskip("PyQt6.QtWidgets")


@pytest.fixture(scope="module")
def app():
    # Forced offscreen (not setdefault): deterministic geometry.
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_window(app=None):
    from stream_denoiser.gui.main_window import MainWindow
    window = MainWindow()
    window.show()
    # Settle first layout activation BEFORE any test resize: a freshly
    # shown top-level fits itself to sizeHint asynchronously, which
    # would otherwise clobber the very next resize (flaky geometry).
    if app is not None:
        _pump(app, 0.3)
    return window


def _pump(app, secs=0.4):
    end = time.time() + secs
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def _wide(app, window, w=1250, h=760):
    window.resize(w, h)
    _pump(app)


def _theme_cols(window):
    grid = window.theme_grid
    return 1 + max(grid.getItemPosition(grid.indexOf(t))[1]
                   for t in window.theme_tiles)


def test_wide_mode_is_the_layout(app):
    from PyQt6.QtWidgets import QBoxLayout, QLabel
    from stream_denoiser.gui.scaling import sp
    window = _make_window(app)
    _wide(app, window)
    assert window._resp == "wide"
    assert window._home_layout.direction() == QBoxLayout.Direction.TopToBottom
    assert window._cards_layout.direction() == QBoxLayout.Direction.LeftToRight
    assert _theme_cols(window) == 6
    assert not window.sidebar.is_compact
    assert window.sidebar.width() == sp(216)
    m = window._home_layout.contentsMargins()
    assert (m.left(), m.top()) == (sp(26), sp(20))
    assert window.power_btn.width() == sp(300)
    # The two cards share the row evenly.
    left = window._cards_layout.itemAt(0).widget()
    right = window._cards_layout.itemAt(1).widget()
    assert abs(left.width() - right.width()) <= 1
    # No input selector: the status bar names the VB-Cable source.
    assert [l for l in window.stats_bar.findChildren(QLabel)
            if l.text() == "vb-cable"]
    window.close()


def test_compact_mode_tightens_chrome(app):
    from PyQt6.QtWidgets import QBoxLayout
    from stream_denoiser.gui.scaling import sp
    window = _make_window(app)
    _wide(app, window, w=1000, h=700)
    assert window._resp == "compact"
    assert _theme_cols(window) == 6
    assert not window.sidebar.is_compact
    m = window._home_layout.contentsMargins()
    assert (m.left(), m.top()) == (sp(16), sp(16))
    assert window._home_layout.spacing() == sp(16)
    assert window.power_btn.width() == sp(270)
    # The page fits the viewport: nothing is clipped on the right.
    scroll = window.stack.widget(0)
    assert (scroll.widget().minimumSizeHint().width()
            <= scroll.viewport().width())
    window.close()


def test_cards_stack_before_they_overflow(app):
    """Side by side just above CARDS_STACK_BELOW still fits; below, they
    stack."""
    import math
    from PyQt6.QtWidgets import QBoxLayout
    from stream_denoiser.gui.scaling import ui_scale
    window = _make_window(app)
    scroll = window.stack.widget(0)
    _wide(app, window, h=700,
          w=math.ceil(window.CARDS_STACK_BELOW * ui_scale()) + 2)
    assert window._cards_layout.direction() == QBoxLayout.Direction.LeftToRight
    assert (scroll.widget().minimumSizeHint().width()
            <= scroll.viewport().width())
    _wide(app, window, w=900, h=700)
    assert window._resp == "compact"
    assert window._cards_layout.direction() == QBoxLayout.Direction.TopToBottom
    assert (scroll.widget().minimumSizeHint().width()
            <= scroll.viewport().width())
    _wide(app, window, w=1250, h=760)
    assert window._cards_layout.direction() == QBoxLayout.Direction.LeftToRight
    window.close()


def test_narrow_mode_reflows(app):
    from PyQt6.QtWidgets import QBoxLayout
    from PyQt6.QtCore import QPoint
    from stream_denoiser.gui.scaling import sp
    window = _make_window(app)
    _wide(app, window, w=720, h=640)
    assert window._resp == "narrow"
    assert window._cards_layout.direction() == QBoxLayout.Direction.TopToBottom
    assert _theme_cols(window) == 3
    assert window.power_btn.width() == sp(240)
    # Icon rail.
    assert window.sidebar.is_compact
    assert window.sidebar.width() == sp(68)
    for btn in window.sidebar._buttons:
        assert not btn._label.isVisible()
    # Theme tiles stay three across (two even rows of three).
    window._on_page_requested(1)
    _pump(app)
    tiles = window.theme_tiles
    assert len(tiles) == 6
    assert tiles[2].y() == tiles[0].y()
    assert tiles[3].y() > tiles[0].y()
    window._on_page_requested(0)
    _pump(app)
    # The sliding highlight still tracks after the reflow.
    window.sidebar.set_active_page(2)
    _pump(app)
    ind = window.sidebar._indicator.geometry()
    btn = window.sidebar._buttons[2]
    top = btn.mapTo(window.sidebar, QPoint(0, 0)).y()
    assert abs((top + btn.height() / 2)
               - (ind.y() + ind.height() / 2)) < 2
    window.close()


def test_roundtrip_restores_wide(app):
    from PyQt6.QtWidgets import QBoxLayout
    from stream_denoiser.gui.scaling import sp
    window = _make_window(app)
    _wide(app, window, w=720, h=640)
    assert window._resp == "narrow"
    _wide(app, window, w=1250, h=760)
    assert window._resp == "wide"
    assert window._cards_layout.direction() == QBoxLayout.Direction.LeftToRight
    assert _theme_cols(window) == 6
    assert window.power_btn.width() == sp(300)
    assert not window.sidebar.is_compact
    assert window.sidebar.width() == sp(216)
    assert window.sidebar._buttons[0]._label.isVisible()
    # Theme tiles back to one row across the Appearance card.
    window._on_page_requested(1)
    _pump(app)
    tiles = window.theme_tiles
    assert all(b.x() > a.x() for a, b in zip(tiles, tiles[1:]))
    assert all(t.y() == tiles[0].y() for t in tiles)
    window._on_page_requested(0)
    _pump(app)
    window.close()


def test_breakpoints_use_design_pixels(app):
    """Modes normalize by UI scale: an 1100px window at 1.5x holds ~733px
    of layout and must read narrow, not wide (HiDPI xcb regression).

    Sized with margin (not near the 850 line): exact window geometry can
    drift slightly when fixed widget sizes go stale across the forced
    scale change, which only this test performs.
    """
    from stream_denoiser.gui import scaling
    window = _make_window()
    prev_scale = scaling._scale_factor
    try:
        scaling.set_scale_factor(1.5)
        _wide(app, window, w=1100, h=800)
        assert window.width() / 1.5 < 800
        assert window._resp == "narrow"
        assert window.sidebar.is_compact
        _wide(app, window, w=1800, h=900)
        assert window._resp == "wide"
    finally:
        # Restore pristine (None), not re-detected: init_scaling() would
        # leave a stored factor behind for later test files.
        scaling._scale_factor = prev_scale
        window.close()
