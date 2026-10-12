"""
Capture backlog guard (A/V desync after loop stalls).

The pulse loop is paced by blocking playback writes. When the loop stalls
(GC, GIL contention, a slow inference frame), capture keeps running while
playback underruns, so the stall's full length stays behind as capture
backlog: measured, a 300 ms stall became 300 ms of permanent A/V lag.
Clock drift between capture and playback is prevented separately by the
PipeWire node group (see pulse_simple.NODE_GROUP); on a server without
node groups it shows up here as slowly growing backlog and is cleared the
same way.

The backlog is read from the capture stream's latency. PipeWire delivers
audio in quantum-sized bursts, so the raw value is a sawtooth (measured
0-45 ms at rest); only its minimum over a window is meaningful. The
floor (the minimum with an empty buffer) is learned per run: the reported
value includes a server-dependent offset (0 or ~35 ms on the same
machine). A window in which reads actually waited for data had an empty
buffer, so its minimum *is* the floor, even if higher than before.

Not used: a time-based estimate (elapsed time vs. samples read). It is
measured against the system clock while a node-grouped stream runs on the
sound card's clock (500 ppm apart here), so it creeps and caused
spurious drops every ~30 s.
"""
from typing import Optional

# Window over which the minimum capture latency is taken (s).
SYNC_WINDOW_SEC = 2.0
# Backlog above the floor at which captured blocks are discarded (ms).
# Normal operation stays near 0; only a stall (or drift without a node
# group) gets here.
SYNC_DROP_THRESHOLD_MS = 40.0
# A read that waited at least this fraction of a block found the capture
# buffer empty.
SYNC_BLOCKED_READ_FRACTION = 0.75
# Waiting reads needed in one window to (re)calibrate the floor; more than
# one so a single preempted read cannot move it.
SYNC_MIN_BLOCKED_READS = 3


class CaptureBacklogGuard:
    """Turns capture-latency observations into blocks to discard.

    Call ``observe()`` after every capture read and discard the returned
    number of blocks (they are already buffered, so reads return at once).
    """

    def __init__(self, block_ms: float,
                 window_sec: float = SYNC_WINDOW_SEC,
                 drop_threshold_ms: float = SYNC_DROP_THRESHOLD_MS):
        if block_ms <= 0:
            raise ValueError("block_ms must be > 0")
        self.block_ms = float(block_ms)
        self.window_sec = float(window_sec)
        self.drop_threshold_ms = float(drop_threshold_ms)
        self.floor_ms: Optional[float] = None
        self.excess_ms = 0.0
        self.dropped_blocks = 0
        self.drop_events = 0
        self._window_start: Optional[float] = None
        self._window_min: Optional[float] = None
        self._window_blocked = 0

    def observe(self, latency_ms: float, read_blocked: bool,
                now: float) -> int:
        """Record one read; return blocks to discard now.

        Args:
            latency_ms: Capture stream latency right after the read
                (negative = unknown, ignored).
            read_blocked: True if the read waited for data.
            now: Monotonic time in seconds.
        """
        if self._window_start is None:
            self._window_start = now
        if latency_ms >= 0 and (self._window_min is None
                                or latency_ms < self._window_min):
            self._window_min = latency_ms
        if read_blocked:
            self._window_blocked += 1
        if now - self._window_start < self.window_sec:
            return 0
        self._window_start = now
        return self._end_window()

    def _end_window(self) -> int:
        wmin, blocked = self._window_min, self._window_blocked
        self._window_min, self._window_blocked = None, 0
        if wmin is None:
            return 0
        if (self.floor_ms is None or wmin < self.floor_ms
                or blocked >= SYNC_MIN_BLOCKED_READS):
            self.floor_ms = wmin
        self.excess_ms = wmin - self.floor_ms
        if self.excess_ms <= self.drop_threshold_ms:
            return 0
        # Keep one block of margin so the drop never runs the buffer dry.
        n = int(self.excess_ms // self.block_ms) - 1
        if n <= 0:
            return 0
        self.excess_ms -= n * self.block_ms
        self.dropped_blocks += n
        self.drop_events += 1
        return n

    @property
    def dropped_ms(self) -> float:
        return self.dropped_blocks * self.block_ms
