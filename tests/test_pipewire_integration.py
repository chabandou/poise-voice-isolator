"""Integration tests for the PipeWire node (gated on a live PipeWire).

The node plays into a temporary null sink instead of the speakers, and
test audio is played into the node by name, so nothing is audible. Tests
that make the node the default sink put the previous default back.
"""
import os
import shutil
import signal
import subprocess
import sys
import threading
import time

import numpy as np
import pytest

SR = 48000
OUT_SINK = "poise-pw-test-out"
NODE = "Poise_PW_Test"


def _available():
    try:
        import pulsectl
        if getattr(pulsectl, "_is_stub", False):
            return False
        from stream_denoiser.backends.pipewire_backend import (
            pipewire_node_status)
        from stream_denoiser.backends.pulse_simple import _load_library
        _load_library()
        return pipewire_node_status()[0] and shutil.which("pactl")
    except Exception:
        return False


pytestmark = [pytest.mark.integration,
              pytest.mark.skipif(not _available(),
                                 reason="needs PipeWire + libpoise_pw.so")]


def _pactl(*args):
    return subprocess.run(["pactl", *args], capture_output=True, text=True,
                          timeout=10)


def _sinks():
    out = _pactl("list", "sinks", "short").stdout
    return [l.split("\t")[1] for l in out.splitlines() if "\t" in l]


def _default():
    return _pactl("get-default-sink").stdout.strip()


def _wait_until(cond, timeout):
    deadline = time.monotonic() + timeout
    while not cond():
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)
    return True


@pytest.fixture
def out_sink():
    proc = _pactl("load-module", "module-null-sink", f"sink_name={OUT_SINK}")
    if proc.returncode != 0:
        pytest.skip(f"could not create null sink: {proc.stderr}")
    module = proc.stdout.strip()
    try:
        assert _wait_until(lambda: OUT_SINK in _sinks(), 3)
        yield OUT_SINK
    finally:
        _pactl("unload-module", module)


@pytest.fixture
def keep_default():
    before = _default()
    yield before
    if before and _default() != before:
        _pactl("set-default-sink", before)


def _node(target, engine_latency=0):
    from stream_denoiser.backends.pipewire_node import PipeWireNode
    from stream_denoiser.constants import (
        PW_FADE_SAMPLES, PW_MARGIN_SAMPLES, PW_QUANTUM)
    return PipeWireNode(frame=512, engine_latency=engine_latency,
                        quantum=PW_QUANTUM, margin=PW_MARGIN_SAMPLES,
                        fade=PW_FADE_SAMPLES, dry_gain=1.0, node_name=NODE,
                        description="Poise PW Test", target=target)


def _locate(rec, seg):
    corr = np.correlate(rec, seg, mode="valid")
    k = int(np.argmax(np.abs(corr)))
    peak = float(abs(corr[k]))
    norm = float(np.sqrt(np.dot(seg, seg) * np.dot(rec[k:k + len(seg)],
                                                    rec[k:k + len(seg)])))
    return k, peak / max(norm, 1e-12)


def test_delay_stays_exact_through_a_worker_stall(out_sink):
    """Two marks 4 s apart in the input are exactly 4 s apart in the
    output, although the worker stopped for 300 ms between them."""
    from stream_denoiser.backends.pulse_simple import (
        PulseCapture, PulsePlayback)
    node = _node(out_sink)
    stop = threading.Event()
    stalled = threading.Event()

    def worker():
        buf = np.empty(512, np.float32)
        frames = 0
        while not stop.is_set():
            k = node.wait_frame(buf, 100)
            if k == -2:
                break
            if k < 0:
                continue
            frames += 1
            if frames == 300 and not stalled.is_set():  # ~3 s in
                stalled.set()
                time.sleep(0.3)
            node.put_frame(k, buf)

    try:
        assert _wait_until(lambda: NODE in _sinks(), 3), node.status()
        threading.Thread(target=worker, daemon=True).start()
        rng = np.random.default_rng(7)
        sig = (rng.standard_normal(SR * 7) * 0.2).astype(np.float32)

        def play():
            # 100 ms blocks (300 ms buffer): the test's own stream must
            # not underrun, or it would shift the input itself.
            with PulsePlayback(NODE, 4800) as p:
                st = np.column_stack([sig, sig])
                for i in range(0, len(st) - 4800 + 1, 4800):
                    p.write(st[i:i + 4800])

        rec = []
        with PulseCapture(f"{out_sink}.monitor", 4800) as cap:
            player = threading.Thread(target=play, daemon=True)
            player.start()
            for _ in range(int(8.5 * SR / 4800)):
                rec.append(cap.read()[0][:, 0].copy())
            player.join(5)
        rec = np.concatenate(rec)

        assert stalled.is_set()
        p1, c1 = _locate(rec, sig[SR:SR + SR // 4])
        p2, c2 = _locate(rec, sig[5 * SR:5 * SR + SR // 4])
        assert c1 > 0.95 and c2 > 0.95, (c1, c2)
        assert p2 - p1 == 4 * SR, f"output moved by {p2 - p1 - 4 * SR} samples"
        st = node.stats()
        assert st["frames_dry"] > 0, st     # the stall played unprocessed
        assert st["resyncs"] == 0, st
        assert node.status()[2] is None
    finally:
        stop.set()
        node.close()


def test_apps_see_the_node_latency(out_sink):
    """A client playing into the node is told about the node's delay, so
    players can hold video back by it."""
    from stream_denoiser.backends.pulse_simple import PulsePlayback

    def client_latency_ms(sink):
        vals = []
        with PulsePlayback(sink, 480) as p:
            z = np.zeros((480, 2), np.float32)
            t0 = time.monotonic()
            while time.monotonic() - t0 < 1.5:
                p.write(z)
                if time.monotonic() - t0 > 0.75:
                    vals.append(p.latency_ms())
        return float(np.median(vals))

    direct = client_latency_ms(out_sink)
    node = _node(out_sink, engine_latency=1536)
    try:
        assert _wait_until(lambda: NODE in _sinks(), 3)
        through = client_latency_ms(NODE)
        expected = node.latency_samples * 1000.0 / SR
        assert abs((through - direct) - expected) < 10.0, (
            direct, through, expected)
    finally:
        node.close()


def _processor():
    from stream_denoiser.engines.base import DenoiseEngine
    from stream_denoiser.processor import DenoiserAudioProcessor

    class Passthrough(DenoiseEngine):
        name = "passthrough"
        required_frame_size = 512

        def process_frame(self, frame):
            return frame

        def reset(self):
            pass

    return DenoiserAudioProcessor(Passthrough(), target_sr=SR,
                                  frame_size=512, enable_aad=False)


def test_run_loop_makes_node_default_and_restores(out_sink, keep_default):
    from stream_denoiser.backends.pipewire_backend import run_pipewire_loop
    stop = threading.Event()
    errors = []

    def run():
        try:
            run_pipewire_loop(_processor(), sink=out_sink, should_stop=stop,
                              node_name=NODE, description="Poise PW Test")
        except Exception as e:  # pragma: no cover - reported below
            errors.append(e)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    try:
        assert _wait_until(lambda: _default() == NODE or errors, 5), errors
        assert not errors
    finally:
        stop.set()
        t.join(5)
    assert not t.is_alive() and not errors
    assert _default() == keep_default
    assert _wait_until(lambda: NODE not in _sinks(), 3)


_KILL_HELPER = f"""
import threading
from stream_denoiser.backends.pipewire_backend import run_pipewire_loop
from stream_denoiser.engines.base import DenoiseEngine
from stream_denoiser.processor import DenoiserAudioProcessor

class Passthrough(DenoiseEngine):
    name = "passthrough"
    required_frame_size = 512
    def process_frame(self, frame):
        return frame
    def reset(self):
        pass

p = DenoiserAudioProcessor(Passthrough(), target_sr=48000, frame_size=512,
                           enable_aad=False)
run_pipewire_loop(p, sink={OUT_SINK!r}, node_name={NODE!r},
                  description="Poise PW Test")
"""


def test_killed_process_leaves_no_sink_behind(out_sink, keep_default,
                                              tmp_path):
    """SIGKILL (no cleanup at all): the sink goes away with the process
    and the default falls back to a sink that exists."""
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log = tmp_path / "helper.log"
    with open(log, "w") as fh:
        helper = subprocess.Popen([sys.executable, "-c", _KILL_HELPER],
                                  cwd=repo, stdout=fh, stderr=subprocess.STDOUT)
    try:
        assert _wait_until(lambda: helper.poll() is not None
                           or _default() == NODE, 15), log.read_text()
        assert helper.poll() is None, log.read_text()
        helper.send_signal(signal.SIGKILL)
        helper.wait(5)
        assert _wait_until(lambda: NODE not in _sinks(), 3)
        assert _wait_until(lambda: _default() in _sinks(), 3), _default()
        assert _default() != NODE
    finally:
        if helper.poll() is None:
            helper.kill()
            helper.wait()


# --- the audio process ---------------------------------------------------------

def _audio_host():
    from stream_denoiser.audio_host import AudioHost
    from stream_denoiser.engines import available_models
    models = available_models()
    if not models:
        pytest.skip("no denoising model available")
    events = []
    host = AudioHost(on_event=events.append)
    config = {"model": models[0], "backend": "pipewire", "node_name": NODE,
              "description": "Poise PW Test", "route_default": False}
    return host, events, config


def test_audio_process_runs_a_session(out_sink, keep_default):
    """The node lives in the audio process: it appears, stats come back,
    and stop removes it. The default sink is left alone here."""
    import logging
    from stream_denoiser import audio_gc
    host, events, config = _audio_host()
    lines = []
    handler = logging.Handler(logging.INFO)
    handler.emit = lambda record: lines.append(record.getMessage())
    audio_gc._logger.addHandler(handler)
    try:
        host.start(dict(config, output_device=out_sink))
        assert _wait_until(lambda: NODE in _sinks() or not host.running, 15)
        assert host.running, events
        assert _wait_until(lambda: host.stats.get("frame_size"), 5)
        final = host.stop()
        assert not host.running and "frame_count" in final
        assert _wait_until(lambda: NODE not in _sinks(), 3)
        assert [e["event"] for e in events if e["event"] != "ready"] \
            == ["running", "stopped"]
        # The child's gc line, forwarded to this process.
        assert any(l.startswith("gc: off for the run") for l in lines)
        assert _default() == keep_default
    finally:
        audio_gc._logger.removeHandler(handler)
        host.shutdown()


def test_killed_audio_process_ends_the_session(out_sink, keep_default):
    from stream_denoiser.audio_host import CRASH_NOTICE
    host, events, config = _audio_host()
    try:
        host.start(dict(config, output_device=out_sink))
        assert _wait_until(lambda: NODE in _sinks() or not host.running, 15)
        os.kill(host.pid, signal.SIGKILL)
        assert _wait_until(lambda: not host.running, 5)
        assert [e["event"] for e in events][-2:] == ["error", "stopped"]
        assert events[-2]["notice"] == CRASH_NOTICE
        assert _wait_until(lambda: NODE not in _sinks(), 3)
    finally:
        host.shutdown()
