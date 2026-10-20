"""The dial card's lattices (widgets/lattice.py, pattern_card.py): the
polygons-in-contact geometry, and each theme's pattern centred on the
dial."""
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


@pytest.fixture
def theme():
    """Set a theme for one test; the default comes back after it."""
    from stream_denoiser.gui import themes
    yield themes.set_current
    themes.set_current(themes.DEFAULT_THEME)


def _pump(app, secs=0.05):
    end = time.time() + secs
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def _card(app, size=(600, 400)):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QVBoxLayout, QWidget
    from stream_denoiser.gui.widgets.pattern_card import PatternCard
    card = PatternCard()
    card.resize(*size)
    origin = QWidget()
    origin.setFixedSize(100, 100)
    QVBoxLayout(card).addWidget(origin, alignment=Qt.AlignmentFlag.AlignCenter)
    card.set_ping_origin(origin)
    card.show()
    _pump(app)
    return card, origin


def test_hankin_draws_a_star_in_a_regular_octagon():
    """Every ray starts at an edge's middle, and in a regular polygon
    they all meet the same distance from its centre: a regular star."""
    from stream_denoiser.gui.widgets import lattice
    octagon = lattice._regular(0.0, 0.0, 8, 10.0, math.pi / 8)
    lines = lattice.hankin(octagon, 67.5)
    assert len(lines) == 8
    apothem = 10.0 * math.cos(math.pi / 8)
    inner = {round(math.hypot(*p), 6) for _, p, _ in lines}
    assert len(inner) == 1 and 0 < inner.pop() < apothem
    for m1, _, m2 in lines:
        assert math.hypot(*m1) == pytest.approx(apothem)
        assert math.hypot(*m2) == pytest.approx(apothem)
    # Either winding gives the same star.
    assert len(lattice.hankin(octagon[::-1], 67.5)) == 8


def test_each_lattice_theme_names_a_known_pattern():
    from stream_denoiser.gui import themes
    from stream_denoiser.gui.widgets import lattice
    expected = {"halcyon": "rub_el_hizb", "verdant": "khatam",
                "ember": "twelve", "orchid": "dome"}
    for tid, kind in expected.items():
        assert themes.style("backdrop", tid) == "lattice"
        assert themes.style("lattice", tid) == kind
        assert kind in lattice.SPECS
    for kind in ("khatam", "twelve"):
        assert not lattice.tile_path(kind).isEmpty()


@pytest.mark.parametrize("tid", ["verdant", "ember", "orchid"])
def test_islamic_lattices_are_centred_on_the_dial(app, theme, tid):
    """Each is mirror-symmetric about the dial: drawn bare, the left of
    the dial is the right of it reflected."""
    theme(tid)
    card, origin = _card(app)
    centre = card._ping_centre()
    image = card._lattice(card.width(), card.height(), masked=False)
    assert image.devicePixelRatio() == 1.0
    cx, cy = round(centre.x()), round(centre.y())
    reach = min(200, cx - 10, card.width() - cx - 10)
    assert reach > 150 and 130 < cy < card.height() - 130
    ink = diff = 0
    for y in range(cy - 120, cy + 120, 3):
        for d in range(reach):
            a = image.pixelColor(cx + d, y).alpha()
            b = image.pixelColor(cx - 1 - d, y).alpha()
            ink += a
            diff += abs(a - b)
    assert ink > 0
    assert diff < 0.05 * ink
    card.close()


def test_a_centred_lattice_follows_the_dial(app, theme):
    """The dial moves (a line appears above it, the card resizes): the
    lattice is redrawn round its new place, not left where it was."""
    theme("verdant")
    card, origin = _card(app)
    card.grab()
    before = card._layer_key
    assert before[5] is not None
    card.layout().setContentsMargins(0, 120, 0, 0)
    _pump(app)
    card.grab()
    after = card._layer_key
    assert after[5] != before[5]
    centre = card._ping_centre()
    assert after[5] == (round(centre.x(), 1), round(centre.y(), 1))
    card.close()


def test_switching_lattice_themes_redraws_the_card(app, theme):
    card, _ = _card(app)
    kinds = []
    for tid in ("halcyon", "verdant", "ember", "orchid", "halcyon"):
        theme(tid)
        card.refresh_theme()
        card.grab()
        kinds.append(card._layer_key[4])
    assert kinds == ["rub_el_hizb", "khatam", "twelve", "dome",
                     "rub_el_hizb"]
    # The first lattice keeps its fixed place, whatever the dial does.
    assert card._layer_key[5] is None
    card.close()


def test_pings_light_the_new_lattices(app, theme, monkeypatch):
    monkeypatch.delenv("POISE_NO_ANIM", raising=False)
    monkeypatch.delenv("POISE_REDUCE_MOTION", raising=False)
    for tid in ("verdant", "ember", "orchid"):
        theme(tid)
        card, _ = _card(app)
        card.set_live(True)
        card.start_pings()
        card._ping_at -= 0.4                       # a ring part-way out
        assert card._ping_frame() is not None
        card.grab()
        assert card._ping_key is not None
        card.set_live(False, animated=False)
        card.close()
