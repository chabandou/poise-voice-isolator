"""Dropdown popup styling (needs Qt; skipped without it).

The popup is a card-like surface: rounded, hairline border, translucent
window so the corners are really round. Rows highlight with a soft wash
and the current choice carries a diamond, so hover never looks selected.
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


def _open(app, items=5, current=1):
    from PyQt6.QtWidgets import QVBoxLayout, QWidget
    from stream_denoiser.gui import themes
    from stream_denoiser.gui.fonts import load_fonts
    from stream_denoiser.gui.styles import get_stylesheet
    from stream_denoiser.gui.widgets.combo import AnimatedComboBox
    themes.set_current("abyss")
    load_fonts()
    root = QWidget()
    root.setStyleSheet(get_stylesheet())
    lay = QVBoxLayout(root)
    combo = AnimatedComboBox()
    combo.setObjectName("device-combo")
    for n in range(items):
        combo.addItem(f"Device number {n} (Realtek Audio)")
    combo.setCurrentIndex(current)
    lay.addWidget(combo)
    root.resize(520, 200)
    root.show()
    root.activateWindow()
    _pump(app)
    combo.showPopup()
    _pump(app, 0.4)
    return root, combo


def test_popup_is_a_rounded_translucent_card(app):
    from stream_denoiser.gui import themes
    root, combo = _open(app)
    popup = combo.view().window()
    from PyQt6.QtCore import Qt
    assert popup.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert popup.windowFlags() & Qt.WindowType.NoDropShadowWindowHint
    img = popup.grab().toImage()
    w, h = img.width(), img.height()
    assert img.pixelColor(0, 0).alpha() == 0, "corner must be transparent"
    assert img.pixelColor(w - 1, h - 1).alpha() == 0
    edge = img.pixelColor(w // 2, 0)                  # hairline border
    assert edge.alpha() > 0
    body = img.pixelColor(w - 10, h // 2)             # clear of text
    assert body.name() == themes.get_theme("abyss")["card"].lower()
    combo.hidePopup()
    root.close()


def test_popup_fits_its_rows_without_scroller_strips(app):
    from PyQt6.QtWidgets import QWidget
    root, combo = _open(app, items=5)
    view = combo.view()
    popup = view.window()
    rows = sum(view.sizeHintForRow(i) for i in range(combo.count()))
    assert view.height() == rows
    assert view.verticalScrollBar().maximum() == 0
    strips = [c for c in popup.children()
              if isinstance(c, QWidget) and c is not view]
    assert strips and all(c.height() == 0 for c in strips)
    combo.hidePopup()
    root.close()


def test_long_lists_scroll_with_a_scrollbar(app):
    root, combo = _open(app, items=16, current=0)
    view = combo.view()
    assert view.verticalScrollBar().maximum() > 0
    visible = combo.maxVisibleItems()
    assert view.height() == sum(view.sizeHintForRow(i)
                                for i in range(visible))
    combo.hidePopup()
    root.close()


def test_current_row_has_a_diamond_and_hover_is_only_a_wash(app):
    from PyQt6.QtGui import QColor
    from PyQt6.QtTest import QTest
    from stream_denoiser.gui import themes
    root, combo = _open(app, items=5, current=1)
    view = combo.view()
    popup = view.window()
    secondary = QColor(themes.get_theme("abyss")["secondary"])
    card = themes.get_theme("abyss")["card"].lower()
    pad = popup.layout().contentsMargins().left() + 1

    def marker_at(row):
        r = view.visualRect(combo.model().index(row, 0))
        img = popup.grab().toImage()
        # diamond sits ~14px into the row, vertically centred
        return img.pixelColor(pad + 14, view.mapTo(popup, r.center()).y())

    cur = marker_at(1)
    assert (abs(cur.red() - secondary.red()) < 8
            and abs(cur.green() - secondary.green()) < 8), cur.name()
    # Hover a *different* row: it washes (colour differs from the card)
    # but gets no diamond.
    row2 = view.visualRect(combo.model().index(2, 0))
    QTest.mouseMove(view.viewport(), row2.center())
    _pump(app, 0.3)
    img = popup.grab().toImage()
    y2 = view.mapTo(popup, row2.center()).y()
    assert img.pixelColor(pad + 30, y2).name() != card      # wash present
    marker = img.pixelColor(pad + 14, y2)
    assert not (abs(marker.red() - secondary.red()) < 8
                and abs(marker.green() - secondary.green()) < 8)
    combo.hidePopup()
    root.close()
