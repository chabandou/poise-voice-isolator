"""Hover must paint wherever the pointer is over a button (needs Qt).

Regression: sidebar items only showed their hover wash on the thin
margin not covered by the icon/label children, so hover seemed to work
"sometimes". Child widgets inside buttons must not take mouse events.
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
    themes.set_current("abyss")
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


def _pixel(root, widget, pt):
    img = root.grab().toImage()
    return img.pixelColor(widget.mapTo(root, pt)).getRgb()


def _hover_changes_pixel(app, root, widget, pt):
    from PyQt6.QtCore import QPoint
    from PyQt6.QtTest import QTest
    QTest.mouseMove(root, QPoint(1, 1))
    _pump(app, 0.2)
    base = _pixel(root, widget, pt)
    QTest.mouseMove(root, widget.mapTo(root, pt))
    _pump(app, 0.3)
    hovered = _pixel(root, widget, pt)
    QTest.mouseMove(root, QPoint(1, 1))
    _pump(app, 0.2)
    return hovered != base


def test_nav_hover_paints_over_icon_label_and_margin(app):
    from PyQt6.QtCore import QPoint
    from stream_denoiser.gui.widgets.sidebar import NavButton
    nav = NavButton(1, "gear", "Settings")      # inactive item
    root = _styled_root(app, nav)
    h = nav.height() // 2
    for where, pt in (("icon", QPoint(24, h)),
                      ("label", QPoint(90, h)),
                      ("margin", QPoint(nav.width() - 4, h))):
        assert _hover_changes_pixel(app, root, nav, pt), where
    root.close()


def test_output_rescan_button_hovers_over_its_icon(app):
    from PyQt6.QtCore import QPoint
    from stream_denoiser.gui.widgets.device_selector import DeviceSelector
    sel = DeviceSelector("Output device", "output")
    root = _styled_root(app, sel)
    btn = sel._refresh_btn
    centre = QPoint(btn.width() // 2, btn.height() // 2)
    assert _hover_changes_pixel(app, root, btn, centre)
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
