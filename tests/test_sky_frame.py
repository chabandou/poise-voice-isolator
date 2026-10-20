"""The night sky's per-frame maths, made cheaper, gives the same frames."""
import os

import pytest

pytest.importorskip("PyQt6.QtWidgets")


@pytest.fixture(scope="module")
def app():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _bezier_as_written(x1, y1, x2, y2):
    """cubic_bezier_fn before its samples were written out inline."""
    cx = 3.0 * x1
    bx = 3.0 * (x2 - x1) - cx
    ax = 1.0 - cx - bx
    cy = 3.0 * y1
    by = 3.0 * (y2 - y1) - cy
    ay = 1.0 - cy - by

    def sx(t):
        return ((ax * t + bx) * t + cx) * t

    def sy(t):
        return ((ay * t + by) * t + cy) * t

    def sdx(t):
        return (3.0 * ax * t + 2.0 * bx) * t + cx

    def fn(progress):
        if progress <= 0.0:
            return 0.0
        if progress >= 1.0:
            return 1.0
        t = progress
        for _ in range(8):
            err = sx(t) - progress
            if abs(err) < 1e-6:
                return sy(t)
            d = sdx(t)
            if abs(d) < 1e-6:
                break
            t -= err / d
        lo, hi, t = 0.0, 1.0, progress
        while lo < hi:
            x = sx(t)
            if abs(x - progress) < 1e-6:
                return sy(t)
            if progress > x:
                lo = t
            else:
                hi = t
            t = (hi - lo) * 0.5 + lo
        return sy(t)

    return fn


def _inputs(n=2003):
    return [i / (n - 1) for i in range(n)] + [-0.1, 1.2, 1e-9, 1 - 1e-9]


@pytest.mark.parametrize("curve", [
    (0.45, 0.0, 0.25, 1.0), (0.3, 0.6, 0.2, 1.0), (0.42, 0.0, 1.0, 1.0),
    (0.2, 0.8, 0.3, 1.0), (0.4, 0.0, 0.65, 1.0), (0.34, 1.56, 0.64, 1.0)])
def test_the_inline_bezier_gives_the_same_values(curve):
    from stream_denoiser.gui.animations import cubic_bezier_fn
    fast, slow = cubic_bezier_fn(*curve), _bezier_as_written(*curve)
    assert all(fast(u) == slow(u) for u in _inputs())


def test_paired_tracks_share_their_timing_and_values(app):
    from stream_denoiser.gui.widgets import sky
    pairs = [sky.TWINKLE, sky.FLASH, sky.AURA_IDLE, sky.AURA_GATHER,
             sky.AURA_LIVE]
    for first, second in pairs:
        assert [(a, e) for a, _, e in first] == [(a, e) for a, _, e in second]
        for u in _inputs(997):
            assert sky.keyframes2(u, first, second) == (
                sky.keyframes(u, first), sky.keyframes(u, second))


def _frames():
    from PyQt6.QtCore import QPointF, QRectF
    from PyQt6.QtGui import QColor
    from stream_denoiser.gui.widgets import sky
    night = sky.NightSky()
    box, centre = QRectF(1.5, 1.5, 909.0, 404.0), QPointF(456.0, 223.0)
    for now, live, cycle in ((1234.5, 0.0, None), (9876.0, 1.0, 1200.0),
                             (47000.0, 0.6, 9300.0)):
        look = {"live": live, "gather": 0.0, "error": 0.0, "reveal": 1.0,
                "gather_ms": 0.0, "cycle": cycle, "stopped": None,
                "moving": True, "gain": lambda i: 1.0,
                "secondary": QColor("#d8b56a"), "accent": QColor("#9a8cff"),
                "accent_light": QColor("#c9c1ff")}
        yield night.frame(box, centre, 1.12, 1.0, now, look), box


def test_motes_and_sparkles_carry_alphas_the_painters_turn_to_colour(app):
    """The QPainter sky makes their colours with _alpha from the frame's
    tones; the GPU sky's uniforms carry the same alphas as those colours
    hold (Qt keeps alpha in 16 bits: so do they)."""
    from PyQt6.QtGui import QVector4D
    pytest.importorskip("PyQt6.QtQuickWidgets")
    from stream_denoiser.gui.widgets import sky
    from stream_denoiser.gui.widgets.sky_gpu import frame_uniforms
    for frame, box in _frames():
        u = frame_uniforms(frame, box)
        for key, tone, entries in (
                ("m", frame["mote_tone"], frame["motes"]),
                ("s", frame["sparkle_tone"], frame["sparkles"])):
            assert entries
            for i, entry in enumerate(entries):
                glow, alpha = entry[3 if key == "s" else 2], entry[4]
                assert isinstance(glow, float) and isinstance(alpha, float)
                colour = sky._alpha(tone, alpha)
                assert u[f"{key}{i}"].w() == QVector4D(
                    0, 0, 0, colour.alphaF()).w()
