"""TUI settings kept across sessions: model, output device, AAD threshold.

The file tests need nothing; the app tests run the TUI headless with the
audio process, engine loading and Pulse replaced by stand-ins.
"""
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

# The TUI is Linux-only and so is Textual (requirements.txt); importing
# stream_denoiser.tui loads the Textual app.
pytest.importorskip("textual.app")

from stream_denoiser.constants import DEFAULT_MODEL, MODEL_RNNOISE  # noqa: E402
from stream_denoiser.tui.settings import TuiSettings, settings_path  # noqa: E402


@pytest.fixture
def config_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data))


def test_path_follows_xdg_config_home(config_home):
    assert settings_path() == config_home / "poise" / "tui.json"


def test_path_without_xdg_is_under_home(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert settings_path() == tmp_path / ".config" / "poise" / "tui.json"


def test_no_file_gives_no_values(config_home):
    s = TuiSettings()
    assert (s.model, s.output_device, s.aad_threshold_db) == (None, None, None)


def test_values_survive_a_new_session(config_home):
    s = TuiSettings()
    s.model = MODEL_RNNOISE
    s.output_device = "alsa_output.usb-headset"
    s.aad_threshold_db = -55.0
    again = TuiSettings()
    assert again.model == MODEL_RNNOISE
    assert again.output_device == "alsa_output.usb-headset"
    assert again.aad_threshold_db == -55.0
    assert not list(settings_path().parent.glob("*.tmp"))


@pytest.mark.parametrize("content", ["{not json", "[1, 2]", ""])
def test_malformed_file_gives_no_values(config_home, content):
    write(settings_path(), content)
    s = TuiSettings()
    assert (s.model, s.output_device, s.aad_threshold_db) == (None, None, None)
    s.aad_threshold_db = -30.0  # and saving replaces it
    assert TuiSettings().aad_threshold_db == -30.0


def test_bad_values_are_ignored_and_out_of_range_clamped(config_home):
    write(settings_path(), {"model": "nope", "output_device": 3,
                            "aad_threshold_db": True})
    s = TuiSettings()
    assert (s.model, s.output_device, s.aad_threshold_db) == (None, None, None)
    write(settings_path(), {"aad_threshold_db": -200})
    assert TuiSettings().aad_threshold_db == -80.0


def test_unknown_keys_are_kept(config_home):
    write(settings_path(), {"future": 1})
    TuiSettings().model = MODEL_RNNOISE
    assert json.loads(settings_path().read_text())["future"] == 1


def test_unwritable_location_does_not_raise(tmp_path, monkeypatch):
    blocker = tmp_path / "file"
    blocker.write_text("")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(blocker))  # a file, not a dir
    s = TuiSettings()
    s.model = MODEL_RNNOISE
    assert s.model == MODEL_RNNOISE  # kept for this session


# --- the app ---------------------------------------------------------------

SINKS = [("alsa_output.speakers", "Speakers"),
         ("alsa_output.usb-headset", "USB Headset")]
DEFAULT_SINK = "alsa_output.speakers"


@pytest.fixture
def make_app(config_home, monkeypatch):
    from stream_denoiser.backends.platform import linux
    from stream_denoiser.tui import app as app_mod

    sinks = [linux.PulseAudioSink(index=i, name=n, description=d,
                                  sample_rate=48000, channels=2)
             for i, (n, d) in enumerate(SINKS)]
    monkeypatch.setattr(linux, "list_pulseaudio_sinks", lambda: list(sinks))
    monkeypatch.setattr(linux, "get_default_sink_name", lambda: DEFAULT_SINK)
    monkeypatch.setattr(app_mod.AudioHost, "launch", lambda self: None)
    monkeypatch.setattr(app_mod.PoiseApp, "_setup_logging", lambda self: None)
    monkeypatch.setattr(app_mod.PoiseApp, "_setup_cleanup_handlers",
                        lambda self: None)
    monkeypatch.setattr(app_mod.PoiseApp, "_load_model",
                        lambda self: setattr(self, "engine", True))
    # Both engines count as installed, whatever this machine has.
    import stream_denoiser.engines as engines
    monkeypatch.setattr(engines, "model_unavailable_reason", lambda name: None)
    yield app_mod.PoiseApp
    from stream_denoiser.tui import palette
    palette.apply()  # module state: the next test starts on the default


def run(app, steps):
    async def main():
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            await steps(app, pilot)
    asyncio.run(main())


def panels(app):
    from stream_denoiser.tui.widgets import DeviceList, IsolationPanel
    return (app.query_one("#device-panel", DeviceList),
            app.query_one("#isolation-panel", IsolationPanel))


def test_first_start_uses_defaults(make_app):
    async def steps(app, pilot):
        devices, isolation = panels(app)
        assert app.model == DEFAULT_MODEL
        assert devices.selected_device == DEFAULT_SINK
        assert isolation.threshold_db == -40.0
        assert isolation.strength_db == -50.0
    run(make_app(), steps)
    # Nothing chosen, so only the first-launch notice is remembered.
    assert json.loads(settings_path().read_text()) == {"disclaimer_shown": True}


def test_music_disclaimer_shows_on_first_start_only(make_app):
    shown = []

    async def steps(app, pilot):
        shown.append(len(app._notifications))
    run(make_app(), steps)
    run(make_app(), steps)
    assert shown == [1, 0]


def test_saved_choices_are_restored(make_app):
    write(settings_path(), {"model": MODEL_RNNOISE,
                            "output_device": "alsa_output.usb-headset",
                            "aad_threshold_db": -60.0,
                            "atten_lim_db": -25.0})

    async def steps(app, pilot):
        devices, isolation = panels(app)
        assert app.model == MODEL_RNNOISE
        assert devices.selected_device == "alsa_output.usb-headset"
        assert isolation.threshold_db == -60.0
        assert isolation.strength_db == -25.0
        shown = str(isolation.query_one("#isolation-body").render())
        assert "-60 dB" in shown and "-25 dB" in shown
    run(make_app(), steps)


def test_explicit_model_wins_for_this_session_only(make_app):
    write(settings_path(), {"model": DEFAULT_MODEL})

    async def steps(app, pilot):
        assert app.model == MODEL_RNNOISE
    run(make_app(model=MODEL_RNNOISE), steps)
    assert TuiSettings().model == DEFAULT_MODEL


def test_saved_model_no_longer_installed_falls_back(make_app, monkeypatch):
    import stream_denoiser.engines as engines
    monkeypatch.setattr(engines, "model_unavailable_reason",
                        lambda name: "gone" if name == MODEL_RNNOISE else None)
    write(settings_path(), {"model": MODEL_RNNOISE})

    async def steps(app, pilot):
        assert app.model == DEFAULT_MODEL
    run(make_app(), steps)
    assert TuiSettings().model == MODEL_RNNOISE  # back when reinstalled


def test_missing_saved_device_falls_back_but_stays_saved(make_app):
    write(settings_path(), {"output_device": "bluez_output.unplugged"})

    async def steps(app, pilot):
        devices, _ = panels(app)
        assert devices.selected_device == DEFAULT_SINK
    run(make_app(), steps)
    assert TuiSettings().output_device == "bluez_output.unplugged"


def test_changes_are_saved(make_app):
    async def steps(app, pilot):
        await pilot.press("minus", "minus")
        # Box 2 has focus: left on strength is gentler (a higher limit).
        await pilot.press("2", "left")
        devices, _ = panels(app)
        devices.query_one("#device-list").focus()
        await pilot.press("down", "enter")
        app._on_model_picked(MODEL_RNNOISE)
        await pilot.pause()
    run(make_app(), steps)
    saved = TuiSettings()
    assert saved.aad_threshold_db == -50.0
    assert saved.atten_lim_db == -45.0
    assert saved.output_device == "alsa_output.usb-headset"
    assert saved.model == MODEL_RNNOISE


def test_refresh_keeps_the_picked_device(make_app):
    async def steps(app, pilot):
        devices, _ = panels(app)
        devices.query_one("#device-list").focus()
        await pilot.press("down", "enter", "r")
        await pilot.pause()
        assert devices.selected_device == "alsa_output.usb-headset"
    run(make_app(), steps)


def test_model_that_fails_to_load_is_not_saved(make_app, monkeypatch):
    from stream_denoiser.tui import app as app_mod
    monkeypatch.setattr(app_mod.PoiseApp, "_load_model",
                        lambda self: setattr(
                            self, "engine",
                            None if self.model == MODEL_RNNOISE else True))

    async def steps(app, pilot):
        app._on_model_picked(MODEL_RNNOISE)
    run(make_app(), steps)
    assert TuiSettings().model is None


def test_isolation_keys_reach_a_running_session(make_app):
    sent = []

    async def steps(app, pilot):
        app.audio.set = lambda **kw: sent.append(kw)
        # Strength starts at the strongest: right changes nothing.
        await pilot.press("2", "right", "down", "right")
    run(make_app(), steps)
    assert sent == [{"aad_threshold_db": -35.0}]


def test_strength_and_threshold_go_to_the_session(make_app):
    configs = []

    async def steps(app, pilot):
        app.audio.start = configs.append
        app.audio.stop = lambda: {}
        sent = []
        app.audio.set = lambda **kw: sent.append(kw)
        await pilot.press("2", "left", "left")
        assert sent == [{"atten_lim_db": -45.0}, {"atten_lim_db": -40.0}]
        await pilot.press("space")
        await pilot.pause()
        assert app.is_processing
        devices, isolation = panels(app)
        assert devices.query_one("#device-list").disabled
        await pilot.press("space")
        await pilot.pause()
        assert not devices.query_one("#device-list").disabled
    run(make_app(), steps)
    assert configs[0]["atten_lim_db"] == -40.0
    assert configs[0]["aad_threshold_db"] == -40.0


def test_a_burst_of_presses_is_one_event(make_app):
    async def steps(app, pilot):
        from stream_denoiser.tui.widgets import EventsPanel
        app.audio.set = lambda **kw: None
        await pilot.press("2", "left", "left", "left")
        events = app.query_one(EventsPanel)
        assert events.latest.message == "strength -50 → -35 dB"
        assert sum(e.key == "strength" for e in events.events) == 1
    run(make_app(), steps)


def test_the_selected_row_shows_only_while_box_2_has_focus(make_app):
    async def steps(app, pilot):
        _, isolation = panels(app)
        body = isolation.query_one("#isolation-body")
        await pilot.press("3")
        await pilot.pause()
        assert "‹" not in str(body.render())
        await pilot.press("2")
        await pilot.pause()
        assert "‹" in str(body.render())
    run(make_app(), steps)


def test_the_scope_stands_still_out_of_focus(make_app):
    async def steps(app, pilot):
        from stream_denoiser.tui.widgets import LevelScope
        scope = app.query_one(LevelScope)
        scope.push([(-20.0, -30.0)])
        scope._tick()
        assert len(scope._columns) == 1
        scope.push([(-21.0, -31.0)])
        app.app_focus = False
        await pilot.pause()
        scope.push([(-22.0, -32.0)])
        scope._tick()
        assert len(scope._columns) == 1  # nothing drawn, nothing queued
        app.app_focus = True
        await pilot.pause()
        scope.push([(-23.0, -33.0)])
        scope._tick()
        assert list(scope._columns)[-1] == (-23.0, -33.0)
        assert len(scope._columns) == 2
    run(make_app(), steps)


def test_box_numbers_are_full_size(make_app):
    async def steps(app, pilot):
        from stream_denoiser.tui.widgets import Box
        from textual.content import Content
        titles = {box.number: Content.from_markup(box.border_title).plain
                  for box in app.query(Box)}
        assert titles[2].startswith("2 isolation")
        assert titles[1].startswith("∿ poise  1 signal")
    run(make_app(), steps)


# --- colors -------------------------------------------------------------

def test_palette_themes_and_overrides():
    from stream_denoiser.tui import palette as P
    try:
        assert P.apply() == [] and P.ACCENT == "#5FD5EB"
        assert P.apply("verdant") == [] and P.ACCENT == "#35E0A8"
        problems = P.apply("neon", {"accent": "orange", "acent": "#fff",
                                    "error": "not-a-color"})
        assert problems == [
            "theme 'neon' unknown; one of abyss, verdant, mono, "
            "ultraviolet, ember, orchid",
            "colors: 'acent' is not a color role",
            "colors.error: 'not-a-color' is not a color"]
        assert P.theme == "abyss" and P.ACCENT == "#FFA500"
        assert P.RED == "#F87171"  # the bad value left the default
        # A new accent alone brings its own shades.
        assert P.ACCENT_DIM not in ("#4A9FB3", "#4a9fb3")
        assert P.css_variables()["poise-accent"] == "#FFA500"
        assert P.css_variables()["poise-accent-dim"] == P.ACCENT_DIM
    finally:
        P.apply()


def test_colors_come_from_tui_json(make_app):
    write(settings_path(), {"theme": "ember",
                            "colors": {"border": "#123456", "oops": 1}})

    async def steps(app, pilot):
        from stream_denoiser.tui.widgets import Box, EventsPanel
        box = app.query_one("#events-panel", Box)
        assert box.styles.border_top[1].hex6 == "#123456"
        app.query_one("#isolation-panel").focus()
        await pilot.pause()
        accent = app.query_one("#isolation-panel").styles.border_top[1]
        assert accent.hex6 == "#F5A524"
        messages = [e.message for e in app.query_one(EventsPanel).events]
        assert "tui.json: colors: 'oops' is not a color role" in messages
    run(make_app(), steps)


def test_t_cycles_the_theme_and_keeps_own_colors(make_app):
    write(settings_path(), {"colors": {"highlight": "#ff0000"}})

    async def steps(app, pilot):
        from stream_denoiser.tui import palette as P
        await pilot.press("t")
        await pilot.pause()
        assert P.theme == "verdant" and P.GOLD == "#FF0000"
        panel = app.query_one("#isolation-panel")
        assert panel.styles.border_top[1].hex6 == "#35E0A8"
    run(make_app(), steps)
    assert TuiSettings().theme == "verdant"
    assert TuiSettings().colors == {"highlight": "#ff0000"}


def test_colors_follow_tui_json_while_running(make_app):
    write(settings_path(), {"model": MODEL_RNNOISE,
                            "colors": {"border": "#123456"}})

    async def steps(app, pilot):
        from stream_denoiser.tui import palette as P
        from stream_denoiser.tui.widgets import Box
        # Rewritten from outside, as a wallpaper palette hook would.
        write(settings_path(), {"model": MODEL_RNNOISE,
                                "colors": {"border": "#abcdef"}})
        app._follow_settings_file()
        await pilot.pause()
        assert P.EDGE == "#ABCDEF"
        box = app.query_one("#events-panel", Box)
        assert box.styles.border_top[1].hex6 == "#ABCDEF"
        # A later save keeps the new colors rather than the stale ones.
        await pilot.press("minus")
        await pilot.pause()
    run(make_app(), steps)
    assert TuiSettings().colors == {"border": "#abcdef"}


_TUI_RUN = """
import asyncio, os, sys, tempfile
sys.path.insert(0, {root!r})
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="poise-test-config-")
from stream_denoiser.backends.platform import linux
from stream_denoiser.tui import app as app_mod
linux.list_pulseaudio_sinks = lambda: []
linux.get_default_sink_name = lambda: None
app_mod.AudioHost.launch = lambda self: None
app_mod.PoiseApp._setup_logging = lambda self: None
app_mod.PoiseApp._setup_cleanup_handlers = lambda self: None
async def main():
    async with app_mod.PoiseApp().run_test(size=(120, 36)) as pilot:
        await pilot.pause()
asyncio.run(main())
print("heavy:", ",".join(m for m in ("numpy", "onnxruntime")
                         if m in sys.modules))
"""


def test_the_tui_process_loads_no_numpy():
    """The engine loads in the audio process only (as the GUI's does,
    test_gui_no_numpy): checking the model here would otherwise keep
    numpy and ONNX Runtime in the UI too. A fresh interpreter, as this
    one has numpy loaded."""
    root = str(Path(__file__).resolve().parent.parent)
    run = subprocess.run([sys.executable, "-c", _TUI_RUN.format(root=root)],
                         capture_output=True, text=True, timeout=120)
    lines = [l for l in run.stdout.splitlines() if l.startswith("heavy:")]
    assert run.returncode == 0 and lines, run.stderr[-2000:]
    assert lines[-1] == "heavy: ", lines[-1]
