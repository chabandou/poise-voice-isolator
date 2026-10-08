"""Tests for Pulse-level monitor discovery (no system changes)."""
import sys
import types

import pytest


def _load_linux_module():
    """Import the Linux router module without PulseAudio side effects."""
    if "pulsectl" not in sys.modules:
        try:
            import pulsectl  # noqa: F401
        except ImportError:
            stub = types.ModuleType("pulsectl")
            stub._is_stub = True

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


def _router():
    mod = _load_linux_module()
    r = mod.LinuxAudioRouter(auto_switch=False)
    r._sink_name = mod.LinuxAudioRouter.SINK_NAME
    r._monitor_source = f"{mod.LinuxAudioRouter.SINK_NAME}.monitor"
    r._original_default_sink = "alsa_output.pci-0000_00_1f.3.analog-stereo"
    return mod, r


def _source(name):
    return types.SimpleNamespace(name=name)


def test_portaudio_helpers_removed():
    mod = _load_linux_module()
    for gone in ("map_pulse_to_portaudio", "find_loopback_hybrid",
                 "find_monitor_sources", "find_loopback_device_linux",
                 "get_linux_output_devices", "get_monitor_device_id"):
        assert not hasattr(mod, gone), gone
    assert not hasattr(mod.LinuxAudioRouter, "_score_monitor_device")
    assert not hasattr(mod.LinuxAudioRouter, "get_monitor_device_id")


def test_original_sink_name_property():
    mod, r = _router()
    assert r.original_sink_name == "alsa_output.pci-0000_00_1f.3.analog-stereo"


def test_wait_for_monitor_source_found(monkeypatch):
    mod, r = _router()
    calls = {"n": 0}

    class FakePulse:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def source_list(self):
            calls["n"] += 1
            if calls["n"] < 3:
                return [_source("alsa_output.pci.monitor")]
            return [_source("Poise_Capture.monitor")]

    fake_pulsectl = types.SimpleNamespace(Pulse=FakePulse)
    monkeypatch.setitem(sys.modules, "pulsectl", fake_pulsectl)
    monkeypatch.setattr(mod, "USE_PULSECTL", True)
    monkeypatch.setattr("time.sleep", lambda s: None)
    assert r.wait_for_monitor_source(timeout_sec=3.0, poll_interval_sec=0.05) == \
        "Poise_Capture.monitor"
    assert calls["n"] >= 3


def test_wait_for_monitor_source_timeout(monkeypatch):
    # NOTE: asserted via mock, not caplog: our loggers use propagate=False,
    # and pytest only attaches its capture handler to non-propagating
    # loggers that already exist at test-setup time — but the module under
    # test is imported lazily inside the test itself, so caplog would
    # flakily miss the record depending on test order.
    mod, r = _router()

    class FakePulse:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def source_list(self):
            return [_source("alsa_output.pci.monitor")]

    fake_pulsectl = types.SimpleNamespace(Pulse=FakePulse)
    monkeypatch.setitem(sys.modules, "pulsectl", fake_pulsectl)
    monkeypatch.setattr(mod, "USE_PULSECTL", True)
    warnings = []
    monkeypatch.setattr(
        mod._logger, "warning",
        lambda msg, *args, **kwargs: warnings.append(msg % args if args else msg),
    )
    assert r.wait_for_monitor_source(timeout_sec=0, poll_interval_sec=0.05) is None
    text = "\n".join(warnings)
    assert "did not appear at the PulseAudio" in text


def test_wait_for_monitor_source_no_name():
    mod, r = _router()
    r._monitor_source = None
    assert r.wait_for_monitor_source(timeout_sec=0) is None


def test_cli_fails_fast_when_monitor_missing(monkeypatch):
    """CLI must not silently capture the default input instead."""
    from stream_denoiser import cli as cli_mod

    made = {}

    class _FakeRouter:
        def __init__(self, auto_switch=True):
            made["created"] = True

        def get_monitor_source_name(self):
            return "Poise_Capture.monitor"

        def wait_for_monitor_source(self, timeout_sec=3.0, poll_interval_sec=0.05):
            return None

        @property
        def original_sink_name(self):
            return "alsa_output.pci.hw"

        def restore_original_sink(self):
            made["restored"] = True
            return True

    monkeypatch.setattr(cli_mod, "is_linux", lambda: True)
    monkeypatch.setattr(cli_mod, "is_windows", lambda: False)
    real_router_mod = _load_linux_module()
    monkeypatch.setattr(real_router_mod, "LinuxAudioRouter", _FakeRouter)

    class _Engine:
        required_frame_size = 480

    with pytest.raises(RuntimeError, match="not visible at the"):
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


def test_cli_uses_source_and_sink_names(monkeypatch):
    from stream_denoiser import cli as cli_mod

    class _FakeRouter:
        def __init__(self, auto_switch=True):
            pass

        def get_monitor_source_name(self):
            return "Poise_Capture.monitor"

        def wait_for_monitor_source(self, timeout_sec=3.0, poll_interval_sec=0.05):
            return "Poise_Capture.monitor"

        @property
        def original_sink_name(self):
            return "alsa_output.pci.hw"

        def restore_original_sink(self):
            return True

    monkeypatch.setattr(cli_mod, "is_linux", lambda: True)
    monkeypatch.setattr(cli_mod, "is_windows", lambda: False)
    real_router_mod = _load_linux_module()
    monkeypatch.setattr(real_router_mod, "LinuxAudioRouter", lambda auto_switch=True: _FakeRouter())

    seen = {}

    def _fake_backend(processor, source, sink):
        seen["source"] = source
        seen["sink"] = sink

    import stream_denoiser.backends.pulse_backend as pulse_backend
    monkeypatch.setattr(pulse_backend, "process_with_pulse", _fake_backend)

    cli_mod.process_system_audio_realtime(_fake_rnnoise_engine())
    assert seen["source"] == "Poise_Capture.monitor"
    assert seen["sink"] == "alsa_output.pci.hw"


def test_cli_rejects_numeric_devices_on_linux(monkeypatch):
    from stream_denoiser import cli as cli_mod
    monkeypatch.setattr(cli_mod, "is_linux", lambda: True)
    monkeypatch.setattr(cli_mod, "is_windows", lambda: False)
    with pytest.raises(ValueError, match="--source"):
        cli_mod.process_system_audio_realtime(_fake_rnnoise_engine(), input_device=2)
    with pytest.raises(ValueError, match="--sink"):
        cli_mod.process_system_audio_realtime(_fake_rnnoise_engine(), output_device=1)
