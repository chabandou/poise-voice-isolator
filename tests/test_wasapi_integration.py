"""Integration tests for the native WASAPI path (gated on Windows with
VB-Cable, an output device and poise_wasapi.dll).

Nothing is played into the cable, so the output device gets the cable's
silence: the tests check that the path runs in real time, feeds the
worker, reports errors and stops cleanly.
"""
import sys
import threading
import time

import numpy as np
import pytest

SR = 48000


def _devices():
    """(CABLE Output, first real output device) WASAPI names, or None."""
    if sys.platform != "win32":
        return None
    try:
        import sounddevice as sd
        from stream_denoiser.backends.wasapi_node import load_library
        load_library()
    except Exception:
        return None
    capture = render = None
    for d in sd.query_devices():
        if sd.query_hostapis(d["hostapi"])["name"] != "Windows WASAPI":
            continue
        if "CABLE Output" in d["name"] and d["max_input_channels"]:
            capture = d["name"]
        elif d["max_output_channels"] and "CABLE" not in d["name"]:
            render = render or d["name"]
    return (capture, render) if capture and render else None


DEVICES = _devices()

pytestmark = [pytest.mark.integration,
              pytest.mark.skipif(DEVICES is None,
                                 reason="needs Windows, VB-Cable, an output "
                                        "device and poise_wasapi.dll")]


def _node(capture=None, render=None):
    from stream_denoiser.backends.wasapi_node import WasapiNode
    return WasapiNode(capture=capture or DEVICES[0],
                      render=render or DEVICES[1], frame=512,
                      engine_latency=1536, margin=1024, fade=64,
                      dry_gain=1.0, fifo_safety=240, render_fill=0)


def test_runs_in_real_time_and_feeds_the_worker():
    """Steady state, after a settling time: VB-Cable's first packets can
    come bunched (a few short reads in the first second on real hardware,
    which the bridge answers by raising its level), and the worker here
    is a plain thread, so a frame can be late while things start."""
    node = _node()
    try:
        buf = np.empty(512, np.float32)
        got = 0
        settled = None
        t0 = time.monotonic()
        while time.monotonic() - t0 < 3.0:
            k = node.wait_frame(buf, 100)
            if k >= 0:
                node.put_frame(k, buf)
                got += 1
            if settled is None and time.monotonic() - t0 >= 1.5:
                settled = {**node.stats(), **node.io_stats()}
        io, st, error = node.io_stats(), node.stats(), node.error()
    finally:
        node.close()
    assert error is None
    assert io["capture_frames"] == pytest.approx(3 * SR, rel=0.1)
    assert io["render_frames"] == pytest.approx(3 * SR, rel=0.1)
    assert got == pytest.approx(3 * SR / 512, rel=0.15)
    assert io["capture_glitches"] == 0
    assert io["fifo_resyncs"] == 0
    assert io["fifo_level"] > io["render_period"]
    assert st["frames_late"] - settled["frames_late"] == 0
    assert io["fifo_starved"] - settled["fifo_starved"] == 0
    assert io["render_underruns"] == 0


def test_latency_is_reported_from_the_parts():
    node = _node()
    try:
        assert node.delay_samples == 512 + node.io_stats()["render_period"] \
            + 64 + 1024
        assert node.latency_samples == (node.io_latency_samples
                                        + node.delay_samples + 1536)
    finally:
        node.close()


def test_unknown_device_is_an_error_not_a_hang():
    from stream_denoiser.backends.wasapi_node import WasapiError
    with pytest.raises(WasapiError, match="capture device"):
        _node(capture="No Such Device (Poise test)")


def test_stop_wakes_a_waiting_worker():
    from stream_denoiser.backends.wasapi_node import WAIT_STOPPED
    node = _node()
    results = []

    def worker():
        buf = np.empty(512, np.float32)
        while True:
            k = node.wait_frame(buf, 1000)
            if k == WAIT_STOPPED:
                results.append(k)
                return

    th = threading.Thread(target=worker)
    th.start()
    time.sleep(0.3)
    node.stop()
    th.join(2.0)
    node.close()
    assert results == [WAIT_STOPPED]


def test_run_loop_processes_and_stops():
    from stream_denoiser.backends.wasapi_backend import run_wasapi_loop
    from stream_denoiser.engines.base import DenoiseEngine
    from stream_denoiser.processor import DenoiserAudioProcessor

    class Passthrough(DenoiseEngine):
        name = "passthrough"
        required_frame_size = 512
        latency_samples = 0
        speech_prob = None

        def process_frame(self, frame):
            return frame

        def reset(self):
            pass

        def close(self):
            pass

    proc = DenoiserAudioProcessor(Passthrough(), frame_size=512,
                                  enable_aad=False)
    started = []
    t0 = time.monotonic()
    stats = run_wasapi_loop(proc, DEVICES[0], DEVICES[1],
                            should_stop=lambda: time.monotonic() - t0 > 2.0,
                            on_started=lambda: started.append(True))
    assert started == [True]
    assert stats["frame_count"] == pytest.approx(2 * SR / 512, rel=0.2)
