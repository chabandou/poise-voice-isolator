"""
PipeWire node backend (Linux).

Poise runs inside PipeWire's processing graph, the way effects such as
EasyEffects and PipeWire's own filter-chain do: a virtual sink ("Poise
Voice Isolator") that apps play into, whose output reaches the sound card
in the same graph cycle. The native part (libpoise_pw.so) keeps the delay
between the two fixed; node_loop runs inference for it on a Python
thread.

With two separate pulse-simple streams, any moment the Python loop fell
behind left permanent A/V lag (see sync.py). Here a frame that is not
ready in time plays unprocessed for that moment and the delay stays put.
"""
import os
import sys
import time
from typing import Callable, Optional, Tuple

from ..audio_gc import gc_paused
from ..constants import (
    BACKEND_ENV,
    LINUX_BACKENDS,
    PULSE_TARGET_SR,
    PW_FADE_SAMPLES,
    PW_MARGIN_SAMPLES,
    PW_NODE_DESCRIPTION,
    PW_NODE_NAME,
    PW_QUANTUM,
    STATS_PRINT_INTERVAL_SEC,
)
from ..logging_config import get_logger, get_log_file_path
from ._loop_util import margin_samples, ms
from .node_loop import worker_loop
from .pipewire_node import (
    PipeWireNode,
    PipeWireNodeError,
    PipeWireNodeUnavailable,
    load_library,
    pipewire_library_version,
)

_logger = get_logger(__name__)

MARGIN_ENV = "POISE_PW_MARGIN_MS"

# How long the new sink may take to show up at the Pulse level.
SINK_APPEAR_TIMEOUT_SEC = 3.0


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------

def linux_backend_preference(requested: Optional[str] = None) -> str:
    """The requested Linux backend: CLI value, else POISE_BACKEND, else auto."""
    value = (requested or os.environ.get(BACKEND_ENV) or "auto").strip().lower()
    if value not in LINUX_BACKENDS:
        raise ValueError(
            f"Unknown backend {value!r} (choose from {', '.join(LINUX_BACKENDS)})")
    return value


def pipewire_node_status() -> Tuple[bool, str]:
    """Whether the PipeWire node can run here: (ok, detail)."""
    if not sys.platform.startswith("linux"):
        return False, "Linux only"
    try:
        load_library()
    except PipeWireNodeUnavailable as e:
        return False, f"native node unavailable: {e}"
    try:
        from .platform.linux import get_pulse_server_info
        server_name, _ = get_pulse_server_info()
    except Exception:
        server_name = None
    if server_name and "pipewire" not in server_name.lower():
        return False, f"audio server is {server_name}, not PipeWire"
    runtime = os.environ.get("XDG_RUNTIME_DIR", "")
    remote = os.environ.get("PIPEWIRE_REMOTE", "pipewire-0")
    if not server_name and not os.path.exists(os.path.join(runtime, remote)):
        return False, "no PipeWire server found"
    return True, f"PipeWire {pipewire_library_version() or '?'}"


def select_linux_backend(preference: str = "auto",
                         source: Optional[str] = None) -> Tuple[str, str]:
    """Pick "pipewire" or "pulse": (backend, reason).

    An explicit capture source is a pulse-simple concept, so it selects
    pulse. Raises RuntimeError when "pipewire" is requested but unavailable.
    """
    if preference == "pulse":
        return "pulse", "requested"
    if source and preference == "auto":
        return "pulse", "capture source given"
    ok, detail = pipewire_node_status()
    if ok:
        return "pipewire", detail
    if preference == "pipewire":
        raise RuntimeError(f"PipeWire node backend unavailable: {detail}")
    return "pulse", detail


# ---------------------------------------------------------------------------
# Default-sink routing
# ---------------------------------------------------------------------------

def _own_sink_names(node_name: str):
    from ..health import OWN_SINK_NAMES
    return set(OWN_SINK_NAMES) | {node_name}


def pick_output_sink(explicit: Optional[str] = None,
                     node_name: str = PW_NODE_NAME) -> Optional[str]:
    """Sink the processed audio goes to: ``explicit``, else the current
    default unless it is one of ours (or a null sink), else the first real
    sink. None lets PipeWire choose."""
    if explicit:
        return explicit
    try:
        import pulsectl
    except ImportError:
        return None
    own = _own_sink_names(node_name)
    try:
        with pulsectl.Pulse("poise-pw-target") as pulse:
            default = pulse.server_info().default_sink_name
            names = [s.name for s in pulse.sink_list()]
    except Exception as e:
        _logger.debug(f"Could not list sinks: {e}")
        return None
    if default and default not in own and "null" not in default.lower():
        return default
    for name in names:
        if name not in own and "null" not in name.lower():
            return name
    return None


class DefaultSinkRouter:
    """Makes the Poise sink the default and puts the old default back.

    Apps that follow the default move to Poise and back. If Poise dies
    without restoring, its sink disappears with the process and WirePlumber
    falls back to a real sink on its own; but it keeps Poise as the saved
    default and reselects it as soon as the next run's sink appears, before
    the old default can be read. ``fallback`` (the output sink, picked
    before the node existed) is restored then.
    """

    def __init__(self, node_name: str = PW_NODE_NAME,
                 fallback: Optional[str] = None):
        self.node_name = node_name
        self.fallback = fallback
        self.original: Optional[str] = None
        self.switched = False

    def wait_for_sink(self, timeout_sec: float = SINK_APPEAR_TIMEOUT_SEC) -> bool:
        import pulsectl
        deadline = time.monotonic() + timeout_sec
        while True:
            try:
                with pulsectl.Pulse("poise-pw-wait") as pulse:
                    if any(s.name == self.node_name for s in pulse.sink_list()):
                        return True
            except Exception as e:
                _logger.debug(f"Sink wait poll failed: {e}")
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)

    def switch(self) -> None:
        import pulsectl
        own = _own_sink_names(self.node_name)
        with pulsectl.Pulse("poise-pw-route") as pulse:
            current = pulse.server_info().default_sink_name
            if current and current not in own:
                self.original = current
            for sink in pulse.sink_list():
                if sink.name == self.node_name:
                    pulse.sink_default_set(sink)
                    self.switched = True
                    _logger.info("Default sink: %s (was %s)",
                                 self.node_name, current)
                    return
        raise RuntimeError(f"Sink {self.node_name} not found")

    def restore(self) -> None:
        if not self.switched:
            return
        self.switched = False
        target = (self.original or self.fallback
                  or pick_output_sink(None, self.node_name))
        if not target:
            return
        try:
            import pulsectl
            with pulsectl.Pulse("poise-pw-restore") as pulse:
                for sink in pulse.sink_list():
                    if sink.name == target:
                        pulse.sink_default_set(sink)
                        _logger.info("Restored default sink to: %s", target)
                        return
        except Exception as e:
            _logger.warning(f"Could not restore default sink: {e}")


# ---------------------------------------------------------------------------
# Processing loop
# ---------------------------------------------------------------------------

def _log_sync(node: PipeWireNode) -> None:
    st = node.stats()
    _logger.info(
        "sync: latency=%.1fms (delay=%d engine=%d samples) wet=%d dry=%d "
        "late=%d skipped=%d quantum=%d max_quantum=%d delay_changes=%d "
        "resyncs=%d input_gaps=%d trigger_fails=%d",
        ms(node.latency_samples), node.delay_samples,
        node.engine_latency, st["frames_wet"], st["frames_dry"],
        st["frames_late"], st["frames_skipped"], st["quantum"],
        st["quantum_max"], st["delay_changes"], st["resyncs"],
        st["input_gaps"], st["trigger_fails"])


def run_pipewire_loop(processor,
                      sink: Optional[str] = None,
                      should_stop=None,
                      on_stats: Optional[Callable[[dict, float], None]] = None,
                      stats_interval_sec: float = STATS_PRINT_INTERVAL_SEC,
                      route_default: bool = True,
                      node_name: str = PW_NODE_NAME,
                      description: str = PW_NODE_DESCRIPTION,
                      pause_gc: bool = False) -> dict:
    """Run Poise as a PipeWire node until ``should_stop``.

    Args:
        processor: Configured DenoiserAudioProcessor (engine already set).
        sink: Sink to play to; None = the real default sink.
        should_stop: threading.Event, callable, or None (until Ctrl+C).
        on_stats: Optional callback(stats, elapsed_sec) every interval.
        stats_interval_sec: Stats callback cadence.
        route_default: Make the Poise sink the default while running.
        pause_gc: Keep the garbage collector off while frames run (only
            in a process that does nothing else; see audio_gc).

    Returns:
        The processor's final stats.
    """
    # Fixed 48 kHz: PipeWire converts other rates at the node's edges.
    processor.setup_resampler(PULSE_TARGET_SR)
    processor.setup_output_resampler(PULSE_TARGET_SR)
    frame = processor.frame_size
    engine = processor.engine
    engine_latency = int(getattr(engine, "latency_samples", 0) or 0)
    target = pick_output_sink(sink, node_name)
    margin = margin_samples(MARGIN_ENV, PW_MARGIN_SAMPLES)

    node = PipeWireNode(
        frame=frame, engine_latency=engine_latency, quantum=PW_QUANTUM,
        margin=margin, fade=PW_FADE_SAMPLES,
        dry_gain=float(getattr(processor, "output_gain", 1.0)),
        node_name=node_name, description=description, target=target)
    _logger.info(
        "run start: model=%s frame_size=%s target_sr=%s sink=%s node=%s "
        "backend=pipewire-node pipewire=%s latency=%.1fms (delay=%d "
        "engine=%d margin=%d quantum<=%d) log=%s",
        getattr(engine, "name", "?"), frame, PULSE_TARGET_SR, target,
        node_name, pipewire_library_version(), ms(node.latency_samples),
        node.delay_samples, engine_latency, margin, PW_QUANTUM,
        get_log_file_path())

    router = (DefaultSinkRouter(node_name, fallback=target)
              if route_default else None)
    start_time = time.time()
    try:
        if router is not None:
            if not router.wait_for_sink():
                raise PipeWireNodeError(
                    f"Sink {node_name} did not appear within "
                    f"{SINK_APPEAR_TIMEOUT_SEC:.0f}s ({node.status()})")
            router.switch()
        with gc_paused(pause_gc):
            worker_loop(node, processor, should_stop, on_stats,
                        stats_interval_sec, start_time, log_sync=_log_sync,
                        error=PipeWireNodeError)
    finally:
        if router is not None:
            router.restore()
        try:
            _log_sync(node)
            _logger.info("run stop: frames=%s elapsed=%.1fs",
                         processor.get_stats().get("frame_count"),
                         time.time() - start_time)
        except Exception:
            pass
        node.close()
    return processor.get_stats()
