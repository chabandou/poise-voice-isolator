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


def _make_tile(checked=False, theme_id="halcyon", width=120):
    from stream_denoiser.gui.widgets.theme_tile import ThemeTile
    tile = ThemeTile(theme_id)
    tile.resize(width, tile.height())
    tile.show()
    tile.setChecked(checked)
    return tile


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


def test_every_tile_paints_at_its_minimum_width(app):
    """Long names shrink to fit instead of clipping."""
    from stream_denoiser.gui import themes
    from stream_denoiser.gui.widgets.theme_tile import ThemeTile
    narrowest = ThemeTile("halcyon").minimumSizeHint().width()
    for theme_id in themes.theme_ids():
        tile = _make_tile(theme_id=theme_id, width=narrowest)
        tile.grab()
        tile.close()


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
