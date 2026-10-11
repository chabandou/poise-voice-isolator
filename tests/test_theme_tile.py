"""ThemeTile paint guards (needs Qt; skipped without it).

The tile is a miniature of its theme (background, wave in the accent,
name in the text colour). Hover/press/select animations must never push
painting outside the widget bounds: the outline sits on the widget edge,
so any growth would clip it flat.
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


@pytest.fixture(autouse=True)
def _abyss_current():
    from stream_denoiser.gui import themes
    prev = themes.current_id()
    themes.set_current("abyss")
    yield
    themes.set_current(prev)


def _make_tile(checked=False, theme_id="abyss", width=120):
    from stream_denoiser.gui.widgets.theme_tile import ThemeTile
    tile = ThemeTile(theme_id)
    tile.resize(width, tile.height())
    tile.show()
    tile.setChecked(checked)
    return tile


def _pump(app, secs=0.5):
    import time
    end = time.time() + secs
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def test_tile_is_a_miniature_of_its_theme(app):
    from stream_denoiser.gui import themes
    for theme_id in themes.theme_ids():
        palette = themes.get_theme(theme_id)
        tile = _make_tile(theme_id=theme_id)
        assert tile._bg.name() == palette["bg"].lower()
        assert tile._accent.name() == palette["accent"].lower()
        assert tile._text.name() == palette["text"].lower()
        assert tile._name == palette["label"]
        assert tile._logo.isValid()
        tile.grab()                       # paints cleanly
        tile.close()


def test_body_is_filled_with_the_theme_background(app):
    from stream_denoiser.gui import themes
    tile = _make_tile(theme_id="verdant")
    img = tile.grab().toImage()
    # A point inside the body, clear of the wave (top-left) and name
    # (bottom-left).
    c = img.pixelColor(tile.width() * 3 // 4, tile.height() // 2)
    assert c.name() == themes.get_theme("verdant")["bg"].lower()
    tile.close()


def test_every_tile_paints_at_its_minimum_width(app):
    """Long names ("Ultraviolet") shrink to fit instead of clipping."""
    from stream_denoiser.gui import themes
    from stream_denoiser.gui.widgets.theme_tile import ThemeTile
    narrowest = ThemeTile("abyss").minimumSizeHint().width()
    for theme_id in themes.theme_ids():
        tile = _make_tile(theme_id=theme_id, width=narrowest)
        tile.grab()
        tile.close()


def _patch(tile, x, y, w, h):
    img = tile.grab().toImage()
    return [img.pixelColor(px, py).getRgb()
            for py in range(y, y + h) for px in range(x, x + w)]


def test_hover_only_touches_the_edge(app):
    """Hover warms the hairline edge; fill and geometry stay put."""
    tile = _make_tile(checked=False)
    tile._hover = 0.0
    img0 = tile.grab().toImage()
    tile._hover = 1.0
    img1 = tile.grab().toImage()
    assert (img0.width(), img0.height()) == (img1.width(), img1.height())
    changed = [(x, y) for y in range(img0.height())
               for x in range(img0.width())
               if img0.pixelColor(x, y) != img1.pixelColor(x, y)]
    assert changed, "hover should be visible"
    band = 12   # outline gap + hairline + rounded-corner sweep
    assert all(x < band or y < band
               or x >= img0.width() - band
               or y >= img0.height() - band
               for x, y in changed), "hover changed more than the edge"
    tile.close()


def test_select_overshoot_never_clips(app):
    """Spring overshoot past 1.0 must still render exactly at full size."""
    tile = _make_tile(checked=True)
    tile._select = 1.0
    w, h = tile.width(), tile.height()
    rest = _patch(tile, 0, 0, w, h)
    tile._select = 1.1  # OutBack peak during the selection pop
    assert _patch(tile, 0, 0, w, h) == rest


def _ring_pixels(tile, color=None):
    """Pixels in a colour (default: the current theme's secondary)."""
    from PyQt6.QtGui import QColor
    from stream_denoiser.gui import themes
    ring = QColor(color or themes.current()["secondary"])
    img = tile.grab().toImage()
    n = 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if (abs(c.red() - ring.red()) <= 5
                    and abs(c.green() - ring.green()) <= 5
                    and abs(c.blue() - ring.blue()) <= 5):
                n += 1
    return n


def test_outline_fades_in_and_out_with_selection(app):
    """Outline crossfades both directions instead of snapping."""
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


def test_outline_uses_the_current_themes_secondary(app):
    from stream_denoiser.gui import themes
    tile = _make_tile(checked=True, theme_id="mono")
    _pump(app)
    abyss_gold = themes.get_theme("abyss")["secondary"]
    ember_teal = themes.get_theme("ember")["secondary"]
    assert _ring_pixels(tile, abyss_gold) > 30
    assert _ring_pixels(tile, ember_teal) == 0
    themes.set_current("ember")
    assert _ring_pixels(tile, ember_teal) > 30
    assert _ring_pixels(tile, abyss_gold) == 0
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
