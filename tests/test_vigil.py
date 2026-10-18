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


def test_live_stars_hold_their_size_and_charge_with_the_disc(app):
    from PyQt6.QtCore import QPointF, QRectF
    from PyQt6.QtGui import QColor
    from stream_denoiser.gui.widgets import sky
    night = sky.NightSky()
    seen = []    # (glow, star scale) per frame
    box = QRectF(0, 0, 900, 520)
    later = sky.BREATH_MS     # the second pulse on (the first lights up)
    cycles = [later + ms for ms in (0, 500, 1000, 4000, 6000, 7000, 7900)]
    for cycle in cycles:
        frame = night.frame(box, QPointF(450, 280), 1.0, 1.0, 1000.0, {
            "live": 1.0, "gather": 0.0, "error": 0.0, "reveal": 1.0,
            "gather_ms": 0.0, "cycle": cycle, "stopped": None,
            "gain": lambda index: 1.0, "moving": True,
            "secondary": QColor("#E6CD8A"), "accent": QColor("#b9a6ff"),
            "accent_light": QColor("#e4dcff")})
        seen.append((frame["glow"], frame["geometry"]["stars_scale"]))
    glow = {cycle - later: g for cycle, (g, _) in zip(cycles, seen)}
    assert all(scale == 1.0 for _, scale in seen)    # no swell with pulses
    assert glow[0] == pytest.approx(1.0)              # full as it leaves
    assert glow[4000] == 0.0                          # gone mid-breath
    assert 0.0 < glow[7000] < glow[7900] < 1.0        # gathering again


def test_the_star_holds_its_size_starting_and_lights_with_the_first_pulse(
        app):
    from PyQt6.QtCore import QPointF, QRectF
    from stream_denoiser.gui.widgets import sky
    night = sky.NightSky()

    def frame(gather_ms, cycle, live):
        look = dict(_idle_look(), live=live, gather=1.0 - live,
                    gather_ms=gather_ms, cycle=cycle)
        return night.frame(QRectF(0, 0, 900, 520), QPointF(450, 280), 1.0,
                           1.0, 1000.0, look)

    for ms in range(0, sky.GATHER_MS, 150):          # loading, switching
        f = frame(ms, None, 0.0)
        assert f["geometry"]["stars_scale"] == 1.0
        assert f["glow"] == 0.0
    assert frame(0.0, None, 0.4)["glow"] == 0.0       # dark until it leaves
    lit = [frame(0.0, ms, 0.4)["glow"]
           for ms in range(0, sky.FIRST_GLOW_MS + 1, 20)]
    assert lit[0] == 0.0 and lit == sorted(lit)       # lights up quickly...
    assert lit[-1] == pytest.approx(1.0, abs=0.02)    # ...full with the pulse


def _idle_look(moving=True):
    from PyQt6.QtGui import QColor
    return {"live": 0.0, "gather": 0.0, "error": 0.0, "reveal": 1.0,
            "gather_ms": 0.0, "cycle": None, "stopped": None,
            "gain": lambda index: 1.0, "moving": moving,
            "secondary": QColor("#E6CD8A"), "accent": QColor("#b9a6ff"),
            "accent_light": QColor("#e4dcff")}


def test_a_shooting_star_crosses_each_span_once(app):
    from stream_denoiser.gui.widgets import sky
    every, span = sky.METEOR_EVERY_MS, sky.METEOR_MS
    starts = []
    for index in range(40):
        start, _ = sky.meteor_flight(index * every + 1.0)
        assert index * every < start < start + span < (index + 1) * every
        assert sky.meteor_flight(start + span / 2)[0] == start
        starts.append(start)
    assert min(b - a for a, b in zip(starts, starts[1:])) > span
    start = starts[5]
    assert sky.meteor_due(start + span / 2)            # crossing
    assert sky.meteor_due(start - 10.0, 33.0)          # about to leave
    assert not sky.meteor_due(start - 100.0, 33.0)
    assert not sky.meteor_due(start + span + 1.0)


# The Home card at 1100 x 720: its sky's box and the dial (centre, k).
_CARD = (1.0, 1.0, 839.0, 478.0)
_DIAL = (420.5, 271.0, 0.94)


def _meteor_at(night, start, u, moving=True):
    from PyQt6.QtCore import QPointF, QRectF
    from stream_denoiser.gui.widgets import sky
    cx, cy, k = _DIAL
    return night.frame(QRectF(*_CARD), QPointF(cx, cy), k, 1.0,
                       start + u * sky.METEOR_MS, _idle_look(moving))["meteor"]


def _trail_length(m):
    """The trail's length along its arc."""
    from stream_denoiser.gui.widgets import sky
    points = [sky.arc_point(m["arc"], m["s0"] + (m["s1"] - m["s0"]) * i / 24)
              for i in range(25)]
    return sum(math.hypot(b.x() - a.x(), b.y() - a.y())
               for a, b in zip(points, points[1:]))


def _first_flight(night):
    from stream_denoiser.gui.widgets import sky
    return next(s for s, _ in (sky.meteor_flight(i * sky.METEOR_EVERY_MS + 1.0)
                               for i in range(30))
                if _meteor_at(night, s, 0.3) is not None)


def test_a_shooting_star_arcs_down_a_side_clear_of_the_dial(app):
    from stream_denoiser.gui.widgets import sky
    night = sky.NightSky()
    width = _CARD[2]
    cx, cy, k = _DIAL
    clear = sky.METEOR_CLEAR * k
    flown = 0
    for index in range(30):
        start, _ = sky.meteor_flight(index * sky.METEOR_EVERY_MS + 1.0)
        if _meteor_at(night, start, 0.3) is None:
            continue                               # no room this time
        flown += 1
        assert _meteor_at(night, start, -0.01) is None   # only in flight
        assert _meteor_at(night, start, 1.0) is None
        assert _meteor_at(night, start, 0.3, moving=False) is None
        frames = [_meteor_at(night, start, i / 40) for i in range(1, 36)]
        frames = [m for m in frames if m is not None]
        for m in frames:                           # clear of dial, headline
            for s in (m["s0"], (m["s0"] + m["s1"]) / 2, m["s1"]):
                point = sky.arc_point(m["arc"], s)
                dx, dy = point.x() - cx, point.y() - cy
                assert math.hypot(dx, dy) > clear - 0.5
                assert abs(dx) > clear - 0.5 or dy > 0
        a, b, c = night._meteor_path[0]
        assert math.hypot(c.x() - a.x(), c.y() - a.y()) >= (
            sky.METEOR_TRAVEL[0] * width - 0.5)
        assert b.y() < (a.y() + c.y()) / 2         # bowed up: an arc
        # Rising into view slowing, then diving faster: the drop per step
        # grows all the way.
        ys = [sky.arc_point((a, b, c), s / 10).y() for s in range(11)]
        drops = [y1 - y0 for y0, y1 in zip(ys, ys[1:])]
        assert drops == sorted(drops) and drops[0] < 0.8 * drops[-1]
        assert max(_trail_length(m) for m in frames) >= 0.2 * width
    assert flown == 30                             # room every time here


def test_a_shooting_star_surfaces_then_dives(app):
    from stream_denoiser.gui.widgets import sky
    night = sky.NightSky()
    start = _first_flight(night)
    at = lambda u: _meteor_at(night, start, u)     # noqa: E731
    us = [i / 50 for i in range(1, 50)]
    frames = [(u, at(u)) for u in us]
    frames = [(u, m) for u, m in frames if m is not None]
    heads = [(u, m["head"]) for u, m in frames]
    peak = max(heads, key=lambda h: h[1])[0]
    assert 0.5 <= peak <= 0.62                     # a late peak...
    rise = next(u for u, h in heads if h > 0.5 * sky.METEOR_ALPHA)
    fall = next(u for u, h in heads if u > peak
                and h < 0.5 * sky.METEOR_ALPHA)
    assert fall - peak < peak - rise               # ...falling away faster
    # Nearer as it surfaces: bigger and whiter; smaller as it dives.
    sizes = {u: m["head_r"] for u, m in frames}
    assert sizes[0.2] < sizes[0.56] > sizes[0.8]
    assert at(0.56)["white"] > at(0.2)["white"]
    # The trail grows as it surfaces and is drawn down after it as it
    # dives, its light lagging the head's.
    lengths = {u: _trail_length(m) for u, m in frames}
    assert lengths[0.2] < lengths[0.6] > lengths[0.84]
    late = at(0.92)
    assert late["head"] == 0.0 and late["colour"].alphaF() > 0
    # The head never stops: an even pace along the arc.
    assert at(0.7)["s1"] == pytest.approx(0.7)
    lit = [sky.meteor_trail_at(t) for t in (0.0, 0.5, 1.0)]
    assert lit[0][0] == 0.0 < lit[1][0] < lit[2][0] == 1.0   # by the head
    assert lit[0][2] < lit[1][2] < lit[2][2] == 1.0           # tapering


def test_the_raster_sky_paints_the_shooting_star(app, monkeypatch):
    from PyQt6.QtCore import QPointF, QRectF, Qt
    from PyQt6.QtGui import QImage, QPainter, QPainterPath
    from stream_denoiser.gui.widgets import sky
    box, (cx, cy, k) = QRectF(*_CARD), _DIAL
    centre = QPointF(cx, cy)
    clip = QPainterPath()
    clip.addRect(box)
    night = sky.NightSky()
    start = _first_flight(night)
    now = start + 0.56 * sky.METEOR_MS             # at its brightest
    head = _meteor_at(night, start, 0.56)["front"]

    def painted():
        image = QImage(842, 481, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.black)
        p = QPainter(image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        night.paint(p, box, clip, centre, k, 1.0, now, _idle_look())
        p.end()
        return image.pixelColor(round(head.x()), round(head.y())).lightness()

    lit = painted()
    monkeypatch.setattr(sky.NightSky, "_meteor",
                        staticmethod(lambda *args: None))
    assert lit > painted() + 40


def test_the_charge_fades_from_where_stop_caught_it(app):
    from stream_denoiser.gui.widgets import sky
    assert sky.charge(None) == 0.0                # dark until the first
    stopped = sky.BREATH_MS * 0.99                # just before a pulse
    held = sky.charge(stopped)
    assert held > 0.9
    after = [sky.charge(stopped + ms, stopped) for ms in range(0, 700, 20)]
    assert after[0] == pytest.approx(held)
    assert after == sorted(after, reverse=True)   # fades, no jump at the
    assert after[-1] == 0.0                       # breath it never takes


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
    dial._nudge_to(-50)
    _pump(app, 0.7)
    dial._nudge_to(-49)                           # both digits change
    assert [len(column) for column in dial._mists] == [2, 2]
    dial.grab()
    _pump(app, 0.7)
    assert [list(column) for column in dial._mists] == [[4], [9]]
    tens = dial._mists[0]
    dial._nudge_to(-48)                           # only the ones change
    assert [len(column) for column in dial._mists] == [1, 2]
    assert dial._mists[0] is tens                 # the tens hold still
    dial.grab()
    _pump(app, 0.7)
    assert [list(column) for column in dial._mists] == [[4], [8]]
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


def test_sky_moves_on_its_own_clock_and_breathes_while_live(app, vigil,
                                                            monkeypatch):
    from stream_denoiser.gui.widgets import pattern_card as pc
    monkeypatch.setattr(pc, "meteor_due", lambda now, ahead=0.0: False)
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


def test_the_clock_speeds_up_for_a_shooting_star(app, vigil, monkeypatch):
    from stream_denoiser.gui.widgets import pattern_card as pc
    due = []
    monkeypatch.setattr(pc, "meteor_due",
                        lambda now, ahead=0.0: bool(due))
    card = _sky_card(app)
    assert card._sky_timer.interval() == pc.SKY_FRAME_MS
    due.append(True)
    card._run_sky()
    assert card._sky_timer.interval() == pc.SKY_METEOR_FRAME_MS
    due.clear()
    card._run_sky()
    assert card._sky_timer.interval() == pc.SKY_FRAME_MS
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
