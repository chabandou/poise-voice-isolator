"""Vigil: the night sky behind the dial and the breathing rhythm (Qt)."""
import math
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


# -- the sky's scatter and timelines (no widgets) ------------------------------
def test_scatter_is_the_designs_and_keeps_its_distance(app):
    from stream_denoiser.gui.widgets import sky
    motes, sparkles = sky.scatter()
    again = sky.scatter()[1]
    assert len(motes) == sky.MOTE_COUNT and len(sparkles) == sky.SPARKLE_COUNT
    assert [(s.fx, s.fy) for s in sparkles] == [(s.fx, s.fy) for s in again]
    w, h = sky.DESIGN_CARD
    for i, a in enumerate(sparkles):
        x, y = a.fx * 100, a.fy * 100
        assert ((x - 50) / 24) ** 2 + ((y - 53) / 40) ** 2 >= 1   # dial
        assert not (y < 15 and 22 < x < 78)                       # title
        for b in sparkles[i + 1:]:
            gap = math.hypot((a.fx - b.fx) * w, (a.fy - b.fy) * h)
            assert gap >= sky.SPARKLE_GAP - 1e-6


def test_seeded_generator_matches_the_designs_mulberry32(app):
    from stream_denoiser.gui.widgets.sky import _mulberry32
    rand = _mulberry32(0x2F6B1D3)
    # The board's own first values (its JS, run once).
    assert [round(rand(), 12) for _ in range(3)] == [
        0.470087567344, 0.545003595063, 0.823450160213]


def test_band_arrival_follows_the_band(app):
    from stream_denoiser.gui.widgets import sky
    assert sky.band_arrival(0) == 0.0
    assert sky.band_arrival(sky.BAND_TO + 50) == sky.BAND_MS
    times = [sky.band_arrival(d) for d in range(100, 780, 40)]
    assert times == sorted(times) and 0 < times[0] < times[-1] < sky.BAND_MS


def test_star_outline_draws_what_the_rotated_rect_did(app):
    """The stars' squares are drawn as lines and corner pieces (far
    cheaper rotated): the same pixels as stroking the rect, give or take
    a seam's rounding where the pieces meet."""
    import numpy as np
    from PyQt6.QtCore import QRectF, Qt
    from PyQt6.QtGui import QColor, QImage, QPainter, QPen
    from stream_denoiser.gui.widgets.sky import _square_outline

    def draw(width, pieces):
        image = QImage(420, 420, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        p = QPainter(image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(210, 210)
        p.rotate(17.0)
        pen = QPen(QColor(200, 180, 255, 70), width)
        if pieces:
            flat, brush, edges, corners = _square_outline(150.0, pen)
            p.setPen(flat)
            p.drawLines(edges)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(brush)
            p.drawPath(corners)
        else:
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(-150, -150, 300, 300))
        p.end()
        bits = image.constBits()
        bits.setsize(image.sizeInBytes())
        return np.frombuffer(bits, np.uint8).astype(int)

    for width in (1.0, 4.0, 10.0):
        rect, pieces = draw(width, False), draw(width, True)
        diff = np.abs(rect - pieces)
        assert (rect > 0).sum() > 1000                # something was drawn
        assert diff.max() <= 8, width
        assert (diff > 2).sum() < 0.01 * (rect > 0).sum(), width


def test_keyframes_interpolate_between_frames(app):
    from stream_denoiser.gui.widgets.sky import CHARGE, keyframes
    assert keyframes(0.0, CHARGE) == 1.0          # full as the pulse leaves
    assert keyframes(0.5, CHARGE) == 0.0          # gone mid-breath
    assert 0.0 < keyframes(0.9, CHARGE) < 1.0     # gathering again
    assert keyframes(1.0, CHARGE) == 1.0


# -- the dial on the breathing rhythm --------------------------------------------
def _dial(app):
    from stream_denoiser.gui.widgets.dial import DialButton
    dial = DialButton()
    dial.show()
    _pump(app, 0.05)
    return dial


def test_breath_blooms_from_the_middle_and_tells_its_phase(app, vigil):
    from stream_denoiser.gui.widgets import dial as d
    dial = _dial(app)
    phases = []
    dial.phase_changed.connect(phases.append)
    dial._is_active = True
    dial.set_transitioning(True)
    dial.set_transitioning(False)
    assert phases == ["starting", "live"]
    lit = d.lit_count(dial.strength_db())
    assert dial._ignite_end() == pytest.approx(
        (lit - 1) / 2 * d.BLOOM_STEP + d.BLOOM_CLOSE)
    # Mid-bloom the middle of the arc has bloomed, the ends not yet.
    col = dial._colours(d.current_theme())
    t = (lit - 1) / 2 * d.BLOOM_STEP * 0.5
    middle = dial._breath_look(lit // 2, lit, col, t)
    end = dial._breath_look(0, lit, col, t)
    assert middle[3] > end[3]                     # glowing
    assert end[0].name() == col["gold"].name()   # still gold
    dial.grab()
    dial.close()


def test_breath_charge_rides_the_cycle_and_fades_on_stop(app, vigil):
    from stream_denoiser.gui.widgets import dial as d
    dial = _dial(app)
    dial.set_active(True)
    ign = dial._ignite_end()
    assert dial._charge(ign) == pytest.approx(1.0)              # the pulse
    assert dial._charge(ign + d.BREATH_MS / 2) == 0.0           # mid-breath
    assert 0 < dial._charge(ign + d.BREATH_MS * 0.9) < 1.0     # gathering
    dial._phase_at = time.monotonic() - (ign + 50) / 1000
    charge = dial._charge(dial._ms())
    dial._on_clicked()                                          # Stop
    dial.set_transitioning(True)
    assert dial._charge(dial._ms()) == pytest.approx(charge, abs=0.05)
    _pump(app, d.CHARGE_DROP_MS / 1000 + 0.05)
    assert dial._charge(dial._ms()) == 0.0
    dial.close()


def test_label_and_readout_mist_instead_of_rolling(app, vigil):
    dial = _dial(app)
    dial._is_active = True
    dial.set_transitioning(True)                  # Start -> dots
    assert (dial._label_from, dial._label_to) == (0, 1)
    assert dial._label_mist.value < 1.0
    _pump(app, 0.7)
    assert dial._label_mist.value == pytest.approx(1.0)
    dial.set_transitioning(False)
    dial._nudge_to(dial.strength_db() + 1)        # one step gentler
    assert len(dial._mists) == 2                  # old misting out, new in
    dial.grab()
    _pump(app, 0.9)
    assert list(dial._mists) == [dial.strength_db()]
    dial.close()


def test_tactile_themes_keep_the_odometer_and_ripple(app, monkeypatch):
    from stream_denoiser.gui import themes
    from stream_denoiser.gui.widgets import dial as d
    monkeypatch.delenv("POISE_NO_ANIM", raising=False)
    themes.set_current("abyss")
    dial = _dial(app)
    dial.set_active(True)
    lit = d.lit_count(dial.strength_db())
    assert dial._ignite_end() == lit * d.IGNITE_STEP + d.IGNITE_TAIL
    dial.close()


def test_dial_reuses_its_ring_while_it_holds_still(app, vigil, monkeypatch):
    monkeypatch.setenv("POISE_REDUCE_MOTION", "1")   # idle holds still
    dial = _dial(app)
    drawn = []
    draw = dial._draw_ring
    dial._draw_ring = lambda *a: drawn.append(1) or draw(*a)
    dial._ring_key = None                         # forget the shown frame
    dial.grab()
    dial.grab()
    assert len(drawn) == 1                        # the same strokes: reused
    dial.set_strength_db(dial.strength_db() + 10)
    dial.grab()
    assert len(drawn) == 2                        # fewer ticks lit: redrawn
    dial.close()


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


def test_sky_moves_on_its_own_clock_and_breathes_while_live(app, vigil):
    from stream_denoiser.gui.widgets import pattern_card as pc
    card = _sky_card(app)
    assert card._sky_timer.isActive()            # always gently moving
    assert card._sky_timer.interval() == pc.SKY_FRAME_MS
    card.set_phase("starting")
    card.grab()
    card.set_live(True)
    card.set_phase("live")
    card.start_pings()
    assert card._sky_timer.interval() == pc.SKY_LIVE_FRAME_MS
    assert not card._ping_timer.isActive()       # the lattice stays off
    for ms in (0, 300, 1500, 7800):              # pulse, halos, rest, charge
        card._ping_at = time.monotonic() - ms / 1000
        card.grab()
    card.hide()
    assert not card._sky_timer.isActive()        # nothing to see
    card.close()


def test_stop_fades_the_pulse_in_flight_and_sends_no_more(app, vigil):
    from stream_denoiser.gui.widgets import sky
    card = _sky_card(app)
    card.set_live(True)
    card.start_pings()
    now = time.monotonic()
    assert card._pulse_gain(0, now) == 1.0
    card.stop_pings()
    assert not card.pinging
    assert 0 < card._pulse_gain(0, time.monotonic() + 0.1) < 1.0
    assert card._pulse_gain(1, time.monotonic()) == 0.0   # no next pulse
    card.set_live(False)
    _pump(app, 2.4 + sky.PULSE_FADE_MS / 1000)
    assert card._ping_at is None                 # back to gold: all done
    card.close()


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
    themes.set_current("abyss")
    card = _sky_card(app)
    assert not card._sky_timer.isActive()
    try:
        themes.set_current("vigil")
        card.refresh_theme()
        assert card._sky_timer.isActive() and card._reveal.value == 1.0
        themes.set_current("abyss")
        card.refresh_theme()
        assert not card._sky_timer.isActive()
    finally:
        themes.set_current("abyss")
        card.close()


def test_saved_ultraviolet_opens_as_vigil(app):
    from stream_denoiser.gui.settings import Settings
    settings = Settings()
    before = settings.get(settings.KEY_THEME, None)
    try:
        settings.set(settings.KEY_THEME, "ultraviolet")
        assert settings.theme == "vigil"
    finally:
        settings.set(settings.KEY_THEME, before or "abyss")
