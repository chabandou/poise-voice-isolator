"""Responsive layout modes (needs Qt; skipped without it).

Wide puts the dial card beside the cards; compact tightens chrome;
narrow stacks the cards, re-grids theme tiles, shrinks the dial and
collapses the sidebar to an icon rail.
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


def test_wide_mode_is_the_layout(app):
    from PyQt6.QtWidgets import QBoxLayout, QLabel
    from stream_denoiser.gui.scaling import sp
    window = _make_window(app)
    _wide(app, window)
    assert window._resp == "wide"
    assert window._home_layout.direction() == QBoxLayout.Direction.LeftToRight
    assert (window._settings_bottom.direction()
            == QBoxLayout.Direction.LeftToRight)
    assert not window.sidebar.is_compact
    assert window.sidebar.width() == sp(216)
    m = window._home_layout.contentsMargins()
    assert (m.left(), m.top()) == (sp(26), sp(26))
    assert window.power_btn.width() == sp(300)
    # Routing note explains automatic VB-Cable capture (no input selector).
    notes = [l for l in window.findChildren(QLabel)
             if "VB-Cable" in l.text()]
    assert notes, "expected automatic VB-Cable routing note"
    window.close()


def test_compact_mode_tightens_chrome(app):
    from PyQt6.QtWidgets import QBoxLayout
    from stream_denoiser.gui.scaling import sp
    window = _make_window(app)
    _wide(app, window, w=1000, h=700)
    assert window._resp == "compact"
    assert window._home_layout.direction() == QBoxLayout.Direction.LeftToRight
    assert (window._settings_bottom.direction()
            == QBoxLayout.Direction.LeftToRight)
    assert not window.sidebar.is_compact
    m = window._home_layout.contentsMargins()
    assert (m.left(), m.top()) == (sp(16), sp(16))
    assert window._home_layout.spacing() == sp(16)
    assert window.power_btn.width() == sp(270)
    window.close()


def test_narrow_mode_reflows(app):
    from PyQt6.QtWidgets import QBoxLayout
    from PyQt6.QtCore import QPoint
    from stream_denoiser.gui.scaling import sp
    window = _make_window(app)
    _wide(app, window, w=720, h=640)
    assert window._resp == "narrow"
    assert window._home_layout.direction() == QBoxLayout.Direction.TopToBottom
    assert (window._settings_bottom.direction()
            == QBoxLayout.Direction.TopToBottom)
    assert window.power_btn.width() == sp(240)
    # Icon rail.
    assert window.sidebar.is_compact
    assert window.sidebar.width() == sp(68)
    for btn in window.sidebar._buttons:
        assert not btn._label.isVisible()
    # Theme tiles wrap 4 across when the cards stack.
    window._on_page_requested(1)
    _pump(app)
    tiles = window.theme_tiles
    assert tiles[1].y() == tiles[0].y()
    assert tiles[3].y() == tiles[0].y()
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
    assert window._home_layout.direction() == QBoxLayout.Direction.LeftToRight
    assert (window._settings_bottom.direction()
            == QBoxLayout.Direction.LeftToRight)
    assert window.power_btn.width() == sp(300)
    assert not window.sidebar.is_compact
    assert window.sidebar.width() == sp(216)
    assert window.sidebar._buttons[0]._label.isVisible()
    # Theme tiles back to two across (2x2 inside the Appearance card).
    window._on_page_requested(1)
    _pump(app)
    tiles = window.theme_tiles
    assert tiles[1].x() > tiles[0].x()
    assert tiles[1].y() == tiles[0].y()
    assert tiles[2].y() > tiles[0].y()
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
