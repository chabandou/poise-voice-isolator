"""
Find staircase steps in a latmeter recording of one endpoint, no Poise.

    python tools/win_steps.py build/latency/<run>

For a run where latmeter played its noise straight into an endpoint and
recorded that endpoint's loopback ("lis"): every second, where the
recording sits relative to the noise played (recorded index minus played
index) and relative to the playing stream's clock. A staircase step is
the recording falling one engine period (512 samples) behind for good,
with a dropout in the audio where it happens.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from win_latency import SR, _best_lag, _load_stream, _times  # noqa: E402


def main():
    out = Path(sys.argv[1])
    sig = np.fromfile(out / "signal.f32", np.float32).astype(np.float64)
    looped = np.concatenate([sig, sig])
    lis, pk = _load_stream(out, "lis")
    t = _times(pk, len(lis))
    t0 = t[0]
    clk = np.loadtxt(out / "rec.clk.csv", delimiter=",", skiprows=1, ndmin=2)
    dev, first = np.unique(clk[:, 1], return_index=True)
    dev_t = clk[first, 2] / 1e7

    rows = []
    prev = None
    n = SR // 10
    for L in range(SR, len(lis) - n, SR):
        seg = lis[L:L + n].astype(np.float64)
        if np.dot(seg, seg) < 1e-6 * n:
            continue
        i, corr = _best_lag(seg, looped, 0)
        if corr < 0.7:   # loopback can be 16-bit and after the volume
            continue
        i %= len(sig)
        # played index: the loop count that keeps the offset near the last one
        guess = L - (prev if prev is not None else 0)
        played = i + len(sig) * round((guess - i) / len(sig))
        off = L - played
        av = np.nan
        if dev[0] <= played <= dev[-1]:
            av = (t[L] - np.interp(played, dev, dev_t)) * 1000.0
        rows.append((t[L] - t0, off, av, corr))
        prev = off
    rows = np.array(rows)
    print(f"{len(rows)} windows over {rows[-1, 0] / 60:.1f} min; "
          f"offset {rows[0, 1]:.0f} -> {rows[-1, 1]:.0f} samples; "
          f"vs clock {rows[0, 2]:.1f} -> {rows[-1, 2]:.1f} ms")

    # Steps: the offset moving for good (median of 10 s before vs after).
    steps = []
    for k in range(10, len(rows) - 10):
        before = np.median(rows[k - 10:k, 1])
        after = np.median(rows[k:k + 10, 1])
        if abs(after - before) >= 100 and (not steps or rows[k, 0] - steps[-1][0] > 15):
            steps.append((rows[k, 0], after - before,
                          np.nanmedian(rows[k:k + 10, 2]) - np.nanmedian(rows[k - 10:k, 2])))
    print(f"steps: {len(steps)}")
    for s, d, dav in steps:
        print(f"  at {s / 60:6.2f} min ({s:7.1f} s): {d:+.0f} samples "
              f"({d / 48:+.1f} ms), vs the stream clock {dav:+.1f} ms")

    # Dropouts: silent runs in the recording (the noise never is silent).
    quiet = np.abs(lis) < 1e-4
    e = np.diff(np.concatenate([[0], quiet.view(np.int8), [0]]))
    a, b = np.where(e == 1)[0], np.where(e == -1)[0]
    keep = ((b - a) >= 64) & (a >= SR)      # not the silence before playback
    gaps = [(t[s] - t0, int(m)) for s, m in zip(a[keep], (b - a)[keep])]
    print(f"dropouts (>= 64 silent samples): {len(gaps)}")
    for s, m in gaps[:40]:
        print(f"  at {s / 60:6.2f} min ({s:7.1f} s): {m} samples ({m / 48:.1f} ms)")


if __name__ == "__main__":
    main()
