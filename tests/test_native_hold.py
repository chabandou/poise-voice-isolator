"""Native views (the GPU sky's window) held as stills while a page slide
or a crossfade runs: their snapshots cannot see a native window, and it
would draw over their overlays (animations.hold_natives)."""
import os
import time

import pytest

pytest.importorskip("PyQt6.QtWidgets")


@pytest.fixture(scope="module")
def app():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _pump(app, secs=0.2):
    end = time.time() + secs
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


@pytest.fixture
def motion(monkeypatch):
    monkeypatch.delenv("POISE_NO_ANIM", raising=False)
    monkeypatch.delenv("POISE_REDUCE_MOTION", raising=False)


def test_hold_natives_holds_what_is_under_the_roots(app):
    from PyQt6.QtWidgets import QWidget
    from stream_denoiser.gui.animations import hold_natives, register_native

    class Host(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.log = []

        def hold_native(self, reason):
            self.log.append(("hold", reason))

        def release_native(self, reason):
            self.log.append(("release", reason))

    root, other = QWidget(), QWidget()
    inside, outside = Host(QWidget(root)), Host(other)
    register_native(inside)
    register_native(outside)
    release = hold_natives([root], "slide")
    assert inside.log == [("hold", "slide")] and outside.log == []
    release()
    release()                                  # (once)
    assert inside.log == [("hold", "slide"), ("release", "slide")]


def test_a_page_slide_holds_the_views_until_it_lands(app, motion):
    from PyQt6.QtWidgets import QStackedWidget, QWidget
    from stream_denoiser.gui import animations

    class Host(QWidget):
        held = 0

        def hold_native(self, reason):
            Host.held += 1

        def release_native(self, reason):
            Host.held -= 1

    stack = QStackedWidget()
    stack.resize(400, 300)
    first, second = QWidget(), QWidget()
    stack.addWidget(first)
    stack.addWidget(second)
    animations.register_native(Host(first))
    stack.show()
    _pump(app, 0.1)
    animations.slide_stack(stack, 1, duration_ms=120)
    assert Host.held == 1
    _pump(app, 0.4)
    assert Host.held == 0
    animations.slide_stack(stack, 0, duration_ms=500)
    assert Host.held == 1
    animations.slide_stack(stack, 1, duration_ms=500)   # cut short
    _pump(app, 0.8)
    assert Host.held == 0
    stack.close()


def test_a_crossfade_says_when_it_is_done(app, motion, monkeypatch):
    from PyQt6.QtWidgets import QWidget
    from stream_denoiser.gui.animations import crossfade_from
    widget = QWidget()
    widget.resize(200, 100)
    widget.show()
    done = []
    crossfade_from(widget, widget.grab(), 60, on_done=lambda: done.append(1))
    assert not done
    _pump(app, 0.3)
    assert done == [1]
    monkeypatch.setenv("POISE_REDUCE_MOTION", "1")
    crossfade_from(widget, widget.grab(), 60, on_done=lambda: done.append(2))
    assert done == [1, 2]                      # no fade: at once
    widget.close()
