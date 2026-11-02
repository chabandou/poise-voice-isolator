"""
Native Core Audio backend (macOS).

Poise taps every app's audio with a global Core Audio process tap and
plays the isolated speech back through the same output device
(native/poise_coreaudio/, libpoise_coreaudio.dylib): a native IOProc runs
poise_core's fixed-delay exchange and never waits on Python, and
node_loop runs inference for it on a Python thread — the same shape as
the WASAPI path on Windows.

The tap cannot be asked to convert: the aggregate's stream format is what
the IOProc gets (plan C2), so the streams are created at 48 kHz Float32
and a device the HAL refuses that for is refused here, by name, instead
of running the engine at the wrong rate. A missing System Audio
Recording grant is not an error but a silence (plan C2b), so the tap's
own capture health is reported alongside the counters.
"""
import platform
import sys
import threading
import time
from typing import Callable, Dict, Optional, Tuple

from ..audio_gc import gc_paused
from ..constants import (
    DEFAULT_SAMPLE_RATE,
    MAC_FADE_SAMPLES,
    MAC_MARGIN_SAMPLES,
    MAC_QUANTUM,
    POISE_MAC_MARGIN_MS,
    STATS_PRINT_INTERVAL_SEC,
)
from ..logging_config import get_logger, get_log_file_path
from ._loop_util import margin_samples, ms, stop_requested
from .coreaudio_node import (
    NODE_RATE,
    CoreAudioError,
    CoreAudioNode,
    CoreAudioUnavailable,
    load_library,
)
from .node_loop import log_core_events, worker_loop

_logger = get_logger(__name__)

# The values live in constants.py with the rest of the platform groups
# (PW_*/WIN_*); these are aliases so nothing reads a second source. T5 sizes
# MAC_MARGIN_SAMPLES from its soak, and that edit must be the one that counts.
MARGIN_ENV = POISE_MAC_MARGIN_MS
# The rate the node's streams carry (plan C2): 48 kHz, or the device is refused.
RATE = NODE_RATE
QUANTUM = MAC_QUANTUM
MARGIN_SAMPLES = MAC_MARGIN_SAMPLES
FADE_SAMPLES = MAC_FADE_SAMPLES
# First macOS with Core Audio process taps.
OS_FLOOR = (14, 2)


class CoreAudioStartError(CoreAudioError):
    """The node could not be created; nothing ran."""


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------

def _os_version() -> Optional[Tuple[int, int]]:
    """(major, minor) of the running macOS, or None if unreadable."""
    try:
        parts = platform.mac_ver()[0].split(".")
        return int(parts[0]), int(parts[1] if len(parts) > 1 else 0)
    except (TypeError, ValueError, IndexError):
        return None


def coreaudio_status() -> Tuple[bool, str]:
    """Whether the native path can run here: (ok, detail)."""
    if sys.platform != "darwin":
        return False, "macOS only"
    version = _os_version()
    if version is None:
        return False, "cannot read the macOS version"
    if version < OS_FLOOR:
        return False, (f"macOS {version[0]}.{version[1]} is older than "
                       f"{OS_FLOOR[0]}.{OS_FLOOR[1]}, the first with the Core "
                       f"Audio process tap this path needs")
    machine = platform.machine()
    if machine != "arm64":
        return False, f"Apple Silicon only (this Mac reports {machine!r})"
    try:
        load_library()
    except CoreAudioUnavailable as e:
        return False, f"native audio path unavailable: {e}"
    return True, "native Core Audio tap"


def select_coreaudio_backend(preference: str = "auto") -> Tuple[str, str]:
    """Pick "coreaudio": (backend, reason).

    Raises RuntimeError when it cannot run: macOS has nothing to fall back
    to, and the PortAudio loop would record the default input instead of
    the system's audio. T7 owns the user-facing wording of the version
    floor; this is the check behind it.
    """
    value = (preference or "auto").strip().lower()
    if value not in ("auto", "coreaudio"):
        raise RuntimeError(
            f"unknown macOS backend {value!r} (choose from auto, coreaudio)")
    ok, detail = coreaudio_status()
    if ok:
        return "coreaudio", detail
    raise RuntimeError(f"the Core Audio backend cannot run here: {detail}")


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

# What the tap is delivering (plan C2b): "no-audio" is not capturing at
# all, "silent" is capturing zeros — a denied or stale grant, or a Mac
# that is quiet.
def capture_state(stats: Dict[str, int]) -> str:
    """Which of "no-audio", "silent" and "signal" the tap is delivering."""
    if stats["input_frames"] <= 0:
        return "no-audio"
    if stats["saw_signal"]:
        return "signal"
    return "silent"


_CAPTURE_NOTES = {
    "no-audio": "the tap has delivered nothing: the aggregate is not being "
                "read at all (plan C2b)",
    "silent": "the tap is delivering silence: a Mac that is quiet, or the "
              "System Audio Recording grant is denied or stale — Settings > "
              "Privacy & Security > Screen & System Audio Recording",
    "signal": "the tap is delivering sound",
}


def tap_alive(node, stats: Dict[str, int]) -> int:
    """1 while the tap is alive.

    The native counter is C4's (T5's property listeners fill it; today it
    reads 1), so a node that has stopped itself — the 250 ms watchdog,
    plan C1 — is not alive whatever it says.
    """
    return int(bool(stats["tap_alive"]) and node.error() is None)


def _log_sync(node) -> None:
    st, ca = node.stats(), node.node_stats()
    rate = node.rate
    _logger.info(
        "sync: latency=%.1fms (io=%d delay=%d engine=%d samples; rate=%d) "
        "wet=%d dry=%d late=%d skipped=%d delay_changes=%d resyncs=%d "
        "input_gaps=%d quantum_max=%d dropped=%d overloads=%d "
        "restarts=%d tap_alive=%d capture=%s silent=%d saw_signal=%d "
        "drift=%+d samples time_delta=%.1f..%.1fms",
        ms(node.latency_samples, rate), node.io_latency_samples,
        node.delay_samples, node.engine_latency, rate,
        st["frames_wet"], st["frames_dry"], st["frames_late"],
        st["frames_skipped"], st["delay_changes"], st["resyncs"],
        st["input_gaps"], st["quantum_max"], ca["dropped"], ca["overloads"],
        ca["restarts"], tap_alive(node, ca), capture_state(ca),
        ca["quiet_frames"], ca["saw_signal"], ca["drift_samples"],
        ms(ca["time_delta_min"], rate), ms(ca["time_delta_max"], rate))


# Node-side events worth a log line each.
_NODE_EVENTS = (
    ("overloads", "an output buffer could not be filled (audible gap)"),
    ("dropped", "captured frames never reached the core"),
)


def _log_events(node, seen: dict, gap_max: float, busy_max: float) -> dict:
    """The core's events (as on PipeWire) plus the device's, and a line
    when what the tap delivers changes (C2b)."""
    st = log_core_events(node, seen, gap_max, busy_max)
    ca = node.node_stats()
    previous = seen.get("node") or {}
    for key, what in _NODE_EVENTS:
        if ca[key] > previous.get(key, 0):
            _logger.info("sync: %s (%d)", what, ca[key] - previous.get(key, 0))
    state = capture_state(ca)
    if state != seen.get("capture"):
        _logger.info("sync: capture is %s (%s)", state,
                     _CAPTURE_NOTES[state])
    # The core's counters stay at the top level (log_core_events reads them
    # back); the node's go in beside them, because they carry the same
    # names for the counters the core owns.
    return {**st, "node": ca, "capture": state}


# ---------------------------------------------------------------------------
# Creating the node
# ---------------------------------------------------------------------------

# How long an abandoned creation may hold the caller's exit path (C1).
STARTUP_JOIN_SEC = 0.5


class _NodeCreation:
    """Creates the node off the calling thread.

    ``poise_ca_new`` waits for a person while the System Audio Recording
    prompt is up (180 s in the native node) and nothing inside it can be
    interrupted, so created on the main thread Ctrl-C would not be handled
    until it returned. Here the wait is interrupted within 50 ms, and a
    node that appears after the caller gave up is destroyed at once —
    destroying the tap is what unmutes the Mac (plan C1).
    """

    def __init__(self, make: Callable[[], CoreAudioNode]):
        self._make = make
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._node: Optional[CoreAudioNode] = None
        self._error: Optional[BaseException] = None
        self._abandoned = False

    def start(self) -> "_NodeCreation":
        self._thread = threading.Thread(target=self._run,
                                        name="poise-coreaudio-create",
                                        daemon=True)
        self._thread.start()
        return self

    def _run(self) -> None:
        try:
            node = self._make()
        except BaseException as e:  # noqa: BLE001 - re-raised by wait()
            with self._lock:
                self._error = e
            self._done.set()
            return
        try:
            with self._lock:
                abandoned = self._abandoned
                if not abandoned:
                    self._node = node
            if abandoned:  # the caller is gone: nobody else will close it
                node.close()
        finally:
            self._done.set()

    def wait(self, gone: Callable[[], bool]) -> Optional[CoreAudioNode]:
        """The node, or None when ``gone()`` came true while creating.

        Raises whatever the creation raised (a refused device arrives as
        CoreAudioStartError from the caller).
        """
        while not self._done.is_set():
            self._done.wait(0.05)
            if gone():
                self.abandon()
        with self._lock:
            node, self._node = self._node, None
            error = self._error
        if error is not None:
            raise error
        return node

    def abandon(self) -> None:
        """Destroy the node as soon as it exists (the caller is going away).

        Best effort by design: it runs on exit routes, where a raise would
        hide the reason the caller gave up.

        The join matters for C1. poise_ca_new() creates the tap (muting the
        Mac) *before* it registers the node with the library's atexit net, so a
        Ctrl-C in that window would otherwise leave a muting tap behind with
        nothing able to destroy it: the creation thread is a daemon and the
        caller's handle is still None. Waiting briefly lets the common case
        (a few seconds of startup) close the node before the process exits;
        when it does not finish, the warning says what the Mac is doing.
        """
        with self._lock:
            self._abandoned = True
            node, self._node = self._node, None
        if node is not None:
            try:
                node.close()
            except Exception:
                _logger.debug("closing an abandoned node failed",
                              exc_info=True)
            return
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(STARTUP_JOIN_SEC)
            if thread.is_alive():
                _logger.warning(
                    "the Core Audio tap may still be muting this Mac until "
                    "this process exits: node creation had not finished "
                    "%.1f s after it was abandoned", STARTUP_JOIN_SEC)


# ---------------------------------------------------------------------------
# Processing loop
# ---------------------------------------------------------------------------

def run_coreaudio_loop(processor, output: Optional[str] = None,
                       should_stop=None,
                       on_stats: Optional[Callable[[dict, float], None]] = None,
                       stats_interval_sec: float = STATS_PRINT_INTERVAL_SEC,
                       on_started: Optional[Callable[[], None]] = None,
                       margin: Optional[int] = None,
                       pause_gc: bool = False) -> dict:
    """Run Poise on the native Core Audio path until ``should_stop``.

    Args:
        processor: Configured DenoiserAudioProcessor (engine already set).
        output: Output device name or UID substring; None = the default
            output. Bluetooth and AirPlay are accepted as far as the HAL
            accepts them.
        should_stop: threading.Event, callable, or None (until Ctrl+C).
        on_stats: Optional callback(stats, elapsed_sec) every interval.
        stats_interval_sec: Stats callback cadence.
        on_started: Called once the tap and the aggregate are running.
        margin: Time the inference thread gets per frame (samples);
            None = MARGIN_SAMPLES. POISE_MAC_MARGIN_MS overrides either.
        pause_gc: Keep the garbage collector off while the tap is open
            (only in a process that does nothing else; see audio_gc).

    on_stats also gets the node's counters (frames_dry, overloads, ...)
    and its latency in samples.

    Raises:
        CoreAudioStartError: the node could not be created (nothing ran) —
            including a device that cannot give 48 kHz, with its real rate
            and its name in the message (plan C2).
        CoreAudioError: the node failed while running (the watchdog
            reports a device that stopped calling back there, plan C1).

    Returns:
        The processor's final stats.
    """
    # Fixed 48 kHz: the HAL resamples the device, the engine never runs at
    # another rate (plan C2).
    processor.setup_resampler(RATE)
    processor.setup_output_resampler(RATE)
    frame = processor.frame_size
    engine = processor.engine
    engine_latency = int(getattr(engine, "latency_samples", 0) or 0)
    margin = margin_samples(
        MARGIN_ENV, MARGIN_SAMPLES if margin is None else margin, RATE)
    with gc_paused(pause_gc):
        return _run_node(processor, output, should_stop, on_stats,
                         stats_interval_sec, on_started, frame,
                         engine_latency, margin)


def _run_node(processor, output, should_stop, on_stats, stats_interval_sec,
              on_started, frame, engine_latency, margin) -> dict:
    engine = processor.engine

    def make_node() -> CoreAudioNode:
        return CoreAudioNode(
            output=output, frame=frame, engine_latency=engine_latency,
            quantum=QUANTUM, margin=margin, fade=FADE_SAMPLES,
            dry_gain=float(getattr(processor, "output_gain", 1.0)),
            rate=RATE, tap_mute=True)

    creation = _NodeCreation(make_node).start()
    node = None
    started_at = 0.0              # 0.0: the loop never got to run
    try:
        try:
            node = creation.wait(lambda: stop_requested(should_stop))
        except (CoreAudioUnavailable, CoreAudioError) as e:
            raise CoreAudioStartError(str(e)) from e
        if node is None:
            _logger.info("run stop: stopped before the node was ready")
            return processor.get_stats()
        _logger.info(
            "run start: model=%s frame_size=%s output=%r backend=coreaudio "
            "latency=%.1fms (io=%d delay=%d engine=%d margin=%d quantum=%d "
            "fade=%d samples; rate=%d) log=%s",
            getattr(engine, "name", "?"), frame, output,
            ms(node.latency_samples, node.rate), node.io_latency_samples,
            node.delay_samples, engine_latency, margin, QUANTUM,
            FADE_SAMPLES, node.rate, get_log_file_path())
        if on_started is not None:
            on_started()
        if on_stats is not None:
            report = on_stats

            def on_stats(stats, elapsed):
                report({**stats, **node.stats(), **node.node_stats(),
                        "latency": node.latency_samples}, elapsed)
        started_at = time.time()
        worker_loop(node, processor, should_stop, on_stats,
                    stats_interval_sec, started_at, log_sync=_log_sync,
                    log_events=_log_events, error=CoreAudioError)
        error = node.error()
        if error:
            raise CoreAudioError(error)
    finally:
        try:
            if node is not None:
                _log_sync(node)
                _logger.info(
                    "run stop: frames=%s elapsed=%.1fs",
                    processor.get_stats().get("frame_count"),
                    0.0 if not started_at else time.time() - started_at)
        except Exception:
            pass
        creation.abandon()
        if node is not None:
            node.close()
    return processor.get_stats()
