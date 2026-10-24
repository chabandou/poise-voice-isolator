"""Motion: eased state blends, hover fades and the theme crossfade (needs Qt)."""
import os
import time

import pytest

pytest.importorskip("PyQt6.QtWidgets")


@pytest.fixture(scope="module")
def app():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _pump(app, secs=0.3):
    end = time.time() + secs
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


# -- Blend ------------------------------------------------------------------------
def test_blend_glides_then_lands(app):
    from PyQt6.QtCore import QObject
    from stream_denoiser.gui.animations import Blend
    owner = QObject()
    steps = []
    blend = Blend(owner, lambda: steps.append(blend.value), 120)
    blend.set_target(1.0)
    assert blend.running and blend.target == 1.0 and blend.value < 1.0
    _pump(app, 0.35)
    assert blend.value == pytest.approx(1.0) and not blend.running
    # Glided: values in between, read from the steps rather than at a set
    # time (a 50 ms window missed every tick when a GC pass landed in it).
    assert len(steps) > 2 and any(0.0 < v < 1.0 for v in steps)
    blend.set_target(1.0)                # same target: no restart
    assert not blend.running


def test_blend_snaps_under_reduced_motion(app, monkeypatch):
    from PyQt6.QtCore import QObject
    from stream_denoiser.gui.animations import Blend
    monkeypatch.setenv("POISE_NO_ANIM", "1")
    owner = QObject()
    blend = Blend(owner, lambda: None, 200)
    blend.set_target(1.0)
    assert blend.value == 1.0 and not blend.running
    blend.set_target(0.0)
    assert blend.value == 0.0


def test_blend_new_duration_starts_from_where_it_is(app):
    """A glide with a different duration than the last one starts from
    the current value (Qt re-emits a stale value while it's reconfigured:
    a 240 ms run read at 240 of 380 ms said 0.7, a visible jump)."""
    from PyQt6.QtCore import QEasingCurve
    from PyQt6.QtWidgets import QWidget
    from stream_denoiser.gui.animations import Blend
    owner = QWidget()
    seen = []
    blend = Blend(owner, lambda: seen.append(blend.value), 240)
    blend.set_target(1.0)
    _pump(app, 0.4)
    assert blend.value == pytest.approx(1.0)
    seen.clear()
    blend.set_target(0.0, duration_ms=380,
                     easing=QEasingCurve.Type.InOutSine)
    assert blend.value == pytest.approx(1.0)
    _pump(app, 0.03)
    assert seen and min(seen) > 0.9            # eased start, no jump
    _pump(app, 0.5)
    assert blend.value == pytest.approx(0.0)
    # The override was for that glide only.
    blend.set_target(1.0)
    assert blend._anim.duration() == 240
    assert blend._anim.easingCurve().type() == QEasingCurve.Type.OutCubic


# -- theme crossfade --------------------------------------------------------------------------
def _fade_overlays(win):
    from PyQt6.QtWidgets import QLabel
    return [c for c in win.children()
            if isinstance(c, QLabel) and c.pixmap() is not None
            and not c.pixmap().isNull()]


def test_theme_switch_is_instant_under_reduced_motion(app, monkeypatch):
    from stream_denoiser.gui.main_window import MainWindow
    win = MainWindow()
    win.show()
    _pump(app, 0.4)
    original = win.settings.theme
    monkeypatch.setenv("POISE_NO_ANIM", "1")
    target = "verdant" if original != "verdant" else "halcyon"
    win._apply_theme(target)
    assert _fade_overlays(win) == []
    win._apply_theme(original)
    win.close()


# -- TextSwap (status line fades) ----------------------------------------------------
@pytest.fixture()
def shown_label(app, monkeypatch):
    from PyQt6.QtWidgets import QLabel
    monkeypatch.delenv("POISE_NO_ANIM", raising=False)
    monkeypatch.delenv("POISE_REDUCE_MOTION", raising=False)
    label = QLabel("old")
    label.show()
    _pump(app, 0.05)
    yield label
    label.close()


def test_text_swap_is_instant_when_hidden_reduced_or_effect_taken(
        app, shown_label, monkeypatch):
    from PyQt6.QtWidgets import QGraphicsOpacityEffect, QLabel
    from stream_denoiser.gui.animations import TextSwap
    hidden = QLabel("old")
    TextSwap(hidden).set_text("new")
    assert hidden.text() == "new"
    pulse = QGraphicsOpacityEffect(shown_label)    # someone else's fade
    shown_label.setGraphicsEffect(pulse)
    swap = TextSwap(shown_label)
    swap.set_text("new")
    assert shown_label.text() == "new" and not swap.busy
    assert shown_label.graphicsEffect() is pulse   # left alone, no nesting
    shown_label.setGraphicsEffect(None)
    monkeypatch.setenv("POISE_NO_ANIM", "1")
    swap.set_text("instant")
    assert shown_label.text() == "instant"
