"""session: which loop runs, and with what, for the CLI and the audio
process (fakes; no audio devices needed)."""
import types

import pytest

from stream_denoiser import cli as cli_mod
from stream_denoiser import session
from stream_denoiser.backends import sounddevice_backend, wasapi_backend
from stream_denoiser.engines.base import DenoiseEngine


class _Engine(DenoiseEngine):
    name = "fake"
    required_frame_size = 480

    def process_frame(self, frame):
        return frame

    def reset(self):
        pass


@pytest.fixture
def windows(monkeypatch):
    """Windows dispatch with fake loops; returns what each loop got."""
    monkeypatch.setattr(session, "sys", types.SimpleNamespace(platform="win32"))
    calls = {}
    chosen = {"backend": "wasapi"}

    def select(preference):
        if preference == "portaudio":
            return "portaudio", "requested"
        return chosen["backend"], "test"

    def wasapi(processor, capture, render, on_started=None, **kwargs):
        calls["wasapi"] = dict(capture=capture, render=render, **kwargs)
        if chosen.get("fail"):
            raise wasapi_backend.WasapiStartError("no device")
        on_started()
        return {}

    def portaudio(processor, input_device, output_device, on_started=None,
                  **kwargs):
        calls["portaudio"] = dict(input=input_device, output=output_device,
                                  **kwargs)
        on_started(input_device, output_device)
        return {}

    monkeypatch.setattr(wasapi_backend, "select_windows_backend", select)
    monkeypatch.setattr(wasapi_backend, "run_wasapi_loop", wasapi)
    monkeypatch.setattr(sounddevice_backend, "run_portaudio_loop", portaudio)
    monkeypatch.setattr(session, "_device_name",
                        lambda device, kind: f"{kind}-{device}")
    calls["chosen"] = chosen
    return calls


def _run(config, **kwargs):
    started = []
    processor = session.build_processor(config, _Engine())
    extra = session.run_session(
        processor, config, on_started=lambda *a: started.append(a), **kwargs)
    return started, extra


def test_native_path_runs_with_the_callers_margin_and_collector(windows):
    started, extra = _run({"backend": "auto", "input_device": 3,
                           "output_device": 5})
    assert started == [("wasapi", "input-3", "output-5")] and extra == {}
    got = windows["wasapi"]
    assert (got["capture"], got["render"]) == ("input-3", "output-5")
    # The CLI's defaults: the UI-process margin, the collector on.
    assert got["margin"] is None and got["pause_gc"] is False

    _run({"backend": "auto"}, wasapi_margin=256, wasapi_pause_gc=True)
    assert windows["wasapi"]["margin"] == 256
    assert windows["wasapi"]["pause_gc"] is True
    assert "portaudio" not in windows


def test_auto_falls_back_to_portaudio_when_the_native_path_fails(windows):
    windows["chosen"]["fail"] = True
    started, _ = _run({"backend": "auto", "input_device": 3,
                       "output_device": 5, "realtime": False})
    assert started == [("portaudio", 3, 5)]
    got = windows["portaudio"]
    assert got["pause_gc"] is True and got["realtime"] is False


def test_wasapi_requested_does_not_fall_back(windows):
    windows["chosen"]["fail"] = True
    with pytest.raises(wasapi_backend.WasapiStartError):
        _run({"backend": "wasapi"})
    assert "portaudio" not in windows


def test_portaudio_requested_skips_the_native_path(windows):
    started, _ = _run({"backend": "portaudio"})
    assert started == [("portaudio", None, None)]
    assert "wasapi" not in windows
    assert windows["portaudio"]["realtime"] is True


def test_build_processor_closes_an_engine_it_created(monkeypatch):
    closed = []

    class Engine(_Engine):
        required_frame_size = 512

        def close(self):
            closed.append(True)

    import stream_denoiser.engines as engines
    monkeypatch.setattr(engines, "create_engine", lambda *a, **k: Engine())
    import stream_denoiser.processor as processor_mod

    def fail(*a, **k):
        raise ValueError("bad frame")

    monkeypatch.setattr(processor_mod, "DenoiserAudioProcessor", fail)
    with pytest.raises(ValueError):
        session.build_processor({})
    assert closed == [True]
    # A caller's engine stays the caller's.
    with pytest.raises(ValueError):
        session.build_processor({}, Engine())
    assert closed == [True]


def test_cli_resolves_portaudio_devices_and_keeps_its_native_settings(
        windows, monkeypatch, capsys):
    """The CLI picks devices as the PortAudio loop would (CABLE Output and
    an output on its host API) and runs the native path with them."""
    monkeypatch.setattr(cli_mod, "is_linux", lambda: False)
    monkeypatch.setattr(cli_mod, "is_windows", lambda: False)
    monkeypatch.setattr(cli_mod, "USE_SOUNDDEVICE", True)
    asked = []

    def select_devices(processor, input_device, output_device):
        asked.append((input_device, output_device))
        return 3, 5

    monkeypatch.setattr(sounddevice_backend, "select_devices", select_devices)
    cli_mod.process_system_audio_realtime(_Engine(), output_device=7,
                                          backend="auto")
    assert asked == [(None, 7)]
    got = windows["wasapi"]
    assert (got["capture"], got["render"]) == ("input-3", "output-5")
    assert got["margin"] is None and got["pause_gc"] is False
    out = capsys.readouterr().out
    assert "native WASAPI" in out and "Output device: output-5" in out
