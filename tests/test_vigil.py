"""Vigil: the night sky behind the dial and the breathing rhythm (Qt)."""
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
def vigil(monkeypatch):
    """Vigil with motion on; the previous theme comes back afterwards."""
    from stream_denoiser.gui import themes
    monkeypatch.delenv("POISE_NO_ANIM", raising=False)
    monkeypatch.delenv("POISE_REDUCE_MOTION", raising=False)
    before = themes.current_id()
    themes.set_current("vigil")
    yield
    themes.set_current(before)


def test_seeded_generator_matches_the_designs_mulberry32(app):
    from stream_denoiser.gui.widgets.sky import _mulberry32
    rand = _mulberry32(0x2F6B1D3)
    # The board's own first values (its JS, run once).
    assert [round(rand(), 12) for _ in range(3)] == [
        0.470087567344, 0.545003595063, 0.823450160213]


# The Home card at 1100 x 720: its sky's box and the dial (centre, k).
_CARD = (1.0, 1.0, 839.0, 478.0)
_DIAL = (420.5, 271.0, 0.94)


# -- the card's night sky --------------------------------------------------------
def _sky_card(app):
    from PyQt6.QtWidgets import QVBoxLayout, QWidget
    from stream_denoiser.gui.widgets.pattern_card import PatternCard
    card = PatternCard()
    card.resize(900, 520)
    origin = QWidget()
    origin.setFixedSize(300, 300)
    QVBoxLayout(card).addWidget(origin)
    card.set_ping_origin(origin)
    card.show()
    _pump(app, 0.05)
    return card


def test_sky_holds_still_under_reduced_motion(app, vigil, monkeypatch):
    monkeypatch.setenv("POISE_REDUCE_MOTION", "1")
    card = _sky_card(app)
    assert not card._sky_timer.isActive()
    card.start_pings()
    assert card._ping_at is None
    card.grab()
    card.close()


def test_switching_to_vigil_swaps_the_backdrop(app, monkeypatch):
    from stream_denoiser.gui import themes
    monkeypatch.delenv("POISE_NO_ANIM", raising=False)
    monkeypatch.delenv("POISE_REDUCE_MOTION", raising=False)
    themes.set_current("halcyon")
    card = _sky_card(app)
    assert not card._sky_timer.isActive()
    try:
        themes.set_current("vigil")
        card.refresh_theme()
        assert card._sky_timer.isActive() and card._reveal.value == 1.0
        themes.set_current("halcyon")
        card.refresh_theme()
        assert not card._sky_timer.isActive()
    finally:
        themes.set_current("halcyon")
        card.close()
