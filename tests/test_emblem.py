"""The About emblem and its easter egg, the seal (widgets/emblem.py).

A click unwinds the dial, locks a rub el hizb in around the face and
writes تَمَّ بِحَمْدِ اللَّهِ inside it from the bottom up; another click
brings the dial back. The pen's paths are baked into assets/seal by
tools/bake_seal_pen.py.
"""
import time

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from stream_denoiser.gui.widgets import emblem as E  # noqa: E402


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _pump(app, secs=0.2):
    end = time.time() + secs
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


@pytest.fixture()
def emblem(app):
    from stream_denoiser.gui.utils import get_icon_path
    w = E.Emblem(size=260)
    w.set_icon(get_icon_path())
    w.show()
    app.processEvents()
    yield w
    from PyQt6.QtCore import QCoreApplication, QEvent
    w.hide()
    w.deleteLater()
    # processEvents alone leaves deferred deletes for a later test's loop.
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_the_baked_pen_is_complete():
    pen = E.load_pen()
    assert pen is not None
    assert len(pen.points) > 500 and pen.duration > 2000
    assert pen.times == sorted(pen.times)            # writing order
    assert pen.times[-1] <= pen.duration + 0.1
    # Every letter group settles, once, while the pen is writing.
    assert sorted(part for _t, part in pen.settles) == list(range(len(pen.parts)))
    assert all(0 <= t <= pen.duration + 0.1 for t in pen.settle_times)
    for src, dst in pen.parts:
        assert src.right() <= pen.atlas.width() and src.bottom() <= pen.atlas.height()
        assert 0 <= dst.left() and dst.right() <= pen.text_space
    # It writes from the bottom up: تَمَّ (the lowest line) first.
    first = pen.points[: len(pen.points) // 8]
    last = pen.points[-len(pen.points) // 8:]
    assert sum(p[1] for p in first) / len(first) > sum(p[1] for p in last) / len(last)


def test_a_click_seals_and_another_brings_the_dial_back(app, emblem):
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtTest import QTest
    centre = emblem.rect().center()
    QTest.mouseClick(emblem, Qt.MouseButton.LeftButton, pos=centre)
    assert emblem.state() == "sealing"
    _pump(app, 0.25)
    assert emblem._t > 100                    # its clock runs
    QTest.mouseClick(emblem, Qt.MouseButton.LeftButton, pos=centre)
    assert emblem.state() == "sealing"        # clicks wait for the seal
    emblem.seek("seal", emblem.seal_ms())
    assert emblem.state() == "sealed"
    emblem.press()
    assert emblem.state() == "restoring"
    emblem.seek("restore", E.RESTORE_MS - 1)
    emblem._playing = True
    emblem._last = time.perf_counter() - 0.02
    emblem._tick()
    assert emblem.state() == "rest"
    # A click outside the ring does nothing.
    QTest.mouseClick(emblem, Qt.MouseButton.LeftButton, pos=QPointF(2, 2).toPoint())
    assert emblem.state() == "rest"


def test_with_reduce_motion_a_click_swaps_at_once(app, emblem):
    """No sequence: the other state at once, the old one fading off it."""
    from stream_denoiser.gui import animations
    animations.set_still(True)
    emblem.press()
    assert emblem.state() == "sealed" and emblem._swap is not None
    _pump(app, (E.SWAP_MS + 150) / 1000)
    assert emblem._swap is None
    emblem.press()
    assert emblem.state() == "rest"


def _beats(spans, total):
    """A frame inside and at the end of every beat, and the last one."""
    times = {0.0, float(total)}
    for value in spans.values():
        if isinstance(value, tuple):
            times.update((value[0] + 1, (value[0] + value[1]) / 2, value[1] + 1))
    return sorted(t for t in times if t <= total)


def test_every_beat_paints(app, emblem):
    """Both sequences, a few frames in each beat, in two themes."""
    from PyQt6.QtGui import QImage, QPainter
    from stream_denoiser.gui import themes
    from stream_denoiser.gui.utils import get_icon_path
    pen = E.load_pen()
    seal = _beats(E.SEAL, emblem.seal_ms())
    seal += [E.SEAL["write"] + pen.duration * f for f in (0.25, 0.5, 0.75)]
    restore = _beats(E.RESTORE, E.RESTORE_MS)
    canvas = QImage(emblem.size(), QImage.Format.Format_ARGB32_Premultiplied)
    saved = themes.current_id()
    try:
        for theme in ("halcyon", "eclipse"):
            themes.set_current(theme)
            emblem.set_icon(get_icon_path(theme))
            for mode, times in (("seal", sorted(seal)), ("restore", restore)):
                for t in times:
                    emblem.seek(mode, t)
                    canvas.fill(0)
                    painter = QPainter(canvas)
                    emblem.render(painter)
                    painter.end()
    finally:
        themes.set_current(saved)
