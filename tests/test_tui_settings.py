"""TUI settings kept across sessions: model, output device, AAD threshold.

The file tests need nothing; the app tests run the TUI headless with the
audio process, engine loading and Pulse replaced by stand-ins.
"""
import asyncio
import json

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
    return app_mod.PoiseApp


def run(app, steps):
    async def main():
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            await steps(app, pilot)
    asyncio.run(main())


def panels(app):
    from stream_denoiser.tui.widgets import AADPanel, DeviceList
    return (app.query_one("#device-panel", DeviceList),
            app.query_one("#aad-panel", AADPanel))


def test_first_start_uses_defaults(make_app):
    async def steps(app, pilot):
        devices, aad = panels(app)
        assert app.model == DEFAULT_MODEL
        assert devices.selected_device == DEFAULT_SINK
        assert aad.threshold_db == -40.0
    run(make_app(), steps)
    assert not settings_path().exists()  # nothing chosen, nothing written


def test_saved_choices_are_restored(make_app):
    write(settings_path(), {"model": MODEL_RNNOISE,
                            "output_device": "alsa_output.usb-headset",
                            "aad_threshold_db": -60.0})

    async def steps(app, pilot):
        devices, aad = panels(app)
        assert app.model == MODEL_RNNOISE
        assert devices.selected_device == "alsa_output.usb-headset"
        assert aad.threshold_db == -60.0
        assert "-60.0 dB" in str(aad.query_one("#aad-threshold-value").render())
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
        devices, _ = panels(app)
        devices.query_one("#device-list").focus()
        await pilot.press("down", "enter")
        app._on_model_picked(MODEL_RNNOISE)
        await pilot.pause()
    run(make_app(), steps)
    saved = TuiSettings()
    assert saved.aad_threshold_db == -50.0
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
