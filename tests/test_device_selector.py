"""Device selector header guards (needs Qt; skipped without it).

The title label was once added to its header row twice; duplicate
layout items for one widget split its allocation and the title drifted
right (scale/width dependent — only visible with room to spare, hence
the wide + scaled setup here).
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


def _pump(app, secs=0.4):
    end = time.time() + secs
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def _header_layout(selector):
    from PyQt6.QtWidgets import QHBoxLayout
    outer = selector.layout()
    for i in range(outer.count()):
        item = outer.itemAt(i)
        lay = item.layout()
        if isinstance(lay, QHBoxLayout):
            return lay
    raise AssertionError("header row not found")


def test_title_appears_once_and_sits_left(app):
    from stream_denoiser.gui import scaling
    from stream_denoiser.gui.widgets.device_selector import DeviceSelector
    try:
        scaling.set_scale_factor(1.5)
        selector = DeviceSelector("Input Device", "input")
        selector.resize(1055, 90)
        selector.show()
        _pump(app)
        header = _header_layout(selector)
        refs = sum(1 for i in range(header.count())
                   if header.itemAt(i).widget() is selector._label)
        assert refs == 1, "title label must be added exactly once"
        items = [header.itemAt(i).widget() for i in range(header.count())]
        icon = next(w for w in items if w is not None
                    and w is not selector._label)
        gap = selector._label.x() - (icon.x() + icon.width())
        assert gap == header.spacing(), (gap, header.spacing())
    finally:
        scaling.init_scaling()
    selector.close()
