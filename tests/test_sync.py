"""Regression tests for the Linux minutes-scale A/V desync.

Two causes, both measured on PipeWire 1.6:

* Clock drift: the Poise_Capture null sink ran on its own timer (system
  clock) while the real sink runs on the sound card crystal (500 ppm slow
  here). The loop is paced by playback, so capture surplus piled up and
  never drained. Fixed by putting both streams in one PipeWire node group
  (one driver, one clock) -- see pulse_simple.NODE_GROUP.
* Stalls: a loop stall leaves its length behind as capture backlog for
  good (a 300 ms stall became 300 ms of permanent lag). CaptureBacklogGuard
  discards it.
"""
import os

import pytest

from stream_denoiser.sync import (
    SYNC_DROP_THRESHOLD_MS,
    SYNC_WINDOW_SEC,
    CaptureBacklogGuard,
)

SR = 48000
BLOCK = 512
BLOCK_MS = BLOCK * 1000.0 / SR
QUANTUM = 1024  # PipeWire delivers capture audio in bursts of this size


def _simulate(guard, seconds, capture_ppm=0.0, playback_ppm=0.0,
              offset_ms=0.0, stalls=(), offset_changes=()):
    """Playback-paced loop over a burst-delivering capture stream.

    Capture audio arrives in QUANTUM bursts; a read waits if fewer than
    BLOCK samples are buffered; the write takes one block at the card's
    rate. The guard sees the reported latency = offset + buffered audio.
    Returns the true capture backlog (ms) right after each read, sampled
    once per second.
    """
    cap_rate = SR * (1 + capture_ppm * 1e-6)
    play_rate = SR * (1 + playback_ppm * 1e-6)
    t = 0.0
    read = 0
    stalls = list(stalls)
    offset_changes = list(offset_changes)
    trace = []
    next_trace = 1.0

    def delivered(at):
        return int(at * cap_rate / QUANTUM) * QUANTUM

    while t < seconds:
        blocked = delivered(t) - read < BLOCK
        if blocked:
            t = (int(t * cap_rate / QUANTUM) + 1) * QUANTUM / cap_rate
        read += BLOCK
        if offset_changes and t >= offset_changes[0][0]:
            offset_ms = offset_changes.pop(0)[1]
        buffered_ms = (delivered(t) - read) * 1000.0 / SR
        for _ in range(guard.observe(offset_ms + buffered_ms, blocked, t)):
            read += BLOCK
        if t >= next_trace:
            trace.append((delivered(t) - read) * 1000.0 / SR)
            next_trace += 1.0
        dt = BLOCK / play_rate
        if stalls and t >= stalls[0][0]:
            dt += stalls.pop(0)[1]
        t += dt
    return trace


def _guard():
    return CaptureBacklogGuard(BLOCK_MS)


def test_without_guard_a_stall_is_permanent_lag():
    """The bug: a 300 ms stall stays as ~300 ms of A/V lag."""
    guard = CaptureBacklogGuard(BLOCK_MS, drop_threshold_ms=float("inf"))
    trace = _simulate(guard, 60, stalls=[(20.0, 0.3)])
    assert min(trace[22:]) > 270.0


def test_stall_backlog_is_dropped():
    guard = _guard()
    trace = _simulate(guard, 60, stalls=[(20.0, 0.3)])
    assert guard.drop_events == 1
    assert 250.0 < guard.dropped_ms < 310.0
    after = trace[20 + int(2 * SYNC_WINDOW_SEC) + 1:]
    assert max(after) < SYNC_DROP_THRESHOLD_MS


def test_small_stalls_add_up_then_drop():
    guard = _guard()
    stalls = [(10.0 + 5 * i, 0.03) for i in range(8)]
    trace = _simulate(guard, 60, stalls=stalls)
    assert guard.drop_events >= 1
    assert max(trace) < SYNC_DROP_THRESHOLD_MS + 2 * QUANTUM * 1000 / SR


@pytest.mark.parametrize("offset_ms", [0.0, 35.0])
def test_steady_operation_never_drops(offset_ms):
    """Node-grouped streams share one clock: the burst sawtooth alone
    must never trigger a drop, whatever the server's latency offset."""
    guard = _guard()
    _simulate(guard, 600, offset_ms=offset_ms)
    assert guard.drop_events == 0


def test_raised_latency_offset_is_not_backlog():
    """A server-side offset change while reads still wait for data moves
    the floor instead of dropping audio."""
    guard = _guard()
    _simulate(guard, 60, offset_changes=[(20.0, 60.0)])
    assert guard.drop_events == 0
    assert guard.floor_ms == pytest.approx(60.0, abs=QUANTUM * 1000 / SR)


def test_drift_without_node_group_stays_bounded():
    """Plain PulseAudio (no node groups): 500 ppm drift is cleared by an
    occasional drop instead of growing without bound."""
    guard = _guard()
    trace = _simulate(guard, 600, playback_ppm=-500.0)
    assert max(trace) < SYNC_DROP_THRESHOLD_MS + 2 * QUANTUM * 1000 / SR
    assert 1 <= guard.drop_events <= 10


def test_slower_capture_never_drops():
    guard = _guard()
    _simulate(guard, 300, capture_ppm=-500.0)
    assert guard.drop_events == 0


def test_unknown_latency_is_ignored():
    guard = _guard()
    for i in range(1000):
        assert guard.observe(-1.0, False, i * 0.01) == 0
    assert guard.floor_ms is None


def test_node_group_is_set_only_while_creating_streams(monkeypatch):
    from stream_denoiser.backends import pulse_simple as ps

    monkeypatch.setenv("PULSE_PROP", "media.role=music")
    seen = {}
    with ps._node_group_env():
        seen["inside"] = os.environ["PULSE_PROP"]
    assert seen["inside"] == f"media.role=music node.group={ps.NODE_GROUP}"
    assert os.environ["PULSE_PROP"] == "media.role=music"

    monkeypatch.delenv("PULSE_PROP")
    with ps._node_group_env():
        assert os.environ["PULSE_PROP"] == f"node.group={ps.NODE_GROUP}"
    assert "PULSE_PROP" not in os.environ


def test_both_streams_are_created_in_the_node_group(monkeypatch):
    from stream_denoiser.backends import pulse_simple as ps
    from test_pulse_simple import FakeLib, _patch

    fake = _patch(monkeypatch, FakeLib(frames=480))
    props = []
    real_new = fake.pa_simple_new

    def spy(*args):
        props.append(os.environ.get("PULSE_PROP"))
        return real_new(*args)

    fake.pa_simple_new = spy
    ps.PulseCapture("src.monitor", 480).close()
    ps.PulsePlayback("sink", 480).close()
    assert props == [f"node.group={ps.NODE_GROUP}"] * 2


def test_invalid_args():
    with pytest.raises(ValueError):
        CaptureBacklogGuard(0)
