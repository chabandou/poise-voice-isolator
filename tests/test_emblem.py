"""The About emblem and its easter egg, the seal (widgets/emblem.py).

A click unwinds the dial, locks a rub el hizb in around the face and
writes تَمَّ بِحَمْدِ اللَّهِ inside it from the bottom up; another click
brings the dial back. The pen's paths are baked into assets/seal by
tools/bake_seal_pen.py.
"""
import glob
import math
import os
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


def _gold_pixels(widget, colour) -> int:
    """Pixels close to `colour` in the middle of the emblem."""
    img = widget.grab().toImage()
    s = img.width()
    count = 0
    for y in range(int(s * 0.3), int(s * 0.7), 2):
        for x in range(int(s * 0.3), int(s * 0.7), 2):
            c = img.pixelColor(x, y)
            if (abs(c.red() - colour.red()) < 40 and abs(c.green() - colour.green()) < 40
                    and abs(c.blue() - colour.blue()) < 40):
                count += 1
    return count


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


def test_every_theme_icon_splits_into_wave_and_dashes():
    folder = os.path.join(os.path.dirname(E.SEAL_DIR))
    icons = glob.glob(os.path.join(folder, "icon*.svg"))
    assert icons
    for path in icons:
        with open(path, encoding="utf-8") as f:
            parts = E._icon_parts(f.read())
        assert parts is not None, path
        wave, dashes = parts
        assert "C" in wave.split(' d="')[1].split('"')[0]
        assert dashes.split(' d="')[1].split('"')[0].count("M") == 4


def test_the_squares_lock_without_a_jump_in_speed(emblem):
    """The detent catches a square at full speed: its angular velocity
    is the same just before and just after the lock, it runs on past its
    seat by about LOCK_PEAK and settles there."""
    start, end = E.SEAL["sq1"]
    angle = lambda t: emblem._square_in(t, (start, end), 0.0, 1)[0]  # noqa: E731
    before = (angle(end) - angle(end - 0.5)) / 0.5
    after = (angle(end + 0.5) - angle(end)) / 0.5
    assert before > 0 and after == pytest.approx(before, rel=0.1)
    peak = max(angle(end + t) for t in range(0, 120))
    assert peak == pytest.approx(E.LOCK_PEAK, rel=0.05)
    assert abs(angle(end + 400)) < math.radians(0.1)
    # And it never crawls on the way in.
    assert before > 0.5 * E.SPIN / (end - start)


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


def test_leaving_the_page_shows_the_plain_emblem_again(app, emblem):
    emblem.seek("seal", emblem.seal_ms())
    emblem.hide()
    app.processEvents()
    emblem.show()
    assert emblem.state() == "rest"


def test_the_lettering_shows_only_once_written(app, emblem):
    from PyQt6.QtGui import QColor
    from stream_denoiser.gui.themes import current
    gold = QColor(current()["secondary"])
    assert _gold_pixels(emblem, gold) == 0
    emblem.seek("seal", E.SEAL["write"] - 10)
    assert _gold_pixels(emblem, gold) == 0
    emblem.seek("seal", emblem.seal_ms())
    sealed = _gold_pixels(emblem, gold)
    assert sealed > 50
    # Half way through, part of it.
    pen = E.load_pen()
    emblem.seek("seal", E.SEAL["write"] + pen.duration / 2)
    assert 0 < _gold_pixels(emblem, gold) < sealed
    # Scrubbing back clears what was written after.
    emblem.seek("seal", E.SEAL["write"] + 5)
    assert _gold_pixels(emblem, gold) < sealed / 4


def test_every_frame_paints(app, emblem):
    """Both sequences, a frame every 60 ms, in two themes."""
    from stream_denoiser.gui import themes
    from stream_denoiser.gui.utils import get_icon_path
    saved = themes.current_id()
    try:
        for theme in ("halcyon", "eclipse"):
            themes.set_current(theme)
            emblem.set_icon(get_icon_path(theme))
            for t in range(0, int(emblem.seal_ms()) + 60, 60):
                emblem.seek("seal", t)
                assert not emblem.grab().isNull()
            for t in range(0, E.RESTORE_MS + 60, 60):
                emblem.seek("restore", t)
                assert not emblem.grab().isNull()
    finally:
        themes.set_current(saved)
