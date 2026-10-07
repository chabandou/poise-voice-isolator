"""Responsive layout modes (needs Qt; skipped without it).

Wide keeps the dashboard mockup; compact tightens chrome; narrow stacks
rows, re-grids theme tiles, and collapses the sidebar to an icon rail.
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


def test_wide_mode_is_the_mockup(app):
    from PyQt6.QtWidgets import QBoxLayout
    from stream_denoiser.gui.scaling import sp
    window = _make_window(app)
    _wide(app, window)
    assert window._resp == "wide"
    assert window._devices_row.direction() == QBoxLayout.Direction.LeftToRight
    assert window._bottom_row.direction() == QBoxLayout.Direction.LeftToRight
    assert not window.sidebar.is_compact
    assert window.sidebar.width() == sp(216)
    m = window._home_layout.contentsMargins()
    assert (m.left(), m.top()) == (26, 26)
    # VB pill label takes spare width: single line when roomy.
    vb = next(l for l in window.findChildren(type(window.status_label))
              if "Auto-select" in l.text())
    fm = vb.fontMetrics()
    assert round(vb.heightForWidth(vb.width()) / fm.lineSpacing()) == 1
    window.close()


def test_compact_mode_tightens_chrome(app):
    from PyQt6.QtWidgets import QBoxLayout
    window = _make_window(app)
    _wide(app, window, w=1000, h=700)
    assert window._resp == "compact"
    assert window._devices_row.direction() == QBoxLayout.Direction.LeftToRight
    assert window._bottom_row.direction() == QBoxLayout.Direction.LeftToRight
    assert not window.sidebar.is_compact
    m = window._home_layout.contentsMargins()
    assert (m.left(), m.top()) == (16, 16)
    assert window._home_layout.spacing() == 24
    window.close()


def test_narrow_mode_reflows(app):
    from PyQt6.QtWidgets import QBoxLayout
    from stream_denoiser.gui.scaling import sp
    window = _make_window(app)
    _wide(app, window, w=720, h=640)
    assert window._resp == "narrow"
    assert window._devices_row.direction() == QBoxLayout.Direction.TopToBottom
    assert window._bottom_row.direction() == QBoxLayout.Direction.TopToBottom
    # Stacked order: power button first, then input, output.
    row = window._devices_row
    assert row.itemAt(0).layout() is window._power_wrap
    assert row.itemAt(1).widget() is window._input_wrap
    assert row.itemAt(2).widget() is window._output_wrap
    # Icon rail.
    assert window.sidebar.is_compact
    assert window.sidebar.width() == sp(68)
    for btn in window.sidebar._buttons:
        assert not btn._label.isVisible()
    # Lowered label columns lift when stacked.
    assert window._input_wrap.layout().contentsMargins().top() == 0
    assert window._output_wrap.layout().contentsMargins().top() == 0
    # Theme tiles wrap 2x2 (settings page must be visible to lay out).
    window._on_page_requested(1)
    _pump(app)
    tiles = window.theme_tiles
    assert tiles[1].y() == tiles[0].y()
    assert tiles[2].y() > tiles[0].y()
    window._on_page_requested(0)
    _pump(app)
    # Indicator still tracks after the reflow.
    window.sidebar.set_active_page(2)
    _pump(app)
    ind = window.sidebar._indicator.geometry()
    btn = window.sidebar._buttons[2]
    from PyQt6.QtCore import QPoint
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
    assert window._devices_row.direction() == QBoxLayout.Direction.LeftToRight
    assert window._bottom_row.direction() == QBoxLayout.Direction.LeftToRight
    # Wide order restored: input, power, output.
    row = window._devices_row
    assert row.itemAt(0).widget() is window._input_wrap
    assert row.itemAt(1).layout() is window._power_wrap
    assert row.itemAt(2).widget() is window._output_wrap
    assert not window.sidebar.is_compact
    assert window.sidebar.width() == sp(216)
    assert window.sidebar._buttons[0]._label.isVisible()
    window._on_page_requested(1)
    _pump(app)
    tiles = window.theme_tiles
    assert tiles[1].x() > tiles[0].x()
    assert tiles[1].y() == tiles[0].y()
    window._on_page_requested(0)
    _pump(app)
    assert window._input_wrap.layout().contentsMargins().top() > 0
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
