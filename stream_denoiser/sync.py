"""
Capture backlog guard (A/V desync in the pulse-simple fallback loop).

The pulse loop is paced by blocking playback writes. Whenever the loop
falls behind (a stall, or many slightly slow iterations while a UI thread
holds the GIL), capture keeps running while playback underruns, so the
lost time stays behind as capture backlog: measured, a 300 ms stall became
300 ms of permanent A/V lag. Clock drift between capture and playback is
prevented separately by the PipeWire node group (see
pulse_simple.NODE_GROUP); on a server without node groups it shows up here
as slowly growing backlog and is cleared the same way.

The backlog is read from the capture stream's reported latency, which
matched the measured end-to-end delay. PipeWire delivers audio in
quantum-sized bursts, so the raw value is a sawtooth (measured 0-45 ms at
rest); only its minimum over a window is meaningful. That minimum is
compared with fixed numbers, never with a learned baseline: learning one
(from the first readings, or from reads that seemed to wait for data)
accepted startup stalls as normal and, while the UI starved the loop,
followed the backlog up to 3.5 s. Only drops that demonstrably fail to
lower the latency (a server whose minimum latency is above the threshold)
raise the reference; those are judged right after the drop, so backlog
that keeps growing cannot pass for latency that will not drain.

Not used: a time-based estimate (elapsed time vs. samples read). It is
measured against the system clock while a node-grouped stream runs on the
sound card's clock (500 ppm apart here), so it creeps and caused
spurious drops every ~30 s.
"""
from collections import deque
from typing import Optional

# Window over which the minimum capture latency is taken (s).
SYNC_WINDOW_SEC = 2.0
# Window-minimum capture latency above which captured audio is discarded
# (ms). Normal operation measured 0-47 ms.
SYNC_DROP_THRESHOLD_MS = 60.0
# Capture latency a drop brings the window minimum back to (ms).
SYNC_TARGET_MS = 20.0
# Consecutive drops that must fail to lower the latency before it is taken
# as this server's minimum rather than backlog.
SYNC_INEFFECTIVE_DROPS = 2
# Largest single drop (ms). Discarding audio that is not buffered makes
# the loop wait for it, so a wrong drop must stay short; real backlog is
# cleared over a few windows instead.
SYNC_MAX_DROP_MS = 500.0
# Reads after a drop whose minimum latency shows whether it worked. Judged
# right away: backlog that keeps growing (a slow loop) must not make a
# drop that did work look like it failed. 8 reads (~85 ms) span the burst
# sawtooth.
SYNC_VERIFY_READS = 8

# Loop iterations longer than this are logged one by one as stalls (ms).
SYNC_STALL_THRESHOLD_MS = 50.0
# Window over which the loop's progress is compared with wall time (s).
SYNC_LOST_WINDOW_SEC = 1.0
# Shortfall per second of wall time not counted as lost (ms): clock drift
# between the system and the sound card (measured 0.5 ms/s) and jitter.
SYNC_LOST_ALLOWANCE_MS_PER_SEC = 2.0


class StallCounter:
    """Measures how far the loop falls behind real time.

    Call ``observe()`` once per iteration. Every SYNC_LOST_WINDOW_SEC the
    audio the loop got through (iterations x one block) is compared with
    the wall time that passed; any shortfall beyond the allowance is added
    to ``lost_ms``. That is the time that becomes capture backlog, whether
    it came from one stall or from many 20-50 ms iterations while a busy UI
    thread held the GIL (which a per-iteration threshold misses), and a
    slow iteration followed by a fast catch-up read nets out. Iterations
    over ``threshold_ms`` are also counted as stalls, and ``observe()``
    returns their length so each can be logged with its timestamp.
    """

    def __init__(self, block_ms: float,
                 threshold_ms: float = SYNC_STALL_THRESHOLD_MS):
        if block_ms <= 0:
            raise ValueError("block_ms must be > 0")
        self.block_ms = float(block_ms)
        self.threshold_ms = float(threshold_ms)
        self.count = 0
        self.max_ms = 0.0
        self.lost_ms = 0.0
        self._last: Optional[float] = None
        self._window_start: Optional[float] = None
        self._window_iters = 0

    def observe(self, now: float) -> float:
        """Record the end of one iteration (monotonic seconds); return its
        length in ms if it was a stall, else 0."""
        last, self._last = self._last, now
        if last is None:
            self._window_start = now
            return 0.0
        self._window_iters += 1
        elapsed = now - self._window_start
        if elapsed >= SYNC_LOST_WINDOW_SEC:
            shortfall = elapsed * 1000.0 - self._window_iters * self.block_ms
            self.lost_ms += max(
                0.0, shortfall - SYNC_LOST_ALLOWANCE_MS_PER_SEC * elapsed)
            self._window_start, self._window_iters = now, 0
        ms = (now - last) * 1000.0
        if ms < self.threshold_ms:
            return 0.0
        self.count += 1
        self.max_ms = max(self.max_ms, ms)
        return ms


class CaptureBacklogGuard:
    """Turns capture-latency observations into blocks to discard.

    Call ``observe()`` after every capture read and discard the returned
    number of blocks (they are already buffered, so reads return at once).
    """

    def __init__(self, block_ms: float,
                 window_sec: float = SYNC_WINDOW_SEC,
                 drop_threshold_ms: float = SYNC_DROP_THRESHOLD_MS,
                 target_ms: float = SYNC_TARGET_MS):
        if block_ms <= 0:
            raise ValueError("block_ms must be > 0")
        self.block_ms = float(block_ms)
        self.window_sec = float(window_sec)
        self.drop_threshold_ms = float(drop_threshold_ms)
        self.target_ms = float(target_ms)
        # Minimum latency that drops proved unable to remove (ms).
        self.offset_ms = 0.0
        self.window_min_ms: Optional[float] = None
        self.dropped_blocks = 0
        self.drop_events = 0
        self.offset_raises = 0
        self._window_start: Optional[float] = None
        self._window_min: Optional[float] = None
        # Latest readings: their minimum is the latency right now (the
        # window minimum lags behind while backlog grows).
        self._recent: deque = deque(maxlen=SYNC_VERIFY_READS)
        # Pending verdict on the last drop: latency before it, ms dropped,
        # reads left, lowest latency seen since.
        self._verify: Optional[list] = None
        self._failed_drops = 0

    def observe(self, latency_ms: float, now: float) -> int:
        """Record one read; return blocks to discard now.

        Args:
            latency_ms: Capture stream latency right after the read
                (negative = unknown, ignored).
            now: Monotonic time in seconds.
        """
        if self._window_start is None:
            self._window_start = now
        if latency_ms >= 0:
            self._recent.append(latency_ms)
            if self._verify is not None:
                self._verify_step(latency_ms)
        if latency_ms >= 0 and (self._window_min is None
                                or latency_ms < self._window_min):
            self._window_min = latency_ms
        if now - self._window_start < self.window_sec:
            return 0
        self._window_start = now
        return self._end_window()

    @property
    def excess_ms(self) -> float:
        """Latest window minimum above the reference (ms)."""
        if self.window_min_ms is None:
            return 0.0
        return max(0.0, self.window_min_ms - self.offset_ms)

    @property
    def dropped_ms(self) -> float:
        return self.dropped_blocks * self.block_ms

    def _end_window(self) -> int:
        wmin, self._window_min = self._window_min, None
        if wmin is None:
            return 0
        self.window_min_ms = wmin
        # The reference only comes back down, toward what was observed.
        self.offset_ms = min(self.offset_ms,
                             max(0.0, wmin - self.target_ms))
        # Sustained over the whole window, so it is backlog, not a burst.
        if wmin - self.offset_ms <= self.drop_threshold_ms:
            return 0
        current = max(wmin, min(self._recent))
        n = int((current - self.offset_ms - self.target_ms) // self.block_ms)
        n = min(n, int(SYNC_MAX_DROP_MS // self.block_ms))
        if n <= 0:
            return 0
        self._verify = [current, n * self.block_ms, SYNC_VERIFY_READS,
                        float("inf")]
        self.dropped_blocks += n
        self.drop_events += 1
        return n

    def _verify_step(self, latency_ms: float) -> None:
        """Did the last drop lower the latency? If drops keep failing,
        that latency is not buffered audio: take it as the minimum."""
        v = self._verify
        v[2] -= 1
        v[3] = min(v[3], latency_ms)
        if v[2] > 0:
            return
        before, dropped, _, after = v
        self._verify = None
        if after <= before - dropped / 2.0:
            self._failed_drops = 0
            return
        self._failed_drops += 1
        if self._failed_drops >= SYNC_INEFFECTIVE_DROPS:
            self._failed_drops = 0
            new = max(0.0, after - self.target_ms)
            if new > self.offset_ms:
                self.offset_ms = new
                self.offset_raises += 1
