"""ThemeTile paint guards (needs Qt; skipped without it).

Hover/press/select animations must never push tile painting outside the
widget bounds: the swatch is full-bleed, so any growth clips the rounded
corners flat. Regression test for exactly that artifact.
"""
import os

import pytest

pytest.importorskip("PyQt6.QtWidgets")


@pytest.fixture(scope="module")
def app():
    # Headless-safe: prefer offscreen unless the caller chose a platform.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_tile(checked=False):
    from stream_denoiser.gui.widgets.theme_tile import ThemeTile
    tile = ThemeTile(accent="#5fd5eb", background="#0a111e",
                     text_dark="#0a111e", name="Abyss")
    tile.resize(120, 88)
    tile.show()
    tile.setChecked(checked)
    return tile


def _patch(tile, x, y, w, h):
    img = tile.grab().toImage()
    return [img.pixelColor(px, py).getRgb()
            for py in range(y, y + h) for px in range(x, x + w)]


def _brightness(pixels):
    return sum(r + g + b for r, g, b, _a in pixels) / max(1, len(pixels))


def test_hover_only_brightens_unchecked(app):
    """Hover must not move any geometry (growth would clip the corners).

    Edge anti-aliasing legitimately re-blends as the fill brightens, so
    instead of exact pixels we bound the change: fill alpha 110 -> 160
    can shift a channel by at most ~46 levels, while a moved corner arc
    would flip edge pixels by ~200 (covered <-> background).
    """
    tile = _make_tile(checked=False)
    tile._hover = 0.0
    img0 = tile.grab().toImage()
    center0 = _brightness(_patch(tile, 50, 34, 20, 20))
    tile._hover = 1.0
    img1 = tile.grab().toImage()
    assert (img0.width(), img0.height()) == (img1.width(), img1.height())
    peak = 0
    for y in range(img0.height()):
        for x in range(img0.width()):
            c0 = img0.pixelColor(x, y)
            c1 = img1.pixelColor(x, y)
            peak = max(peak, abs(c0.red() - c1.red()),
                       abs(c0.green() - c1.green()),
                       abs(c0.blue() - c1.blue()))
    assert peak <= 50, peak
    # Fill responds to hover (direction depends on what's behind the
    # blend: brighter over dark cards, darker over light ones).
    assert abs(_brightness(_patch(tile, 50, 34, 20, 20)) - center0) > 20


def test_select_overshoot_never_clips(app):
    """Spring overshoot past 1.0 must still render exactly at full size."""
    tile = _make_tile(checked=True)
    tile._select = 1.0
    rest = _patch(tile, 0, 0, 120, 88)
    tile._select = 1.1  # OutBack peak during the selection pop
    assert _patch(tile, 0, 0, 120, 88) == rest


def _ring_pixels(tile):
    """Ring-colored pixels in the top half (name text lives at bottom).

    Scoped above the label because text anti-aliasing fringe can land
    near the ring tone and would otherwise pollute the count.
    """
    from PyQt6.QtGui import QColor
    ring = QColor("#0a111e").lighter(150)
    img = tile.grab().toImage()
    n = 0
    for y in range(img.height() // 2):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if (abs(c.red() - ring.red()) <= 5
                    and abs(c.green() - ring.green()) <= 5
                    and abs(c.blue() - ring.blue()) <= 5):
                n += 1
    return n


def _pump(app, secs=0.5):
    import time
    end = time.time() + secs
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def test_ring_fades_in_and_out_with_selection(app):
    """Ring crossfades both directions instead of snapping."""
    from PyQt6.QtCore import QAbstractAnimation
    tile = _make_tile(checked=False)
    assert _ring_pixels(tile) == 0
    tile.setChecked(True)
    assert tile._sel_anim is not None
    assert tile._sel_anim.state() == QAbstractAnimation.State.Running
    _pump(app)
    assert _ring_pixels(tile) > 30
    tile.setChecked(False)
    assert tile._sel_anim.state() == QAbstractAnimation.State.Running
    _pump(app)
    assert _ring_pixels(tile) == 0
    tile.close()


def test_selection_snaps_under_reduced_motion(app, monkeypatch):
    """No animation objects when motion is off; end states still land."""
    monkeypatch.setenv("POISE_NO_ANIM", "1")
    tile = _make_tile(checked=False)
    tile.setChecked(True)
    assert tile._sel_anim is None
    assert tile._selT == 1.0
    assert _ring_pixels(tile) > 30
    tile.setChecked(False)
    assert tile._selT == 0.0
    assert _ring_pixels(tile) == 0
    tile.close()
