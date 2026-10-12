"""Regression tests for the minutes-scale A/V desync in the pulse-simple
fallback loop (the default Linux backend is now the PipeWire node).

Causes, all measured on PipeWire 1.6:

* Clock drift: the Poise_Capture null sink ran on its own timer (system
  clock) while the real sink runs on the sound card crystal (500 ppm slow
  here). The loop is paced by playback, so capture surplus piled up and
  never drained. Fixed by putting both streams in one PipeWire node group
  (one driver, one clock) -- see pulse_simple.NODE_GROUP.
* Lost time: any time the loop falls behind stays as capture backlog (a
  300 ms stall became 300 ms of permanent lag). Switching to the TUI's
  workspace made the loop ~5% slow while Textual redrew (~50 ms lost per
  switch, 3.5 s in one minute): fixed at the source by a short GIL switch
  interval, and CaptureBacklogGuard discards what is left.
* The previous guard learned its reference from the first readings and
  from reads that seemed to wait for data, so it took a startup stall as
  normal and followed the backlog up to 3.5 s. The reference is now fixed.
"""
import os

import pytest

from stream_denoiser.sync import (
    SYNC_DROP_THRESHOLD_MS,
    SYNC_INEFFECTIVE_DROPS,
    SYNC_MAX_DROP_MS,
    SYNC_TARGET_MS,
    SYNC_WINDOW_SEC,
    CaptureBacklogGuard,
    StallCounter,
)

SR = 48000
BLOCK = 512
BLOCK_MS = BLOCK * 1000.0 / SR
QUANTUM = 1024  # PipeWire delivers capture audio in bursts of this size
QUANTUM_MS = QUANTUM * 1000.0 / SR


def _simulate(guard, seconds, capture_ppm=0.0, playback_ppm=0.0,
              offset_ms=0.0, stalls=(), slow=(), offset_changes=()):
    """Playback-paced loop over a burst-delivering capture stream.

    Capture audio arrives in QUANTUM bursts; a read (including the reads
    that discard blocks) waits if fewer than BLOCK samples are buffered;
    the write takes one block at the card's rate. The guard sees the
    reported latency = offset + buffered audio, where the offset stands
    for latency that is not readable audio.

    stalls: [(t, seconds)] one-off pauses.
    slow: [(t_from, t_to, factor)] iterations take `factor` x as long
        (a UI thread holding the GIL).
    offset_changes: [(t, new_offset_ms)].

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
        # Epsilon: a time computed as k * QUANTUM / rate must count burst k
        # as delivered despite float rounding.
        return int(at * cap_rate / QUANTUM + 1e-9) * QUANTUM

    def read_block():
        nonlocal t, read
        k = int(t * cap_rate / QUANTUM)
        while k * QUANTUM - read < BLOCK:
            k += 1
        t = max(t, k * QUANTUM / cap_rate)
        read += BLOCK

    while t < seconds:
        read_block()
        if offset_changes and t >= offset_changes[0][0]:
            offset_ms = offset_changes.pop(0)[1]
        buffered_ms = (delivered(t) - read) * 1000.0 / SR
        for _ in range(guard.observe(offset_ms + buffered_ms, t)):
            read_block()
        if t >= next_trace:
            trace.append((delivered(t) - read) * 1000.0 / SR)
            next_trace += 1.0
        dt = BLOCK / play_rate
        for t_from, t_to, factor in slow:
            if t_from <= t < t_to:
                dt *= factor
        if stalls and t >= stalls[0][0]:
            dt += stalls.pop(0)[1]
        t += dt
    return trace


def _guard():
    return CaptureBacklogGuard(BLOCK_MS)


# Backlog a window can still hold just before its drop: threshold plus
# the burst sawtooth.
BOUND_MS = SYNC_DROP_THRESHOLD_MS + 2 * QUANTUM_MS


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


def test_startup_stall_is_not_taken_as_normal():
    """Measured: stalls before the first usable window left 180 ms that
    the old guard adopted as its floor and never removed."""
    guard = _guard()
    trace = _simulate(guard, 30, stalls=[(0.3, 0.25)])
    assert guard.drop_events >= 1
    assert max(trace[int(2 * SYNC_WINDOW_SEC) + 1:]) < SYNC_DROP_THRESHOLD_MS


def test_slow_loop_cannot_raise_the_reference():
    """Measured: the TUI starving the loop for a minute (~5% slow) added
    3.5 s, which the old guard followed as its floor. The lag must stay
    bounded throughout and return below the threshold afterwards."""
    guard = _guard()
    trace = _simulate(guard, 100, slow=[(10.0, 70.0, 1.05)])
    # The window right after a drop starts low, so drops come every other
    # window while backlog keeps growing.
    growth_per_window = 0.05 * SYNC_WINDOW_SEC * 1000.0
    assert max(trace) < BOUND_MS + 2 * growth_per_window
    assert max(trace[75:]) < SYNC_DROP_THRESHOLD_MS
    assert guard.offset_ms == 0.0


@pytest.mark.parametrize("offset_ms", [0.0, 35.0])
def test_steady_operation_never_drops(offset_ms):
    """Node-grouped streams share one clock: the burst sawtooth and the
    measured server offsets (0 and ~35 ms) must never trigger a drop."""
    guard = _guard()
    _simulate(guard, 600, offset_ms=offset_ms)
    assert guard.drop_events == 0


def test_unremovable_latency_is_accepted_after_failed_drops():
    """A server whose minimum latency sits above the threshold: drops
    cannot lower it, so after a couple of tries it is taken as that
    server's minimum instead of draining the buffer dry forever."""
    guard = _guard()
    _simulate(guard, 120, offset_changes=[(20.0, 120.0)])
    assert guard.drop_events <= SYNC_INEFFECTIVE_DROPS + 1
    assert guard.offset_ms == pytest.approx(120.0 - SYNC_TARGET_MS,
                                            abs=QUANTUM_MS)
    drops = guard.drop_events
    _simulate(guard, 60, offset_ms=120.0)
    assert guard.drop_events == drops


def test_huge_unremovable_latency_costs_only_short_waits():
    """Dropping audio that is not buffered makes the loop wait for it.
    Each drop is capped, and failed ones stop after a couple of tries."""
    guard = _guard()
    _simulate(guard, 60, offset_ms=3500.0)
    assert guard.drop_events <= SYNC_INEFFECTIVE_DROPS
    assert guard.dropped_ms <= SYNC_INEFFECTIVE_DROPS * SYNC_MAX_DROP_MS
    assert guard.offset_ms > 3000.0


def test_seconds_of_backlog_are_cleared_in_capped_steps():
    guard = _guard()
    trace = _simulate(guard, 60, stalls=[(10.0, 3.0)])
    assert guard.offset_ms == 0.0
    assert guard.dropped_ms > 2900.0
    assert guard.drop_events >= 3000.0 / SYNC_MAX_DROP_MS
    assert max(trace[35:]) < BOUND_MS


def test_backlog_on_top_of_accepted_minimum_is_still_dropped():
    guard = _guard()
    trace = _simulate(guard, 120, offset_ms=120.0, stalls=[(60.0, 0.3)])
    assert guard.offset_ms > 0
    assert max(trace[60 + int(3 * SYNC_WINDOW_SEC):]) < SYNC_DROP_THRESHOLD_MS


def test_drift_without_node_group_stays_bounded():
    """Plain PulseAudio (no node groups): 500 ppm drift is cleared by an
    occasional drop instead of growing without bound."""
    guard = _guard()
    trace = _simulate(guard, 600, playback_ppm=-500.0)
    assert max(trace) < BOUND_MS
    assert 1 <= guard.drop_events <= 10
    assert guard.offset_ms == 0.0


def test_slower_capture_never_drops():
    guard = _guard()
    _simulate(guard, 300, capture_ppm=-500.0)
    assert guard.drop_events == 0


def test_unknown_latency_is_ignored():
    guard = _guard()
    for i in range(1000):
        assert guard.observe(-1.0, i * 0.01) == 0
    assert guard.window_min_ms is None
    assert guard.excess_ms == 0.0


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


def _feed(counter, gaps_ms, t=0.0):
    out = []
    for gap_ms in gaps_ms:
        t += gap_ms / 1000.0
        out.append(counter.observe(t))
    return t, out


def test_lost_time_ignores_jitter_and_clock_drift():
    """99.9% of iterations measured under 13.2 ms, and the card ran 500 ppm
    slow against the system clock: neither is lost time."""
    stalls = StallCounter(BLOCK_MS)
    jitter = [BLOCK_MS + d for d in (-1.5, 1.5, -0.9, 2.5, -2.5, 0.9)] * 500
    _, out = _feed(stalls, jitter)
    drift = [BLOCK_MS * 1.0005] * 6000
    _feed(stalls, drift)
    assert stalls.lost_ms == 0.0
    assert stalls.count == 0 and not any(out)


def test_slow_iteration_followed_by_catch_up_nets_out():
    """A slow read followed by a fast one (audio already buffered) costs
    nothing; counting only the slow one overstated the loss by 60%."""
    stalls = StallCounter(BLOCK_MS)
    _feed(stalls, [24.0, BLOCK_MS * 2 - 24.0 + 0.0001] * 1000)
    assert stalls.lost_ms < 5.0


def test_lost_time_counts_ui_slowdowns_below_stall_threshold():
    """A busy UI made many 20-50 ms iterations that a >50 ms stall
    threshold missed entirely; their excess is the backlog they leave."""
    stalls = StallCounter(BLOCK_MS)
    _feed(stalls, [BLOCK_MS] * 200 + [30.0] * 60 + [BLOCK_MS] * 200)
    assert stalls.count == 0
    expected = 60 * (30.0 - BLOCK_MS)
    assert stalls.lost_ms == pytest.approx(expected, rel=0.05)


def test_stalls_are_reported_one_by_one():
    stalls = StallCounter(BLOCK_MS)
    _, reported = _feed(stalls, [BLOCK_MS] * 100 + [240.0] + [BLOCK_MS] * 200
                        + [550.0] + [BLOCK_MS] * 200)
    assert [round(r) for r in reported if r] == [240, 550]
    assert stalls.count == 2
    assert stalls.max_ms == pytest.approx(550.0)
    assert stalls.lost_ms == pytest.approx(240 + 550 - 2 * BLOCK_MS,
                                           abs=10.0)


def test_invalid_args():
    with pytest.raises(ValueError):
        CaptureBacklogGuard(0)
    with pytest.raises(ValueError):
        StallCounter(0)


def test_audio_loop_runs_with_fast_gil_handoff(monkeypatch):
    """A busy UI thread must not hold up the audio loop for the default
    5 ms per GIL reacquire (measured: ~50 ms of lag per switch to the
    TUI's workspace). The loop shortens the switch interval while it runs
    and restores it afterwards."""
    import sys

    import numpy as np

    from stream_denoiser.backends import pulse_backend as pb
    from stream_denoiser.backends.platform import linux

    seen = []

    class FakeStream:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            seen.append(sys.getswitchinterval())
            return np.zeros((512, 1), dtype=np.float32), False

        def write(self, data):
            pass

        def latency_ms(self):
            return 0.0

    class FakeProcessor:
        frame_size = 512

        def setup_resampler(self, sr):
            pass

        def setup_output_resampler(self, sr):
            pass

        def process_chunk(self, chunk):
            return chunk

        def get_stats(self):
            return {"frame_count": 0}

    monkeypatch.setattr(pb, "PulseCapture", FakeStream)
    monkeypatch.setattr(pb, "PulsePlayback", FakeStream)
    monkeypatch.setattr(linux, "get_pulse_server_info", lambda: ("test", "0"))
    before = sys.getswitchinterval()
    pb.run_pulse_loop(FakeProcessor(), "src.monitor", "sink",
                      should_stop=lambda: len(seen) >= 5)
    assert seen and all(v == pb.AUDIO_SWITCH_INTERVAL_SEC for v in seen)
    assert sys.getswitchinterval() == before
