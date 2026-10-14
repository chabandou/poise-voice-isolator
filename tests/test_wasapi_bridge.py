"""The Windows clock bridge (poise_wasapi.dll): CABLE Output to speakers.

VB-Cable runs on its own clock and the speakers on the sound card's, so
the native path resamples between them, keeping just enough input in its
FIFO. Driven by hand here: capture packets and render cycles of 10 ms
each, the capture clock off by a chosen ppm, packets arriving late, in
pairs, or after a stall. Whatever the clocks and the packet timing do,
the audio must stay continuous and clean and the wall-clock delay from
capture to output must stay put (or come back once capture calms down).
"""
import sys

import numpy as np
import pytest

if sys.platform != "win32":
    pytest.skip("Windows only", allow_module_level=True)

from stream_denoiser.backends.wasapi_node import (  # noqa: E402
    ClockBridge, WasapiUnavailable, load_library)

try:
    load_library()
except WasapiUnavailable as e:  # not built here
    pytest.skip(f"poise_wasapi.dll unavailable: {e}", allow_module_level=True)

SR = 48000
PERIOD = 480                       # 10 ms, both devices
SAFETY = 240                       # WIN_FIFO_SAFETY_SAMPLES
START = PERIOD + 33 + SAFETY       # fill target to start from, as the DLL


def _noise(seconds, seed=0):
    """Band-limited noise (< 8 kHz): untouched by the resampler's filter."""
    rng = np.random.default_rng(seed)
    x = rng.standard_normal(int(SR * seconds) + 8192)
    spec = np.fft.rfft(x)
    spec[int(len(spec) * 8000 / (SR / 2)):] = 0
    return (np.fft.irfft(spec, len(x)) * 0.2).astype(np.float32)


def _simulate(x, seconds, ppm=0.0, jitter_ms=0.0, stall=None, pairs=None,
              rough=None, checkpoints=(), seed=1):
    """Run the bridge for `seconds` of render time.

    Capture packets of PERIOD samples come from a clock `ppm` faster than
    the render clock (the reference), each up to `jitter_ms` late. During
    `stall` (start, end), or a list of them, no packet arrives; they all
    come at the end.
    During `pairs` (start, end) packets arrive two at a time. During
    `rough` (start, end, ms) they are up to that many ms late.
    Returns (output, bridge, {checkpoint: stats}).
    """
    rng = np.random.default_rng(seed)
    stalls = [] if stall is None else (
        [stall] if np.isscalar(stall[0]) else list(stall))
    cap_dt = PERIOD / (SR * (1.0 + ppm * 1e-6))
    ren_dt = PERIOD / SR
    events = []
    k = 0
    while k * cap_dt < seconds + 1.0:
        t = (k + 1) * cap_dt
        late = rng.uniform(0.0, jitter_ms / 1000.0)
        if rough is not None and rough[0] <= t < rough[1]:
            late = rng.uniform(0.0, rough[2] / 1000.0)
        if pairs is not None and pairs[0] <= t < pairs[1] and k % 2 == 0:
            late = cap_dt
        t += late
        for s0, s1 in stalls:
            if s0 <= t < s1:
                t = s1 + k * 1e-9
        events.append((t, 0, k))
        k += 1
    n_ren = int(seconds / ren_dt)
    events += [(0.0037 + i * ren_dt, 1, i) for i in range(n_ren)]
    end = 0.0037 + (n_ren - 1) * ren_dt
    events = sorted(e for e in events if e[0] <= end)
    b = ClockBridge(START, SAFETY)
    out = np.empty(n_ren * PERIOD, np.float32)
    snaps, todo = {}, sorted(checkpoints)
    for t, kind, i in events:
        while todo and t >= todo[0]:
            snaps[todo.pop(0)] = b.stats()
        if kind == 0:
            b.push(x[i * PERIOD:(i + 1) * PERIOD], t)
        else:
            b.update(t)
            out[i * PERIOD:(i + 1) * PERIOD] = b.read(PERIOD)
    return out, b, snaps


def _source_pos(out, x, o, guess, search=6000, n=4800):
    """Input position whose audio plays at output sample o."""
    seg = out[o:o + n].astype(np.float64)
    lo = max(0, int(guess) - search)
    ref = x[lo:lo + n + 2 * search].astype(np.float64)
    c = np.correlate(ref, seg, mode="valid")
    return lo + int(np.argmax(c))


def _delay_ms(out, x, o, ppm=0.0):
    """Wall-clock delay of output sample o: it plays at o / SR on the
    render clock; its audio was captured at s / (SR (1 + ppm)) on the
    cable's."""
    s = _source_pos(out, x, o, o * (1 + ppm * 1e-6) - START)
    return (o / SR - s / (SR * (1.0 + ppm * 1e-6))) * 1000.0


def test_equal_clocks_fixed_delay_and_clean_audio():
    x = _noise(31)
    out, b, _ = _simulate(x, 30)
    st = b.stats()
    assert st["starved"] == 0 and st["resyncs"] == 0
    assert abs(st["rate_ppb"]) < 100_000         # < 100 ppm, settling
    d0, d1 = _delay_ms(out, x, 5 * SR), _delay_ms(out, x, 29 * SR)
    assert d1 == pytest.approx(d0, abs=0.1)
    # The input has nothing above 8 kHz: any click, gap or aliasing would
    # put energy there.
    seg = out[2 * SR:30 * SR].astype(np.float64)
    a = 2 * np.pi * np.arange(len(seg)) / len(seg)   # Blackman-Harris
    seg *= 0.35875 - 0.48829 * np.cos(a) + 0.14128 * np.cos(2 * a)         - 0.01168 * np.cos(3 * a)
    spec = np.abs(np.fft.rfft(seg)) ** 2
    f = np.fft.rfftfreq(len(seg), 1 / SR)
    leak = spec[f > 9000].sum() / spec[f < 8000].sum()
    assert 10 * np.log10(leak) < -70


@pytest.mark.parametrize("ppm", [500, -500, 2000, -2000])
def test_clock_drift_is_resampled_away(ppm):
    """Capture faster or slower than the speakers: the rate correction
    finds the difference, the FIFO never runs dry or over, and the
    wall-clock delay stays where it was."""
    x = _noise(182, seed=abs(ppm))
    out, b, _ = _simulate(x, 180, ppm=ppm, jitter_ms=2.0)
    st = b.stats()
    assert st["starved"] == 0
    assert st["resyncs"] == 0
    assert st["rate_ppb"] / 1000.0 == pytest.approx(ppm, rel=0.05, abs=10)
    # Packets 2 ms late at worst fit the safety: no headroom bought.
    assert st["headroom"] >= 0
    assert st["target"] < START + SR / 1000.0
    # Locking on moves the delay by a few milliseconds at most; once
    # locked it does not move at all.
    delays = [_delay_ms(out, x, t * SR, ppm) for t in (20, 60, 120, 179)]
    assert max(delays) - min(delays) < 3.0
    assert max(delays[1:]) - min(delays[1:]) < 0.5


def test_late_packets_never_starve_the_output():
    x = _noise(61, seed=3)
    _, b, _ = _simulate(x, 60, ppm=300, jitter_ms=4.0, seed=7)
    assert b.stats()["starved"] == 0


def test_packets_in_pairs_raise_the_level_instead_of_starving():
    """Capture delivering 20 ms at a time (seen from VB-Cable in a VM):
    a level sized for 10 ms packets runs short at first; the shortfall
    raises the level and then nothing runs short any more."""
    x = _noise(91, seed=5)
    out, b, snaps = _simulate(x, 90, ppm=100, jitter_ms=1.0,
                              pairs=(10.0, 1e9), checkpoints=(20.0,))
    st = b.stats()
    assert st["starved"] == snaps[20.0]["starved"]       # none after 20 s
    assert st["starved"] <= 3
    assert st["headroom"] >= 0
    # The headroom needed follows the packet/read phase, which cycles
    # slowly with the clock difference: the delay may wander a little.
    delays = [_delay_ms(out, x, t * SR, 100) for t in (40, 60, 89)]
    assert max(delays) - min(delays) < 5.0


def test_rough_capture_costs_latency_for_a_while_then_gives_it_back():
    """A minute of capture packets up to 15 ms late: the bridge buys the
    headroom it needs (a few short gaps at most, then none), and once
    capture is regular again it returns to its usual delay."""
    x = _noise(241, seed=6)
    out, b, snaps = _simulate(x, 240, ppm=-200, jitter_ms=1.0,
                              rough=(30.0, 90.0, 15.0),
                              checkpoints=(50.0, 90.0))
    st = b.stats()
    assert snaps[90.0]["starved"] == snaps[50.0]["starved"]   # adapted
    assert st["starved"] == snaps[90.0]["starved"]            # calm again
    assert st["resyncs"] == 0
    calm, rough, after = (_delay_ms(out, x, t * SR, -200)
                          for t in (25, 85, 235))
    assert rough > calm + 5.0          # it did buy headroom
    assert after == pytest.approx(calm, abs=3.0)


def test_capture_stall_costs_silence_not_delay():
    """Capture delivers nothing for 150 ms, then all of it at once: the
    output plays silence meanwhile, then drops the stale audio at once.
    No headroom covers a stall, so it buys none: the delay is what it was
    before right away (the stall crosses a rate-control window, which
    used to raise the target twice: +20 ms for most of a minute)."""
    x = _noise(61, seed=4)
    out, b, _ = _simulate(x, 60, stall=(10.0, 10.15))
    st = b.stats()
    assert st["starved"] >= 1
    assert st["stalls"] == 1
    assert st["resyncs"] == 1
    assert st["dropped"] > 0.1 * SR
    before = _delay_ms(out, x, 8 * SR)
    assert _delay_ms(out, x, 12 * SR) == pytest.approx(before, abs=2.0)
    assert _delay_ms(out, x, 58 * SR) == pytest.approx(before, abs=2.0)
    assert st["target"] == START
    # The silence is where the stall was.
    gap = out[int(10.06 * SR):int(10.12 * SR)]
    assert np.max(np.abs(gap)) < 1e-6


def test_repeated_stalls_do_not_ratchet_the_delay():
    """A 120 ms stall every 15 s (a driver hiccuping): each one is a gap,
    none of them adds delay, however often they come."""
    x = _noise(122, seed=8)
    stalls = [(t, t + 0.12) for t in np.arange(10.0, 115.0, 15.0)]
    out, b, _ = _simulate(x, 120, ppm=150, jitter_ms=1.0, stall=stalls)
    st = b.stats()
    assert st["stalls"] == len(stalls)
    before = _delay_ms(out, x, 8 * SR, 150)
    after = [_delay_ms(out, x, int((t + 3.0) * SR), 150) for t, _ in stalls[1:]]
    assert max(after) < before + 3.0


def test_resampling_is_clean_while_correcting():
    """A 1 kHz tone through a 1000 ppm correction: distortion and noise
    stay far below audibility."""
    t = np.arange(SR * 62) / SR
    x = (0.5 * np.sin(2 * np.pi * 1000.0 * t)).astype(np.float32)
    out, b, _ = _simulate(x, 60, ppm=1000)
    seg = out[50 * SR:50 * SR + 16384].astype(np.float64)
    a = 2 * np.pi * np.arange(len(seg)) / len(seg)   # Blackman-Harris
    w = 0.35875 - 0.48829 * np.cos(a) + 0.14128 * np.cos(2 * a) \
        - 0.01168 * np.cos(3 * a)
    spec = np.abs(np.fft.rfft(seg * w)) ** 2
    peak = int(np.argmax(spec))
    tone = spec[max(0, peak - 8):peak + 9].sum()
    rest = spec.sum() - tone
    assert 10 * np.log10(rest / tone) < -70
