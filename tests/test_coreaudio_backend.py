"""The native Core Audio path on macOS: library binding, backend
selection, the 48 kHz-or-refuse rule, the documented stat set, the
capture-health distinction and the exit routes (fakes; no device, no TCC
grant and no system audio needed).

The dylib's own behaviour is exercised by the `integration` test at the
end, which needs a device and the System Audio Recording grant.
"""
import contextlib
import logging
import os
import sys
import time

import numpy as np
import pytest

from stream_denoiser.backends import coreaudio_backend as cb
from stream_denoiser.backends import coreaudio_node as cn
from stream_denoiser.backends import node_loop
from stream_denoiser.backends.delay_core import STAT_NAMES, WAIT_STOPPED, \
    WAIT_TIMEOUT
from stream_denoiser.backends.node_loop import NodeError


# --- the library's surface, in Python --------------------------------------

class _FakeLib:
    """A stand-in for libpoise_coreaudio.dylib: one node, counters the
    test sets, and a record of what was asked of it."""

    def __init__(self, frame=512, delay=1344, io_latency=1147,
                 stats=None, status=None, refuse=None):
        self.frame = frame
        self.delay = delay
        self.io_latency = io_latency
        self.status = status
        self.refuse = refuse          # message poise_ca_new fails with
        self.created = []             # poise_ca_new's arguments
        self.destroyed = 0
        self.values = dict.fromkeys(cn.CA_STAT_NAMES, 0)
        self.values.update(stats or {})

    def poise_ca_new(self, output, frame, engine_latency, quantum, margin,
                     fade, dry_gain, rate, tap_mute, err, errlen):
        self.created.append(dict(
            output=output, frame=frame, engine_latency=engine_latency,
            quantum=quantum, margin=margin, fade=fade, dry_gain=dry_gain,
            rate=rate, tap_mute=tap_mute))
        if self.refuse:
            err.value = self.refuse.encode()
            return None
        return object()               # the handle

    def poise_ca_destroy(self, handle):
        self.destroyed += 1

    def poise_ca_core(self, handle):
        return "core"

    def poise_ca_frame(self, handle):
        return self.frame

    def poise_ca_delay_samples(self, handle):
        return self.delay

    def poise_ca_io_latency_samples(self, handle):
        return self.io_latency

    def poise_ca_status(self, handle, err, errlen):
        if self.status:
            err.value = self.status.encode()
            return 1
        return 0

    def poise_ca_get_stats(self, handle, out, n):
        for i, name in enumerate(cn.CA_STAT_NAMES[:n]):
            out[i] = self.values[name] & ((1 << 64) - 1)

    def poise_ca_stat_count(self):
        return len(cn.CA_STAT_NAMES)

    # poise_core_*, as delay_core.CoreOps calls them
    def poise_core_get_stats(self, core, out, n):
        for i, name in enumerate(STAT_NAMES[:n]):
            out[i] = self.values.get(name, 0)

    def poise_core_delay(self, core):
        return self.delay

    def poise_core_stop(self, core):
        pass


def _node(lib=None, **kwargs):
    args = dict(output=None, frame=512, engine_latency=1536, quantum=512,
                margin=256, fade=64, dry_gain=1.0)
    args.update(kwargs)
    return cn.CoreAudioNode(lib=lib if lib is not None else _FakeLib(), **args)


# --- the binding -----------------------------------------------------------

def test_unavailable_is_a_runtime_error_so_other_suites_skip():
    """tests/test_pipewire_core.py catches RuntimeError when the native
    core is missing: a macOS CI box without the dylib must skip there."""
    assert issubclass(cn.CoreAudioUnavailable, RuntimeError)
    assert not issubclass(cn.CoreAudioUnavailable, NodeError)
    assert issubclass(cn.CoreAudioError, NodeError)


def test_library_lookup_says_how_to_build_it(monkeypatch, tmp_path):
    monkeypatch.setattr(cn, "_lib", None)
    monkeypatch.setattr(cn, "_candidate_paths",
                        lambda: [str(tmp_path / "build-it.dylib")])
    monkeypatch.setattr(cn.sys, "platform", "darwin")
    with pytest.raises(cn.CoreAudioUnavailable, match="make -C native"):
        cn.load_library()


def test_the_built_library_reports_the_counts_bound_here():
    """load_library() refuses a build whose enums disagree with the names
    tuples; on a host without the dylib it says how to build one."""
    try:
        lib = cn.load_library()
    except cn.CoreAudioUnavailable as e:
        pytest.skip(f"native node not built here: {e}")
    assert lib.poise_ca_stat_count() == len(cn.CA_STAT_NAMES)
    assert lib.poise_core_stat_count() == len(STAT_NAMES)


def test_node_asks_for_the_device_and_48k_float32():
    lib = _FakeLib()
    node = _node(lib, output="MacBook Pro Speakers")
    assert lib.created[0]["output"] == b"MacBook Pro Speakers"
    assert (lib.created[0]["rate"], lib.created[0]["tap_mute"]) == (48000, 1)
    assert node.rate == 48000
    node.close()


def test_node_reports_a_refused_device_with_its_real_rate():
    lib = _FakeLib(refuse='refusing to run: the aggregate input stream is '
                           '44100 Hz, 2 ch, flags 0x29, not the requested '
                           '48000 Hz Float32 (device "AirPods", runs at '
                           '44100 Hz)')
    with pytest.raises(cn.CoreAudioError, match="44100 Hz.*AirPods"):
        _node(lib, output="AirPods")


def test_node_latency_is_io_plus_delay_plus_the_engine():
    node = _node(_FakeLib(io_latency=1147, delay=1344))
    assert node.latency_samples == 1147 + 1344 + 1536
    node.close()


def test_node_stats_map_the_native_order_and_read_the_signed_ones():
    lib = _FakeLib(stats={"callbacks": 764, "input_frames": 391168,
                          "overloads": 2, "quiet_frames": 9, "saw_signal": 1,
                          "drift_samples": -17, "time_delta_min": -3,
                          "time_delta_max": 1180, "restarts": 1,
                          "tap_alive": 1})
    node = _node(lib)
    st = node.node_stats()
    assert (st["callbacks"], st["input_frames"], st["overloads"]) == \
        (764, 391168, 2)
    assert (st["drift_samples"], st["time_delta_min"]) == (-17, -3)
    assert st["time_delta_max"] == 1180
    # The two device-change counters exist natively as placeholders.
    assert (st["restarts"], st["tap_alive"]) == (1, 1)
    node.close()


def test_node_error_is_none_until_the_node_stops_itself():
    lib = _FakeLib()
    node = _node(lib)
    assert node.error() is None
    lib.status = "poise stopped and audio was restored: the audio device " \
                 "stopped calling back for 250 ms"
    assert "audio was restored" in node.error()
    node.close()


def test_close_destroys_the_tap_once_and_leaves_the_exit_net():
    lib = _FakeLib()
    node = _node(lib)
    node.close()
    node.close()
    assert lib.destroyed == 1
    assert node not in cn._live


def test_the_exit_net_destroys_a_node_nobody_closed():
    """atexit route (the mute contract): a node still alive at exit is destroyed,
    which is what unmutes the Mac."""
    lib = _FakeLib()
    node = _node(lib)
    assert node in cn._live
    cn._destroy_live_nodes()
    assert lib.destroyed == 1
    assert not cn._live


# --- backend selection -----------------------------------------------------

def test_status_off_macos_is_unavailable(monkeypatch):
    monkeypatch.setattr(cb.sys, "platform", "linux")
    assert cb.coreaudio_status() == (False, "macOS only")


def _mac(monkeypatch, version="27.0.1", machine="arm64"):
    monkeypatch.setattr(cb.sys, "platform", "darwin")
    monkeypatch.setattr(cb.platform, "mac_ver",
                        lambda *a: (version, ("", "", ""), machine))
    monkeypatch.setattr(cb.platform, "machine", lambda: machine)


def test_status_refuses_an_os_older_than_the_first_tap(monkeypatch):
    _mac(monkeypatch, version="13.6.9")
    ok, detail = cb.coreaudio_status()
    assert not ok and "14.2" in detail


def test_status_refuses_an_intel_mac(monkeypatch):
    _mac(monkeypatch, machine="x86_64")
    ok, detail = cb.coreaudio_status()
    assert not ok and "Apple Silicon" in detail


def test_status_needs_the_library(monkeypatch):
    _mac(monkeypatch)

    def missing():
        raise cn.CoreAudioUnavailable("libpoise_coreaudio.dylib not found "
                                      "(build it: make -C native/poise_coreaudio)")
    monkeypatch.setattr(cb, "load_library", missing)
    ok, detail = cb.coreaudio_status()
    assert not ok and "make -C native" in detail


def test_select_returns_coreaudio_when_it_can_run(monkeypatch):
    monkeypatch.setattr(cb, "coreaudio_status", lambda: (True, "native"))
    assert cb.select_coreaudio_backend("auto") == ("coreaudio", "native")
    assert cb.select_coreaudio_backend("CoreAudio")[0] == "coreaudio"


def test_select_fails_rather_than_falling_back(monkeypatch):
    monkeypatch.setattr(cb, "coreaudio_status", lambda: (False, "not built"))
    for preference in ("auto", "coreaudio"):
        with pytest.raises(RuntimeError, match="not built"):
            cb.select_coreaudio_backend(preference)
    with pytest.raises(RuntimeError, match="unknown macOS backend"):
        cb.select_coreaudio_backend("portaudio")


def test_margin_env_override(monkeypatch):
    from stream_denoiser.backends._loop_util import margin_samples

    def margin():
        return margin_samples(cb.MARGIN_ENV, cb.MARGIN_SAMPLES, cb.RATE)

    monkeypatch.delenv(cb.MARGIN_ENV, raising=False)
    assert margin() == cb.MARGIN_SAMPLES
    monkeypatch.setenv(cb.MARGIN_ENV, "10")
    assert margin() == 480
    monkeypatch.setenv(cb.MARGIN_ENV, "lots")
    assert margin() == cb.MARGIN_SAMPLES


# --- what the tap delivers (capture health) --------------------------------------

def test_capture_state_separates_zeros_from_not_capturing():
    base = dict.fromkeys(cn.CA_STAT_NAMES, 0)
    assert cb.capture_state(base) == "no-audio"
    assert cb.capture_state({**base, "input_frames": 48000}) == "silent"
    assert cb.capture_state({**base, "input_frames": 48000,
                             "saw_signal": 1}) == "signal"


# --- the loop --------------------------------------------------------------

class _FakeNode:
    """A node for the loop: frames come from ``script``, counters from
    ``stats``/``node``, nothing touches a device."""

    frame = 4
    rate = 48000
    engine_latency = 1536
    latency_samples = 4027
    io_latency_samples = 1147
    delay_samples = 1344

    def __init__(self, script=(WAIT_STOPPED,), error=None, stats=None,
                 node=None, **kwargs):
        self.kwargs = kwargs
        self.script = list(script)
        self.put = {}
        self._error = error
        self._stats = list(stats or [])
        self._node = list(node or [])
        self.closed = 0
        self._last = dict.fromkeys(STAT_NAMES, 0)
        self._last_node = dict.fromkeys(cn.CA_STAT_NAMES, 0)
        self._last_node["tap_alive"] = 1      # the native placeholder

    def stats(self):
        if self._stats:
            self._last = dict(self._last, **self._stats.pop(0))
        return self._last

    def node_stats(self):
        if self._node:
            self._last_node = dict(self._last_node, **self._node.pop(0))
        return self._last_node

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

    def close(self):
        self.closed += 1


class _Doubler:
    def process_chunk(self, x):
        assert x.dtype == np.float32 and x.shape == (4,)
        return x * 2

    def get_stats(self):
        return {"frame_count": 1}

    def setup_resampler(self, rate):
        pass

    def setup_output_resampler(self, rate):
        pass


def _worker_loop(node, should_stop=None):
    node_loop.worker_loop(node, _Doubler(), should_stop, None, 1.0,
                          time.time(), log_sync=cb._log_sync,
                          log_events=cb._log_events, error=cn.CoreAudioError)


class _FakeProcessor(_Doubler):
    """The processor the loop needs, with 4-sample frames."""

    frame_size = 4
    output_gain = 2.0

    def __init__(self):
        self.resamplers = []

    def setup_resampler(self, rate):
        self.resamplers.append(rate)

    def setup_output_resampler(self, rate):
        self.resamplers.append(rate)

    class engine:
        name = "fake"
        latency_samples = 1536


def test_worker_processes_each_frame_and_returns_it():
    node = _FakeNode([0, 1, WAIT_TIMEOUT, 2])
    _worker_loop(node)
    assert sorted(node.put) == [0, 1, 2]
    np.testing.assert_allclose(node.put[2], 4.0)


def test_worker_stops_on_request():
    node = _FakeNode([0, 1, 2])
    _worker_loop(node, lambda: True)
    assert node.put == {}


def test_worker_raises_a_stopped_node_as_core_audio_error():
    node = _FakeNode([WAIT_TIMEOUT],
                     error="poise stopped and audio was restored: the audio "
                           "device stopped calling back for 250 ms")
    with pytest.raises(cn.CoreAudioError, match="audio was restored"):
        _worker_loop(node)


@contextlib.contextmanager
def _log_lines(logger):
    lines = []
    handler = logging.Handler(logging.INFO)
    handler.emit = lambda record: lines.append(record.getMessage())
    logger.addHandler(handler)
    try:
        yield lines
    finally:
        logger.removeHandler(handler)


def test_sync_line_reports_the_device_rate_and_the_documented_stat_set():
    node = _FakeNode()
    # A rate that is not DEFAULT_SAMPLE_RATE: the line must scale its
    # milliseconds by the node's rate, not by the constant.
    node.rate = 24000
    node.latency_samples = 24000
    with _log_lines(cb._logger) as lines:
        cb._log_sync(node)
    line = lines[-1]
    assert "rate=24000" in line
    assert "latency=1000.0ms" in line
    for field in ("dry=", "skipped=", "delay_changes=", "resyncs=",
                  "input_gaps=", "quantum_max=", "overloads=", "restarts=",
                  "tap_alive=", "capture=", "silent=", "saw_signal=",
                  "drift=", "time_delta="):
        assert field in line, field
    for dropped in ("fifo", "mmcss", "render_queue", "headroom", "holes"):
        assert dropped not in line


def test_sync_line_reports_a_stopped_node_as_a_dead_tap():
    node = _FakeNode(error="poise stopped and audio was restored")
    with _log_lines(cb._logger) as lines:
        cb._log_sync(node)
    assert "tap_alive=0" in lines[-1]     # whatever the native counter says


def test_events_report_the_node_s_counters_and_a_change_of_capture():
    node = _FakeNode(node=[
        {"input_frames": 4096, "quiet_frames": 4096, "saw_signal": 0,
         "overloads": 0, "dropped": 0},
        {"input_frames": 8192, "quiet_frames": 5000, "saw_signal": 1,
         "overloads": 2, "dropped": 1},
    ])
    seen = {"frames_dry": 0, "delay_changes": 0, "resyncs": 0,
            "input_gaps": 0}
    with _log_lines(cb._logger) as lines:
        seen = cb._log_events(node, seen, 0.0, 0.0)
        assert seen["capture"] == "silent"
        seen = cb._log_events(node, seen, 0.0, 0.0)
    text = "\n".join(lines)
    assert "capture is silent" in text
    assert "capture is signal" in text
    assert "an output buffer could not be filled (audible gap) (2)" in text
    assert "captured frames never reached the core (1)" in text
    assert text.count("capture is") == 2


def test_loop_pins_the_engine_to_48k_and_reports_the_node_s_counters(
        monkeypatch):
    node = _FakeNode([0, WAIT_STOPPED],
                     node=[{"frames_dry": 3, "overloads": 1}])

    def fake_node(**kwargs):
        node.kwargs = kwargs
        return node

    monkeypatch.setattr(cb, "CoreAudioNode", fake_node)
    processor = _FakeProcessor()
    reported = []
    cb.run_coreaudio_loop(processor, "Speakers", stats_interval_sec=0.0,
                          on_stats=lambda stats, elapsed: reported.append(stats))
    assert processor.resamplers == [48000, 48000]
    assert node.kwargs["rate"] == 48000 and node.kwargs["output"] == "Speakers"
    assert node.closed == 1
    assert reported[-1]["overloads"] == 1
    assert reported[-1]["latency"] == node.latency_samples


def test_a_device_that_cannot_give_48k_is_refused_by_name(monkeypatch):
    def refuse(**kwargs):
        raise cn.CoreAudioError(
            'refusing to run: the aggregate output stream is 44100 Hz, 2 ch, '
            'flags 0x29, not the requested 48000 Hz Float32 (device '
            '"AirPods", runs at 44100 Hz)')

    monkeypatch.setattr(cb, "CoreAudioNode", refuse)
    processor = _FakeProcessor()
    with pytest.raises(cb.CoreAudioStartError, match='44100 Hz.*"AirPods"'):
        cb.run_coreaudio_loop(processor)
    # The engine was pinned to 48 kHz before the node was even created.
    assert processor.resamplers == [48000, 48000]


def test_a_stop_while_the_prompt_is_up_destroys_the_node(monkeypatch):
    """Ctrl-C during poise_ca_new (the System Audio Recording prompt waits
    for a person) must not leave a tap behind: the node is destroyed as
    soon as it exists (the mute contract)."""
    import threading

    stop = threading.Event()
    made = []

    def slow(**kwargs):
        made.append(_FakeNode(**kwargs))
        stop.set()            # the user gives up while the prompt is up
        time.sleep(0.1)       # the answer arrives a little later
        return made[-1]

    monkeypatch.setattr(cb, "CoreAudioNode", slow)
    processor = _FakeProcessor()
    stats = cb.run_coreaudio_loop(processor, should_stop=stop)
    assert stats == processor.get_stats()
    assert made and made[0].closed == 1


def test_creation_hands_the_node_over_or_raises_its_error():
    made = _FakeNode()
    assert cb._NodeCreation(lambda: made).start().wait(lambda: False) is made

    def refuse():
        raise cb.CoreAudioStartError("no output device matches")
    creation = cb._NodeCreation(refuse).start()
    with pytest.raises(cb.CoreAudioStartError, match="no output device"):
        creation.wait(lambda: False)


# --- the real thing --------------------------------------------------------

def _real_node_usable() -> bool:
    """A live tap mutes every app while it runs, so it is opt-in."""
    if sys.platform != "darwin" or not os.environ.get("POISE_COREAUDIO_LIVE"):
        return False
    try:
        return cb.coreaudio_status()[0]
    except Exception:
        return False


@pytest.mark.integration
@pytest.mark.skipif(not _real_node_usable(),
                    reason="set POISE_COREAUDIO_LIVE=1 on a Mac with macOS "
                           "14.2+, the built dylib, an output device, the "
                           "System Audio Recording grant and audio playing")
def test_live_node_delivers_frames_and_stops_cleanly():
    """Real tap: a few frames arrive, then close() unmutes the Mac.

    Audio has to be playing: with nothing tapped, the aggregate's IOProc
    never runs and the native node gives up after 3 s.
    """
    node = cn.CoreAudioNode(output=None, frame=512, engine_latency=1536,
                            quantum=512, margin=256, fade=64, dry_gain=1.0)
    try:
        buf = np.empty(512, np.float32)
        got = [node.wait_frame(buf, 100) for _ in range(5)]
        assert any(k >= 0 for k in got), "the tap delivered no frame"
        st = node.node_stats()
        assert st["callbacks"] > 0 and st["input_frames"] > 0
        assert st["rt_policy"] == 1
    finally:
        node.close()
    assert node.error() is None
