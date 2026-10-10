"""Tests for null-sink monitor discovery (no system changes)."""
import sys
import types

import pytest


def _load_linux_module():
    """Import the Linux router module without PulseAudio side effects."""
    # Stub pulsectl so import works on boxes without PulseAudio libs.
    if "pulsectl" not in sys.modules:
        try:
            import pulsectl  # noqa: F401
        except ImportError:
            stub = types.ModuleType("pulsectl")

            class PulseError(Exception):
                pass

            class Pulse:
                def __init__(self, *a, **k):
                    raise PulseError("stub")

            stub.Pulse = Pulse
            stub.PulseError = PulseError
            sys.modules["pulsectl"] = stub
    from stream_denoiser.backends.platform import linux as linux_mod
    return linux_mod


def _router(monkey_module=None):
    mod = _load_linux_module()
    r = mod.LinuxAudioRouter(auto_switch=False)
    r._sink_name = mod.LinuxAudioRouter.SINK_NAME
    r._monitor_source = f"{mod.LinuxAudioRouter.SINK_NAME}.monitor"
    return mod, r


def _dev(name, inputs=1, outputs=0, sr=48000, api=0):
    return {
        "name": name,
        "max_input_channels": inputs,
        "max_output_channels": outputs,
        "default_samplerate": sr,
        "hostapi": api,
    }


def test_score_matches_sink_name_and_description():
    mod, r = _router()
    assert r._score_monitor_device(_dev("Poise_Capture")) > 0
    # PipeWire/Pulse often publishes the description instead of the slug.
    assert r._score_monitor_device(_dev("Monitor of Poise Audio Capture")) > 0
    assert r._score_monitor_device(_dev("Poise_Capture.monitor")) > 0


def test_score_rejects_output_only_and_unrelated():
    mod, r = _router()
    assert r._score_monitor_device(_dev("Poise_Capture", inputs=0)) == 0
    assert r._score_monitor_device(_dev("Built-in Microphone")) == 0
    assert r._score_monitor_device(_dev("")) == 0


def test_get_monitor_finds_description_named_device(monkeypatch):
    mod, r = _router()
    fake_sd = types.SimpleNamespace()
    fake_sd._terminate = lambda: None
    fake_sd._initialize = lambda: None
    fake_sd.query_devices = lambda: [
        _dev("Built-in Microphone"),
        _dev("Monitor of Poise Audio Capture"),
    ]
    fake_sd.query_hostapis = lambda i: {"name": "PulseAudio"}
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
    monkeypatch.setattr(r, "_pulse_monitor_exists", lambda: True)
    assert r.get_monitor_device_id(timeout_sec=0, retry_interval_sec=0.05) == 1


def test_get_monitor_retries_until_device_appears(monkeypatch):
    mod, r = _router()
    calls = {"n": 0}

    def _query():
        calls["n"] += 1
        if calls["n"] < 3:
            return [_dev("Built-in Microphone")]
        return [_dev("Poise_Capture")]

    fake_sd = types.SimpleNamespace()
    fake_sd._terminate = lambda: None
    fake_sd._initialize = lambda: None
    fake_sd.query_devices = _query
    fake_sd.query_hostapis = lambda i: {"name": "PulseAudio"}
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(r, "_pulse_monitor_exists", lambda: True)
    assert r.get_monitor_device_id(timeout_sec=60, retry_interval_sec=0.05) == 0
    assert calls["n"] >= 3


def test_get_monitor_logs_devices_on_failure(monkeypatch, caplog):
    mod, r = _router()
    fake_sd = types.SimpleNamespace()
    fake_sd._terminate = lambda: None
    fake_sd._initialize = lambda: None
    fake_sd.query_devices = lambda: [_dev("Built-in Microphone")]
    fake_sd.query_hostapis = lambda i: {"name": "PulseAudio"}
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
    monkeypatch.setattr(r, "_pulse_monitor_exists", lambda: True)
    with caplog.at_level("WARNING", logger="stream_denoiser"):
        assert r.get_monitor_device_id(timeout_sec=0, retry_interval_sec=0.05) is None
    text = "\n".join(rec.message for rec in caplog.records)
    assert "Could not find PortAudio device for monitor" in text
    assert "Built-in Microphone" in text  # device dump for remote diagnosis
    assert "PulseAudio HAS" in text


def test_cli_fails_fast_when_monitor_missing(monkeypatch):
    """CLI must not silently capture the default input instead."""
    from stream_denoiser import cli as cli_mod

    made = {}

    class _FakeRouter:
        def __init__(self, auto_switch=True):
            made["created"] = True

        def get_monitor_source_name(self):
            return "Poise_Capture.monitor"

        def get_monitor_device_id(self):
            return None

        def restore_original_sink(self):
            made["restored"] = True
            return True

    monkeypatch.setattr(cli_mod, "is_linux", lambda: True)
    monkeypatch.setattr(cli_mod, "is_windows", lambda: False)
    monkeypatch.setitem(
        sys.modules,
        "stream_denoiser.backends.platform.linux",
        types.SimpleNamespace(LinuxAudioRouter=_FakeRouter),
    )
    import importlib
    # Patch the already-imported reference used inside cli.process_system_audio_realtime
    # via sys.modules lookup fallback: force the local import to resolve.
    real_router_mod = _load_linux_module()
    monkeypatch.setattr(real_router_mod, "LinuxAudioRouter", _FakeRouter)

    class _Engine:
        required_frame_size = 480

    with pytest.raises(RuntimeError, match="not visible to PortAudio"):
        cli_mod.process_system_audio_realtime(_Engine(), input_device=None)
    assert made.get("restored") is True


def _fake_rnnoise_engine():
    from stream_denoiser.engines.base import DenoiseEngine

    class _FakeEngine(DenoiseEngine):
        name = "fake"
        required_frame_size = 480

        def __init__(self):
            self.speech_prob = None

        def process_frame(self, frame):
            return frame

        def reset(self):
            pass

        def close(self):
            pass

    return _FakeEngine()


def test_cli_keeps_explicit_input_when_monitor_missing(monkeypatch):
    from stream_denoiser import cli as cli_mod

    class _FakeRouter:
        def get_monitor_source_name(self):
            return "Poise_Capture.monitor"

        def get_monitor_device_id(self):
            return None

        def restore_original_sink(self):
            return True

    monkeypatch.setattr(cli_mod, "is_linux", lambda: True)
    monkeypatch.setattr(cli_mod, "is_windows", lambda: False)
    real_router_mod = _load_linux_module()
    monkeypatch.setattr(real_router_mod, "LinuxAudioRouter", lambda auto_switch=True: _FakeRouter())

    seen = {}

    def _fake_backend(processor, input_device, output_device):
        seen["input"] = input_device

    monkeypatch.setattr(cli_mod, "USE_SOUNDDEVICE", True)
    monkeypatch.setitem(
        sys.modules,
        "stream_denoiser.backends.sounddevice_backend",
        types.SimpleNamespace(process_with_sounddevice=_fake_backend),
    )
    # process_system_audio_realtime imports the backend inside the function,
    # so patch the real module attribute instead.
    import stream_denoiser.backends.sounddevice_backend as sd_backend
    monkeypatch.setattr(sd_backend, "process_with_sounddevice", _fake_backend)

    cli_mod.process_system_audio_realtime(_fake_rnnoise_engine(), input_device=2)
    assert seen["input"] == 2
