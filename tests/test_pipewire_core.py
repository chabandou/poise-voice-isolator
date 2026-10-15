"""Timing of the fixed-delay core (libpoise_pw.so; on Windows the same
core inside poise_wasapi.dll).

Cycles are driven by hand, so no PipeWire server is needed. The "engine"
in most tests is a pure delay of ENGINE samples: its output then equals
the dry fallback exactly, so whatever mix of processed and unprocessed
frames the core plays, the output must be the input delayed by exactly
delay + ENGINE samples.
"""
import sys
import threading
import time

import numpy as np
import pytest

from stream_denoiser.backends.pipewire_node import (
    WAIT_STOPPED, WAIT_TIMEOUT, DelayCore, PipeWireNodeUnavailable,
    load_library)


def _core_library():
    if sys.platform == "win32":
        from stream_denoiser.backends import wasapi_node
        return wasapi_node.load_library()
    return load_library()


try:
    LIB = _core_library()
except (PipeWireNodeUnavailable, RuntimeError) as e:  # not built here
    pytest.skip(f"native core unavailable: {e}", allow_module_level=True)

F = 512
ENGINE = 1536
QUANTUM = 512
MARGIN = 1024
FADE = 64


def _signal(seconds=3.0, seed=0):
    rng = np.random.default_rng(seed)
    return (rng.standard_normal(int(48000 * seconds)) * 0.1).astype(np.float32)


def _delayed(x, n):
    return np.concatenate([np.zeros(n, np.float32), x])


def _run(core, x, sizes, deliver):
    """Drive cycles of the given sizes; after each, hand every available
    frame k to deliver(k, frame) (which may hold it back)."""
    out, pos, i = [], 0, 0
    buf = np.empty(core.frame, np.float32)
    while pos < len(x):
        n = sizes[i % len(sizes)]
        i += 1
        chunk = x[pos:pos + n]
        if len(chunk) < n:
            break
        out.append(core.cycle(chunk, n))
        pos += n
        while True:
            k = core.wait_frame(buf, 0)
            if k < 0:
                break
            deliver(k, buf.copy())
    return np.concatenate(out)


def _engine(x, gain=1.0):
    src = _delayed(x, ENGINE) * gain
    return lambda k: src[k * F:(k + 1) * F]


@pytest.fixture
def core():
    c = DelayCore(F, engine_latency=ENGINE, quantum=QUANTUM, margin=MARGIN,
                  fade=FADE, lib=LIB)
    yield c
    c.close()


def test_delay_is_frame_cycle_fade_margin(core):
    assert core.delay_samples == F + QUANTUM + FADE + MARGIN


def test_output_is_input_delayed_exactly(core):
    x = _signal()
    eng = _engine(x)
    y = _run(core, x, [QUANTUM], lambda k, fr: core.put_frame(k, eng(k)))
    expect = _delayed(x, core.delay_samples + ENGINE)[:len(y)]
    np.testing.assert_allclose(y, expect, atol=1e-6)
    st = core.stats()
    assert st["frames_dry"] == 0 and st["frames_late"] == 0
    assert st["frames_wet"] > 200


def test_late_frames_play_unprocessed_without_moving_time(core):
    """Frames never delivered fall back to dry; time is unchanged."""
    x = _signal()
    eng = _engine(x)

    def deliver(k, fr):
        if k % 9 != 4:
            core.put_frame(k, eng(k))

    y = _run(core, x, [QUANTUM], deliver)
    expect = _delayed(x, core.delay_samples + ENGINE)[:len(y)]
    np.testing.assert_allclose(y, expect, atol=1e-6)
    assert core.stats()["frames_dry"] >= 25


def test_frames_delivered_after_their_deadline_count_as_late(core):
    x = _signal(2.0)
    eng = _engine(x)
    held = []

    def deliver(k, fr):
        if k % 10 == 3:
            held.append(k)  # delivered much later
        else:
            core.put_frame(k, eng(k))
        while held and held[0] < k - 8:
            core.put_frame(held[0], eng(held.pop(0)))

    y = _run(core, x, [QUANTUM], deliver)
    expect = _delayed(x, core.delay_samples + ENGINE)[:len(y)]
    np.testing.assert_allclose(y, expect, atol=1e-6)
    st = core.stats()
    # Each held frame played unprocessed, then arrived: late counts exactly
    # those (the last few may not have arrived by the end).
    assert st["frames_late"] >= 10
    assert st["frames_dry"] - 3 <= st["frames_late"] <= st["frames_dry"]


def test_switches_crossfade_between_processed_and_unprocessed(core):
    """Processed audio at half gain: away from switches the output is
    exactly wet or dry; at a switch it ramps over FADE samples."""
    x = np.full(48000 * 2, 0.5, np.float32)
    eng = _engine(x, gain=0.5)
    missing = {40, 41, 60}

    def deliver(k, fr):
        if k not in missing:
            core.put_frame(k, eng(k))

    y = _run(core, x, [QUANTUM], deliver)
    # Frame k plays at output index delay + k*F (its contents already
    # carry the engine's own delay).
    off = core.delay_samples
    seg = lambda k: y[off + k * F: off + (k + 1) * F]  # noqa: E731
    np.testing.assert_allclose(seg(30), 0.25, atol=1e-6)  # wet
    np.testing.assert_allclose(seg(40)[FADE:], 0.5, atol=1e-6)  # dry
    np.testing.assert_allclose(seg(41), 0.5, atol=1e-6)
    # wet -> dry: last FADE samples of frame 39 rise from 0.25 to 0.5
    tail = seg(39)[-FADE:]
    assert np.all(np.diff(tail) > 0) and 0.25 < tail[0] < tail[-1] < 0.5
    np.testing.assert_allclose(seg(39)[:-FADE], 0.25, atol=1e-6)
    # dry -> wet: first FADE samples of frame 42 fall from 0.5 to 0.25
    head = seg(42)[:FADE]
    assert np.all(np.diff(head) < 0) and 0.5 > head[0] > head[-1] > 0.25
    np.testing.assert_allclose(seg(42)[FADE:], 0.25, atol=1e-6)


def test_worker_stall_skips_ahead_and_recovers(core):
    """A worker gone for ~0.3 s: those frames play dry, the worker jumps
    to the first frame still open, and processing resumes in time."""
    x = _signal()
    eng = _engine(x)
    buf = np.empty(F, np.float32)
    out, pos, cycles = [], 0, 0
    while pos + QUANTUM <= len(x):
        out.append(core.cycle(x[pos:pos + QUANTUM], QUANTUM))
        pos += QUANTUM
        cycles += 1
        stalled = 100 <= cycles < 130  # ~0.32 s with no worker
        if stalled:
            continue
        while True:
            k = core.wait_frame(buf, 0)
            if k < 0:
                break
            core.put_frame(k, eng(k))
    y = np.concatenate(out)
    expect = _delayed(x, core.delay_samples + ENGINE)[:len(y)]
    np.testing.assert_allclose(y, expect, atol=1e-6)
    st = core.stats()
    assert st["frames_skipped"] > 0
    assert st["frames_dry"] >= 28
    # processing resumed: the last second is all wet
    assert st["frames_wet"] > 200


def test_variable_cycle_sizes_keep_exact_delay(core):
    x = _signal()
    eng = _engine(x)
    y = _run(core, x, [128, 256, 512, 64, 480, 333, 512],
             lambda k, fr: core.put_frame(k, eng(k)))
    expect = _delayed(x, core.delay_samples + ENGINE)[:len(y)]
    np.testing.assert_allclose(y, expect, atol=1e-6)
    assert core.stats()["frames_dry"] == 0


def test_cycle_larger_than_designed_raises_delay_once(core):
    x = _signal()
    eng = _engine(x)
    y = _run(core, x, [1024], lambda k, fr: core.put_frame(k, eng(k)))
    st = core.stats()
    d = F + 1024 + FADE + MARGIN
    assert core.delay_samples == d
    assert st["delay_changes"] == 1 and st["quantum_max"] == 1024
    expect = _delayed(x, d + ENGINE)[:len(y)]
    np.testing.assert_allclose(y[-48000:], expect[-48000:], atol=1e-6)


def test_silent_large_cycles_do_not_raise_delay(core):
    """With no app on the Poise sink, PipeWire runs its default (larger)
    cycle; that must not raise the delay for the rest of the run."""
    silent = np.zeros(48000, np.float32)
    _run(core, silent, [1024], lambda k, fr: None)
    st = core.stats()
    assert st["quantum_max"] == 1024 and st["delay_changes"] == 0
    assert core.delay_samples == F + QUANTUM + FADE + MARGIN
    # Sound arrives at the designed cycle: still no change.
    x = _signal(1.0)
    _run(core, x, [QUANTUM], lambda k, fr: None)
    assert core.stats()["delay_changes"] == 0
    # A large cycle carrying sound does raise it.
    _run(core, x, [1024], lambda k, fr: None)
    assert core.stats()["delay_changes"] == 1


def test_unprocessed_silence_is_not_counted(core):
    """Frames the worker never delivered count as dry only if audible."""
    _run(core, np.zeros(48000, np.float32), [QUANTUM], lambda k, fr: None)
    assert core.stats()["frames_dry"] == 0
    _run(core, _signal(1.0), [QUANTUM], lambda k, fr: None)
    assert core.stats()["frames_dry"] > 50


def test_missing_input_is_silence_and_keeps_delay(core):
    """A cycle without input: its slot plays silence, later audio keeps
    its timing."""
    x = _signal(2.0)
    buf = np.empty(F, np.float32)
    out, pos, cycles = [], 0, 0
    hist = []
    while pos + QUANTUM <= len(x):
        cycles += 1
        if cycles == 50:
            out.append(core.cycle(None, QUANTUM))
            hist.append(np.zeros(QUANTUM, np.float32))
        else:
            chunk = x[pos:pos + QUANTUM]
            out.append(core.cycle(chunk, QUANTUM))
            hist.append(chunk)
            pos += QUANTUM
        src = _delayed(np.concatenate(hist), ENGINE)
        while True:
            k = core.wait_frame(buf, 0)
            if k < 0:
                break
            core.put_frame(k, src[k * F:(k + 1) * F])
    y = np.concatenate(out)
    played = np.concatenate(hist)
    expect = _delayed(played, core.delay_samples + ENGINE)[:len(y)]
    np.testing.assert_allclose(y, expect, atol=1e-6)
    assert core.stats()["input_gaps"] == 1


def test_input_burst_resyncs_instead_of_adding_delay(core):
    """Two cycles of input arriving at once must not become extra delay."""
    x = _signal(2.0)
    eng = _engine(x)
    buf = np.empty(F, np.float32)
    out, pos, cycles = [], 0, 0
    while pos + 2 * QUANTUM <= len(x):
        cycles += 1
        n_in = 2 * QUANTUM if cycles == 40 else QUANTUM
        out.append(core.cycle(x[pos:pos + n_in], QUANTUM))
        pos += n_in
        while True:
            k = core.wait_frame(buf, 0)
            if k < 0:
                break
            core.put_frame(k, eng(k))
    y = np.concatenate(out)
    assert core.stats()["resyncs"] == 1
    # After the burst the output position jumped by one cycle: output
    # index i now plays input i + QUANTUM - delay - ENGINE.
    d = core.delay_samples + ENGINE
    tail = y[-24000:]
    start = len(y) - 24000
    expect = x[start + QUANTUM - d: start + QUANTUM - d + 24000]
    np.testing.assert_allclose(tail, expect, atol=1e-6)


def test_wait_blocks_until_a_frame_completes(core):
    buf = np.empty(F, np.float32)
    got = {}

    def worker():
        got["k"] = core.wait_frame(buf, 2000)

    t = threading.Thread(target=worker)
    t.start()
    time.sleep(0.05)
    assert t.is_alive()
    core.cycle(np.ones(F, np.float32), F)
    t.join(1.0)
    assert not t.is_alive() and got["k"] == 0
    np.testing.assert_allclose(buf, 1.0)


def test_wait_times_out_and_stop_wakes_it(core):
    buf = np.empty(F, np.float32)
    assert core.wait_frame(buf, 0) == WAIT_TIMEOUT
    t0 = time.monotonic()
    assert core.wait_frame(buf, 30) == WAIT_TIMEOUT
    assert time.monotonic() - t0 >= 0.02

    got = {}
    t = threading.Thread(target=lambda: got.setdefault(
        "k", core.wait_frame(buf, 5000)))
    t.start()
    time.sleep(0.05)
    core.stop()
    t.join(1.0)
    assert got["k"] == WAIT_STOPPED


def test_rejects_wrong_buffers(core):
    with pytest.raises(ValueError):
        core.wait_frame(np.empty(F, np.float64), 0)
    with pytest.raises(ValueError):
        core.put_frame(0, np.zeros(F - 1, np.float32))
