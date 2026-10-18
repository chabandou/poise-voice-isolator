"""Reduce motion in Settings: the ambient motion holds still.

The sky, the dial's loops and the live halo stop (and the GPU sky view
goes, with the memory it holds); short hover and click feedback stays.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("PyQt6.QtWidgets")

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def app():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _pump(app, secs=0.3):
    end = time.time() + secs
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


@pytest.fixture()
def still_reset():
    from stream_denoiser.gui import animations
    yield animations
    animations.set_still(False)


def test_only_the_ambient_motion_holds_still(still_reset):
    animations = still_reset
    animations.set_still(True)
    assert not animations.ambient_ok()
    assert animations.motion_ok()           # hover and click feedback stay
    animations.set_still(False)
    assert animations.ambient_ok()


def test_the_default_follows_windows_animation_effects(app, monkeypatch):
    from stream_denoiser.gui import settings as settings_mod
    s = settings_mod.get_settings()
    saved = (s.get(s.KEY_REDUCE_MOTION)
             if s.contains(s.KEY_REDUCE_MOTION) else None)
    try:
        s.remove(s.KEY_REDUCE_MOTION)
        monkeypatch.setattr(settings_mod, "system_animations", lambda: True)
        assert s.reduce_motion is False
        monkeypatch.setattr(settings_mod, "system_animations", lambda: False)
        assert s.reduce_motion is True
        s.reduce_motion = False                 # chosen here: that wins
        assert s.reduce_motion is False
    finally:
        if saved is None:
            s.remove(s.KEY_REDUCE_MOTION)
        else:
            s.set(s.KEY_REDUCE_MOTION, saved)


@pytest.fixture()
def window(app, still_reset):
    from stream_denoiser.gui.main_window import MainWindow
    win = MainWindow()
    win.resize(1180, 760)
    win.show()
    _pump(app)
    saved = win.settings.reduce_motion
    win.restarts = []                      # no real restart in tests
    win.restart_app = lambda: win.restarts.append(1)
    yield win
    win.motion_switch.setChecked(saved)
    win.close()


def test_the_switch_holds_home_still_and_lets_it_go(app, window):
    from stream_denoiser.gui.animations import ambient_ok
    window.motion_switch.setChecked(False)
    _pump(app, 0.1)
    row = window.motion_switch.parentWidget()
    assert "Lowers CPU, GPU and memory use" in row.toolTip()

    window.motion_switch.setChecked(True)
    _pump(app, 0.1)
    assert window.settings.reduce_motion is True
    assert not ambient_ok()
    assert not window.power_btn._clock.isActive()
    assert not window._stage._sky_timer.isActive()
    assert not window._stage._ping_timer.isActive()
    assert window._stage._view is None
    # Starting holds still too: no pulses, no halo.
    window.stats_bar.show_status("processing")
    window._stage.start_pings()
    window.power_btn._run_clock()
    _pump(app, 1.0)                        # past a queued status step
    assert window.stats_bar._shown[0] == "processing"
    assert not window._stage.pinging
    assert not window.stats_bar._halo.isActive()
    assert not window.power_btn._clock.isActive()

    window.motion_switch.setChecked(False)
    _pump(app, 0.1)
    assert window.settings.reduce_motion is False
    assert ambient_ok()


def test_the_switch_restarts_poise(app, window):
    window.motion_switch.setChecked(not window.motion_switch.isChecked())
    _pump(app, 0.1)
    assert window.restarts == []           # the switch is seen to flip
    _pump(app, 0.4)
    assert window.restarts == [1]
    row = window.motion_switch.parentWidget()
    assert "restarts" in row._subtitle


def test_a_restart_comes_back_where_it_was(app, monkeypatch):
    import stream_denoiser.gui as gui
    monkeypatch.setattr(sys, "argv", ["C:/poise/run_poise_gui.py",
                                      "--log-file", "x.log",
                                      gui.FLAG_RESTART_RESUME])
    monkeypatch.setattr(gui, "_restart_args", None)
    gui.request_restart(resume=False)
    program, args = gui._restart_command(gui._restart_args)
    assert program == sys.executable
    assert args == [os.path.abspath("C:/poise/run_poise_gui.py"),
                    "--log-file", "x.log", gui.FLAG_RESTART_SETTINGS]
    gui.request_restart(resume=True)
    assert gui._restart_args[-2:] == [gui.FLAG_RESTART_SETTINGS,
                                      gui.FLAG_RESTART_RESUME]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    program, args = gui._restart_command(["--x"])
    assert (program, args) == (sys.executable, ["--x"])


def test_a_restarted_window_opens_on_settings(app, window, monkeypatch):
    started = []
    monkeypatch.setattr(window, "_start_processing",
                        lambda: started.append(1))
    window.resume_after_restart(settings_page=True, isolate=True)
    _pump(app, 0.1)
    assert window.stack.currentIndex() == 1
    assert started == [1]


def test_reset_keeps_the_motion_setting(app, window):
    window.motion_switch.setChecked(True)
    window.reset_to_defaults()
    assert window.motion_switch.isChecked()
    assert window.settings.reduce_motion is True


def test_the_still_sky_is_painted_once(app, still_reset, monkeypatch):
    from PyQt6.QtWidgets import QVBoxLayout, QWidget
    from stream_denoiser.gui import themes
    from stream_denoiser.gui.widgets.pattern_card import PatternCard
    still_reset.set_still(True)
    before = themes.current_id()
    themes.set_current("vigil")
    try:
        card = PatternCard()
        card.resize(900, 520)
        origin = QWidget()
        origin.setFixedSize(300, 300)
        QVBoxLayout(card).addWidget(origin)
        card.set_ping_origin(origin)
        card.show()
        _pump(app, 0.1)
        assert card._view is None and not card._view_failed
        card.grab()
        kept = card._still
        assert kept is not None
        card.grab()                        # a hover over the dial repaints
        assert card._still is kept
        card.set_live(True)                # what it shows changed
        card.grab()
        assert card._still is not kept
        card.close()
    finally:
        themes.set_current(before)


_GPU_CHECK = """
import sys, tempfile, time
sys.path.insert(0, {root!r})
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                  tempfile.mkdtemp(prefix="poise-test-config-"))
app = QApplication([])
from stream_denoiser.gui.settings import get_settings
s = get_settings()
s.theme = "vigil"
s.reduce_motion = True
s.minimize_to_tray_asked = True
from stream_denoiser.gui.main_window import MainWindow
win = MainWindow()
win.show()
def pump(secs):
    end = time.time() + secs
    while time.time() < end:
        app.processEvents()
pump(1.0)
loaded = "stream_denoiser.gui.widgets.sky_gpu" in sys.modules
print("still", loaded, win._stage._view is None)
win.motion_switch.setChecked(False)
pump(2.0)
view = win._stage._view
if view is None:
    print("skip: no GPU sky here")
    sys.exit(0)
print("moving", win.power_btn._ring_sink is not None)
win.motion_switch.setChecked(True)
pump(0.5)
print("again", win._stage._view is None, win.power_btn._ring_sink is None)
sys.stdout.flush()
"""


@pytest.mark.skipif(sys.platform != "win32", reason="the GPU sky's home")
def test_the_gpu_sky_goes_and_comes_back():
    """On the real platform (offscreen has no GPU API): started with
    Reduce motion, Qt Quick never loads; the switch brings the GPU sky
    (and its dial ring) back and takes them away again."""
    env = dict(os.environ, QT_QPA_PLATFORM="windows")
    run = subprocess.run(
        [sys.executable, "-c", _GPU_CHECK.format(root=str(ROOT))],
        capture_output=True, text=True, timeout=120, env=env)
    out = run.stdout.strip().splitlines()
    assert run.returncode == 0 and out, run.stderr[-2000:]
    assert out[0] == "still False True", out
    if out[-1].startswith("skip:"):
        pytest.skip(out[-1][6:])
    assert out[1:] == ["moving True", "again True True"], out
