"""Hover must paint wherever the pointer is over a button (needs Qt).

Regression: sidebar items only showed their hover wash on the thin
margin not covered by the icon/label children, so hover seemed to work
"sometimes". Child widgets inside buttons must not take mouse events.
The sidebar wash itself fades out to the right (like the active item's).
"""
import os
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


def _styled_root(app, *widgets):
    from PyQt6.QtWidgets import QVBoxLayout, QWidget
    from stream_denoiser.gui import themes
    from stream_denoiser.gui.fonts import load_fonts
    from stream_denoiser.gui.styles import get_stylesheet
    themes.set_current("halcyon")
    load_fonts()
    root = QWidget()
    root.setStyleSheet(get_stylesheet())
    lay = QVBoxLayout(root)
    for w in widgets:
        lay.addWidget(w)
    root.resize(280, 140 * len(widgets))
    root.show()
    root.activateWindow()
    _pump(app, 0.4)
    return root


def _patch(root, widget, pt, r=2):
    """Pixels within r of pt: a lone pixel may sit on an opaque glyph
    (where it lands depends on the platform's font rasterizer), but the
    wash still shows between the strokes around it."""
    img = root.grab().toImage()
    c = widget.mapTo(root, pt)
    return [img.pixelColor(c.x() + dx, c.y() + dy).getRgb()
            for dy in range(-r, r + 1) for dx in range(-r, r + 1)]


def _hover_changes_pixel(app, root, widget, pt):
    from PyQt6.QtCore import QPoint
    from PyQt6.QtTest import QTest
    QTest.mouseMove(root, QPoint(1, 1))
    _pump(app, 0.2)
    base = _patch(root, widget, pt)
    QTest.mouseMove(root, widget.mapTo(root, pt))
    _pump(app, 0.3)
    hovered = _patch(root, widget, pt)
    QTest.mouseMove(root, QPoint(1, 1))
    _pump(app, 0.2)
    return hovered != base


def test_nav_hover_paints_over_icon_and_label(app):
    from PyQt6.QtCore import QPoint
    from stream_denoiser.gui.widgets.sidebar import NavButton
    nav = NavButton(1, "gear", "Settings")      # inactive item
    root = _styled_root(app, nav)
    h = nav.height() // 2
    # The wash fades out toward the right, so probe where it is visible.
    try:
        for where, pt in (("icon", QPoint(24, h)),
                          ("label", QPoint(90, h))):
            assert _hover_changes_pixel(app, root, nav, pt), where
    finally:
        root.close()  # a window left open takes the next test's hover


def test_output_rescan_button_hovers_over_its_icon(app):
    from PyQt6.QtCore import QPoint
    from stream_denoiser.gui.widgets.device_selector import DeviceSelector
    sel = DeviceSelector("Output device", "output")
    root = _styled_root(app, sel)
    btn = sel._refresh_btn
    centre = QPoint(btn.width() // 2, btn.height() // 2)
    try:
        assert _hover_changes_pixel(app, root, btn, centre)
    finally:
        root.close()


def test_buttons_with_child_widgets_never_take_mouse_events(app):
    """Every child inside any button must be mouse-transparent."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QAbstractButton, QWidget
    from stream_denoiser.gui.main_window import MainWindow
    from stream_denoiser.gui.widgets.vb_cable_dialog import VbCableDialog
    win = MainWindow()
    win.show()
    dlg = VbCableDialog(win, "x")
    offenders = []
    for top in (win, dlg):
        for btn in top.findChildren(QAbstractButton):
            for child in btn.children():
                if (isinstance(child, QWidget) and not child.testAttribute(
                        Qt.WidgetAttribute.WA_TransparentForMouseEvents)):
                    offenders.append((type(btn).__name__, btn.objectName(),
                                      type(child).__name__))
    assert offenders == [], offenders
    dlg.close()
    win.close()
