"""PipeWire node backend: selection, routing and the worker loop (fakes;
no audio server needed)."""
import sys
import time
import types

import numpy as np
import pytest

from stream_denoiser.backends import node_loop
from stream_denoiser.backends import pipewire_backend as pwb
from stream_denoiser.backends._loop_util import margin_samples
from stream_denoiser.backends.delay_core import WAIT_STOPPED, WAIT_TIMEOUT
from stream_denoiser.backends.pipewire_node import PipeWireNodeError
from stream_denoiser.constants import PW_NODE_NAME


# --- backend selection -----------------------------------------------------

def test_preference_reads_argument_then_env(monkeypatch):
    monkeypatch.delenv(pwb.BACKEND_ENV, raising=False)
    assert pwb.linux_backend_preference() == "auto"
    monkeypatch.setenv(pwb.BACKEND_ENV, "Pulse")
    assert pwb.linux_backend_preference() == "pulse"
    assert pwb.linux_backend_preference("pipewire") == "pipewire"
    with pytest.raises(ValueError, match="jack"):
        pwb.linux_backend_preference("jack")


def test_select_prefers_pipewire_when_available(monkeypatch):
    monkeypatch.setattr(pwb, "pipewire_node_status",
                        lambda: (True, "PipeWire 1.6"))
    assert pwb.select_linux_backend("auto") == ("pipewire", "PipeWire 1.6")
    assert pwb.select_linux_backend("pipewire")[0] == "pipewire"
    assert pwb.select_linux_backend("pulse") == ("pulse", "requested")
    # An explicit capture source only exists on the pulse-simple path.
    assert pwb.select_linux_backend("auto", source="x.monitor")[0] == "pulse"


def test_select_falls_back_or_fails_when_unavailable(monkeypatch):
    monkeypatch.setattr(pwb, "pipewire_node_status",
                        lambda: (False, "not built"))
    assert pwb.select_linux_backend("auto") == ("pulse", "not built")
    with pytest.raises(RuntimeError, match="not built"):
        pwb.select_linux_backend("pipewire")


def test_margin_env_override(monkeypatch):
    def margin():
        return margin_samples(pwb.MARGIN_ENV, pwb.PW_MARGIN_SAMPLES)

    monkeypatch.delenv(pwb.MARGIN_ENV, raising=False)
    assert margin() == pwb.PW_MARGIN_SAMPLES
    monkeypatch.setenv(pwb.MARGIN_ENV, "10")
    assert margin() == 480
    monkeypatch.setenv(pwb.MARGIN_ENV, "lots")
    assert margin() == pwb.PW_MARGIN_SAMPLES


# --- routing ---------------------------------------------------------------

class _FakePulse:
    def __init__(self, default, sinks):
        self.default = default
        self.sinks = [types.SimpleNamespace(name=n) for n in sinks]

    def module(self):
        pulse = self

        class _Ctx:
            def __init__(self, *_a, **_k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def server_info(self):
                return types.SimpleNamespace(default_sink_name=pulse.default)

            def sink_list(self):
                return list(pulse.sinks)

            def sink_default_set(self, sink):
                pulse.default = sink.name

        return types.SimpleNamespace(Pulse=_Ctx, PulseError=Exception)


@pytest.fixture
def fake_pulse(monkeypatch):
    def install(default, sinks):
        fake = _FakePulse(default, sinks)
        monkeypatch.setitem(sys.modules, "pulsectl", fake.module())
        return fake
    return install


def test_output_sink_is_the_real_default(fake_pulse):
    fake_pulse("alsa_out", ["alsa_out", "hdmi_out"])
    assert pwb.pick_output_sink() == "alsa_out"
    assert pwb.pick_output_sink("hdmi_out") == "hdmi_out"


def test_output_sink_skips_our_own_and_null_sinks(fake_pulse):
    fake_pulse(PW_NODE_NAME,
               [PW_NODE_NAME, "Poise_Capture", "some_null_sink", "alsa_out"])
    assert pwb.pick_output_sink() == "alsa_out"
    fake_pulse("Poise_Capture", ["Poise_Capture", "hdmi_out"])
    assert pwb.pick_output_sink() == "hdmi_out"


def test_router_switches_and_restores_default(fake_pulse):
    fake = fake_pulse("alsa_out", ["alsa_out", PW_NODE_NAME])
    router = pwb.DefaultSinkRouter(PW_NODE_NAME)
    assert router.wait_for_sink(0.1)
    router.switch()
    assert fake.default == PW_NODE_NAME and router.original == "alsa_out"
    router.restore()
    assert fake.default == "alsa_out"
    router.restore()  # idempotent
    assert fake.default == "alsa_out"


def test_router_restores_a_real_sink_when_ours_was_default(fake_pulse):
    """Poise already default at start (e.g. WirePlumber remembered it from
    a crashed run): restore still lands on real hardware."""
    fake = fake_pulse(PW_NODE_NAME, [PW_NODE_NAME, "alsa_out"])
    router = pwb.DefaultSinkRouter(PW_NODE_NAME)
    router.switch()
    assert router.original is None
    router.restore()
    assert fake.default == "alsa_out"


def test_router_prefers_the_output_sink_over_list_order(fake_pulse):
    fake = fake_pulse(PW_NODE_NAME, [PW_NODE_NAME, "alsa_out", "hdmi_out"])
    router = pwb.DefaultSinkRouter(PW_NODE_NAME, fallback="hdmi_out")
    router.switch()
    router.restore()
    assert fake.default == "hdmi_out"


def test_router_wait_gives_up(fake_pulse):
    fake_pulse("alsa_out", ["alsa_out"])
    assert not pwb.DefaultSinkRouter(PW_NODE_NAME).wait_for_sink(0.1)


# --- worker loop -----------------------------------------------------------

class _FakeNode:
    frame = 4
    delay_samples = 2112
    latency_samples = 3648

    def __init__(self, script, error=None, stats=None):
        self.script = list(script)
        self.put = {}
        self._error = error
        self._stats = list(stats or [])
        self._last = dict.fromkeys(
            ("frames_dry", "delay_changes", "resyncs", "input_gaps",
             "quantum_max"), 0)

    def stats(self):
        if self._stats:
            self._last = dict(self._last, **self._stats.pop(0))
        return self._last

    def wait_frame(self, buf, timeout_ms):
        if not self.script:
            return WAIT_STOPPED
        k = self.script.pop(0)
        if k >= 0:
            buf[:] = k
        return k

    def put_frame(self, k, out):
        self.put[k] = np.array(out)

    def error(self):
        return self._error


def _worker_loop(node, should_stop=None):
    """The PipeWire node's worker loop, as run_pipewire_loop runs it."""
    node_loop.worker_loop(node, _Doubler(), should_stop, None, 1.0,
                          time.time(), log_sync=pwb._log_sync,
                          error=PipeWireNodeError)


class _Doubler:
    def process_chunk(self, x):
        assert x.dtype == np.float32 and x.shape == (4,)
        return x * 2

    def get_stats(self):
        return {}


def test_worker_processes_each_frame_and_returns_it():
    node = _FakeNode([0, 1, WAIT_TIMEOUT, 2])
    _worker_loop(node)
    assert sorted(node.put) == [0, 1, 2]
    np.testing.assert_allclose(node.put[2], 4.0)


def test_worker_stops_on_request():
    node = _FakeNode([0, 1, 2])
    _worker_loop(node, lambda: True)
    assert node.put == {}


def test_worker_raises_node_errors():
    node = _FakeNode([WAIT_TIMEOUT], error="Poise output: target gone")
    with pytest.raises(PipeWireNodeError, match="target gone"):
        _worker_loop(node)


def test_worker_logs_each_event(monkeypatch):
    import logging
    monkeypatch.setattr(node_loop, "EVENT_CHECK_SEC", 0.0)
    node = _FakeNode([0, 1, 2],
                     stats=[{}, {"frames_dry": 3},
                            {"frames_dry": 3, "delay_changes": 1,
                             "quantum_max": 1024}])
    lines = []
    handler = logging.Handler(logging.INFO)
    handler.emit = lambda record: lines.append(record.getMessage())
    node_loop._logger.addHandler(handler)
    try:
        _worker_loop(node)
    finally:
        node_loop._logger.removeHandler(handler)
    text = "\n".join(lines)
    assert "3 frames (0 ms) played unprocessed" in text
    assert "delay raised to 2112 samples" in text and "1024-sample" in text
    assert text.count("played unprocessed") == 1


def test_worker_restores_gil_switch_interval():
    before = sys.getswitchinterval()
    _worker_loop(_FakeNode([0]))
    assert sys.getswitchinterval() == before


# --- CLI -------------------------------------------------------------------

def _engine():
    from stream_denoiser.engines.base import DenoiseEngine

    class _E(DenoiseEngine):
        name = "fake"
        required_frame_size = 480

        def process_frame(self, frame):
            return frame

        def reset(self):
            pass

    return _E()


def test_cli_runs_the_pipewire_node_when_selected(monkeypatch):
    from stream_denoiser import cli as cli_mod
    monkeypatch.setattr(cli_mod, "is_linux", lambda: True)
    monkeypatch.setattr(pwb, "pipewire_node_status", lambda: (True, "ok"))
    seen = {}

    def fake_run(processor, sink=None, route_default=True):
        seen.update(frame=processor.frame_size, sink=sink,
                    route=route_default)

    monkeypatch.setattr(pwb, "process_with_pipewire", fake_run)
    cli_mod.process_system_audio_realtime(_engine(), sink="alsa_out",
                                          use_vb_cable=False)
    assert seen == {"frame": 480, "sink": "alsa_out", "route": False}


def test_cli_keeps_pulse_path_when_forced(monkeypatch):
    from stream_denoiser import cli as cli_mod
    monkeypatch.setattr(cli_mod, "is_linux", lambda: True)
    monkeypatch.setattr(pwb, "pipewire_node_status", lambda: (True, "ok"))
    monkeypatch.setattr(pwb, "process_with_pipewire",
                        lambda *a, **k: pytest.fail("PipeWire path taken"))
    seen = {}
    import stream_denoiser.backends.pulse_backend as pulse_backend
    monkeypatch.setattr(pulse_backend, "process_with_pulse",
                        lambda processor, source, sink: seen.update(
                            source=source, sink=sink))
    cli_mod.process_system_audio_realtime(
        _engine(), source="x.monitor", sink="alsa_out", use_vb_cable=False,
        backend="pulse")
    assert seen == {"source": "x.monitor", "sink": "alsa_out"}
