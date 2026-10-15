"""The audio loop's own process (audio_host): sessions, messages, crashes.

Most tests drive the session side in this process through a fake pipe;
a few spawn the real audio process (no audio server needed: their
sessions fail before opening any stream). Live PipeWire sessions are in
test_pipewire_integration.py.
"""
import json
import logging
import os
import signal
import sys
import time
import types

import numpy as np
import pytest

from stream_denoiser import audio_host as ah
from stream_denoiser import session
from stream_denoiser.engines.base import DenoiseEngine
from stream_denoiser.processor import DenoiserAudioProcessor


class FakeChannel:
    """The pipe, seen from one end: queued messages in, sent ones kept.
    Messages go through JSON like the real one."""

    def __init__(self, inbox=(), closed=False):
        self.inbox = list(inbox)
        self.closed = closed
        self.sent = []

    def send(self, msg):
        self.sent.append(json.loads(json.dumps(msg, default=ah._plain)))
        return True

    def poll(self):
        return bool(self.inbox) or self.closed

    def recv(self):
        if self.inbox:
            return self.inbox.pop(0)
        raise EOFError

    def events(self, kind=None):
        return [m for m in self.sent
                if kind is None or m.get("event") == kind]


class Passthrough(DenoiseEngine):
    name = "passthrough"
    required_frame_size = 480

    def __init__(self):
        self.atten = []

    def process_frame(self, frame):
        return frame

    def reset(self):
        pass

    def set_atten_lim_db(self, value):
        self.atten.append(value)


def _processor():
    return DenoiserAudioProcessor(Passthrough(), target_sr=48000,
                                  frame_size=480, enable_aad=True,
                                  aad_threshold_db=-40.0)


# --- session side ------------------------------------------------------------

def test_control_applies_settings_then_stops():
    channel = FakeChannel([{"cmd": "set", "aad_threshold_db": -55.0},
                           {"cmd": "set", "atten_lim_db": -12.0},
                           {"cmd": "stop"}])
    ctl = ah._Control(channel)
    ctl.processor = processor = _processor()
    assert ctl.should_stop() is True
    assert processor.aad.threshold_db == -55.0
    assert processor.engine.atten == [-12.0]
    assert not ctl.quit


def test_settings_wait_for_the_processor():
    ctl = ah._Control(FakeChannel([{"cmd": "set", "aad_threshold_db": -60}]))
    assert ctl.should_stop() is False
    ctl.processor = processor = _processor()
    ctl.apply_pending()
    assert processor.aad.threshold_db == -60.0


def test_control_ends_the_process_when_the_ui_is_gone():
    ctl = ah._Control(FakeChannel(closed=True))
    assert ctl.should_stop() is True
    assert ctl.quit


def _session(monkeypatch, channel, run_session):
    monkeypatch.setattr(session, "build_processor",
                        lambda config: _processor())
    monkeypatch.setattr(session, "run_session", run_session)
    return ah._run_session(channel, {"backend": "pipewire"})


def test_session_streams_stats_until_stopped(monkeypatch):
    channel = FakeChannel([{"cmd": "set", "aad_threshold_db": -50}])

    def run_backend(processor, config, should_stop, on_stats, on_started,
                    **_):
        on_started("pipewire", None, None)
        on_stats({}, 1.0)
        channel.inbox.append({"cmd": "stop"})
        while not should_stop():
            pass
        processor.process_chunk(np.full(480, 0.1, dtype=np.float32))
        on_stats({}, 2.0)
        return {"empty_reads": 3}

    assert _session(monkeypatch, channel, run_backend) is False
    assert channel.events("running") == [{"event": "running",
                                          "backend": "pipewire"}]
    stats = channel.events("stats")
    assert stats and stats[-1]["elapsed"] == 2.0
    assert stats[-1]["stats"]["aad_threshold_db"] == -50.0
    final = channel.events("stopped")
    assert len(final) == 1 and channel.sent[-1]["event"] == "stopped"
    assert final[0]["stats"]["empty_reads"] == 3
    assert final[0]["stats"]["aad_total"] == 1


def test_session_failure_sends_the_notice_then_stops(monkeypatch):
    channel = FakeChannel()

    def run_backend(processor, config, **_):
        raise session.SessionError("no monitor", session.CAPTURE_NOTICE)

    _session(monkeypatch, channel, run_backend)
    assert [m["event"] for m in channel.sent] == ["error", "stopped"]
    assert channel.sent[0]["notice"] == session.CAPTURE_NOTICE


def test_session_crash_in_the_loop_is_an_audio_error(monkeypatch):
    channel = FakeChannel()

    def run_backend(processor, config, **_):
        raise RuntimeError("Poise output: target gone")

    _session(monkeypatch, channel, run_backend)
    error = channel.events("error")[0]
    assert error["notice"] == ah.AUDIO_ERROR_NOTICE
    assert "target gone" in error["message"]
    assert channel.sent[-1]["event"] == "stopped"


def test_quit_ends_the_process(monkeypatch):
    channel = FakeChannel([{"cmd": "quit"}])

    def run_backend(processor, config, should_stop, **_):
        while not should_stop():
            pass
        return {}

    assert _session(monkeypatch, channel, run_backend) is True
    assert channel.sent[-1]["event"] == "stopped"


def test_stop_before_the_loop_skips_it(monkeypatch):
    channel = FakeChannel([{"cmd": "stop"}])
    _session(monkeypatch, channel,
             lambda *a, **k: pytest.fail("loop started after stop"))
    assert [m["event"] for m in channel.sent] == ["stopped"]


def test_unknown_backend_is_an_error():
    with pytest.raises(ValueError, match="unknown audio backend"):
        session.run_session(_processor(), {"backend": "alsa"})


# --- pulse-simple endpoints ------------------------------------------------------

@pytest.fixture
def linux(monkeypatch):
    if "pulsectl" not in sys.modules:
        try:
            import pulsectl  # noqa: F401
        except ImportError:
            stub = types.ModuleType("pulsectl")
            stub._is_stub = True
            stub.PulseError = type("PulseError", (Exception,), {})
            sys.modules["pulsectl"] = stub
    from stream_denoiser.backends.platform import linux as mod
    monkeypatch.setattr(mod, "wait_for_source", lambda name: name)
    monkeypatch.setattr(mod, "get_default_sink_name", lambda: "default_hw")
    monkeypatch.setattr(mod, "find_monitor_source_pulsectl",
                        lambda: types.SimpleNamespace(name="hw.monitor"))
    return mod


def test_pulse_endpoints_follow_the_router(linux):
    config = {"routed": True, "monitor_source": "Poise_Capture.monitor",
              "fallback_sink": "saved_hw"}
    assert session.pulse_endpoints(config) == ("Poise_Capture.monitor",
                                               "saved_hw")
    config["output_device"] = "chosen"
    assert session.pulse_endpoints(config)[1] == "chosen"
    assert session.pulse_endpoints({"routed": True, "monitor_source": "m"}) \
        == ("m", "default_hw")
    # An explicit capture source (the CLI's --source) wins.
    config["input_device"] = "x.monitor"
    assert session.pulse_endpoints(config) == ("x.monitor", "chosen")


def test_pulse_endpoints_without_router_capture_the_default_monitor(linux):
    assert session.pulse_endpoints({"routed": False}) == ("hw.monitor",
                                                         "default_hw")


@pytest.mark.parametrize("config, patch, notice", [
    ({"routed": True}, {}, session.CAPTURE_NOTICE),
    ({"routed": True, "monitor_source": "m"},
     {"wait_for_source": lambda name: None}, session.CAPTURE_NOTICE),
    ({"routed": False}, {"find_monitor_source_pulsectl": lambda: None},
     session.CAPTURE_NOTICE),
    ({"routed": False}, {"get_default_sink_name": lambda: None},
     session.PLAYBACK_NOTICE),
])
def test_pulse_endpoints_fail_fast(linux, monkeypatch, config, patch,
                                   notice):
    for name, fn in patch.items():
        monkeypatch.setattr(linux, name, fn)
    with pytest.raises(session.SessionError) as err:
        session.pulse_endpoints(config)
    assert err.value.notice == notice


# --- UI side ---------------------------------------------------------------------

def test_records_keep_their_logger_and_time():
    seen = []
    handler = logging.Handler(logging.DEBUG)
    handler.emit = seen.append
    from stream_denoiser.logging_config import get_logger
    logger = get_logger("stream_denoiser.test_audio_host_forward")
    logger.addHandler(handler)
    try:
        ah._emit_log({"event": "log", "name": logger.name,
                      "level": logging.WARNING, "msg": "sync: 3 frames",
                      "created": 1000.25})
    finally:
        logger.removeHandler(handler)
    (record,) = seen
    assert record.getMessage() == "sync: 3 frames"
    assert record.levelname == "WARNING" and record.created == 1000.25
    assert record.msecs == pytest.approx(250.0)


def test_numpy_values_cross_as_plain_json():
    msg = {"a": np.float32(0.5), "b": np.int64(3), "c": np.zeros(2)}
    assert json.loads(json.dumps(msg, default=ah._plain)) == \
        {"a": 0.5, "b": 3, "c": [0.0, 0.0]}


def test_a_crash_ends_the_session_for_the_ui():
    events = []
    host = ah.AudioHost(on_event=events.append)
    proc = types.SimpleNamespace(exitcode=-11, join=lambda timeout=None: None)
    host._proc = proc
    host._stopped.clear()
    host._read(proc, FakeChannel([{"event": "stats",
                                   "stats": {"frame_count": 7}}]))
    assert [e["event"] for e in events] == ["error", "stopped"]
    assert events[0]["notice"] == ah.CRASH_NOTICE
    assert "-11" in events[0]["message"]
    assert not host.running and host.final_stats == {"frame_count": 7}


def test_the_end_of_an_idle_process_is_quiet():
    events = []
    host = ah.AudioHost(on_event=events.append)
    proc = types.SimpleNamespace(exitcode=0, join=lambda timeout=None: None)
    host._proc = proc
    host._read(proc, FakeChannel())
    assert events == []


# --- the real process --------------------------------------------------------------

def _wait(cond, timeout=20.0):
    deadline = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


@pytest.fixture
def host():
    events = []
    host = ah.AudioHost(on_event=events.append)
    host.events = events
    yield host
    host.shutdown(timeout=5)


def test_audio_process_session_round_trip(host):
    seen = []
    handler = logging.Handler(logging.DEBUG)
    handler.emit = lambda record: seen.append(
        (record.name, record.getMessage()))
    ah._logger.addHandler(handler)
    try:
        host.launch()
        assert _wait(lambda: any(e["event"] == "ready"
                                 for e in host.events))
        child = host.pid
        assert child != os.getpid()
        # Fails while building the engine: no audio server involved.
        host.start({"model": "no-such-model", "backend": "pipewire"})
        assert _wait(lambda: not host.running)
    finally:
        ah._logger.removeHandler(handler)
    kinds = [e["event"] for e in host.events]
    assert kinds == ["ready", "error", "stopped"]
    assert host.events[1]["notice"] == ah.AUDIO_ERROR_NOTICE
    # The child's own log record, re-emitted here under its logger.
    assert any(name == "stream_denoiser.audio_host"
               and msg.startswith("Processing error:") for name, msg in seen)
    host.shutdown(timeout=5)
    assert not host.alive
    assert _wait(lambda: not os.path.exists(f"/proc/{child}"), 5) \
        or not sys.platform.startswith("linux")


@pytest.mark.skipif(not hasattr(signal, "SIGKILL"), reason="POSIX only")
def test_a_dead_audio_process_is_replaced_on_start(host):
    host.launch()
    first = host.pid
    os.kill(first, signal.SIGKILL)
    assert _wait(lambda: not host.alive, 5)
    host.start({"model": "no-such-model", "backend": "pipewire"})
    assert host.pid != first
    assert _wait(lambda: not host.running)
    assert [e["event"] for e in host.events][-2:] == ["error", "stopped"]


# --- the TUI ----------------------------------------------------------------------------

@pytest.fixture
def tui(monkeypatch):
    pytest.importorskip("textual.app")
    monkeypatch.setenv("POISE_DISABLE_FILE_LOG", "1")
    saved = {s: signal.getsignal(s) for s in
             (signal.SIGTERM, signal.SIGINT, getattr(signal, "SIGHUP", 0)) if s}
    from stream_denoiser.tui.app import PoiseApp
    yield PoiseApp
    for sig, handler in saved.items():
        signal.signal(sig, handler)


def test_tui_starts_its_audio_process_and_follows_its_events(tui):
    """Inside Textual, sys.stderr is a print capture with fileno() -1,
    which once made every spawn fail."""
    import asyncio
    from stream_denoiser.tui.app import AudioEvent
    from stream_denoiser.tui.widgets import StatusLine

    async def run():
        app = tui(model="rnnoise")
        async with app.run_test(size=(140, 44)) as pilot:
            await pilot.pause(0.2)
            assert app.audio.alive
            # A session that ends on its own resets the UI and keeps
            # the reason on the status line.
            app.is_processing = True
            app.post_message(AudioEvent({"event": "error",
                                         "notice": "Capture device not found."}))
            app.post_message(AudioEvent({"event": "stopped", "stats": {}}))
            await pilot.pause(0.2)
            assert not app.is_processing
            status = app.query_one("#status-line", StatusLine)
            assert status.current_message == "Capture device not found."
            await pilot.press("q")
        assert not app.audio.alive

    asyncio.run(run())
