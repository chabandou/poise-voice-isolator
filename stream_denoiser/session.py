"""
One audio session: the processor, and the loop that runs it.

The CLI runs its session in its own process (cli); the GUI and the TUI
run theirs in the audio process (audio_host). Both build the processor
and pick the loop here. Routing (VB-Cable as the default playback, the
Linux null sink) stays with the caller, which passes what the loop needs
in ``config``: the audio process can die, and the UI that set the
routing up puts it back.

config keys (JSON values: AudioHost sends them over its pipe as they are):
    backend: "pipewire" or "pulse"; elsewhere "auto" (the native WASAPI
        path, PortAudio when it cannot start), "wasapi" or "portaudio".
    model, onnx_path, atten_lim_db, aad_enabled, aad_threshold_db: the
        processor (see build_processor); all optional.
    input_device, output_device: pulse: source and sink names; pipewire:
        output_device, the sink to play to; Windows: PortAudio IDs, or
        endpoint names on the native path. All optional.
    pipewire, optional: route_default, node_name, description.
    pulse: routed (the caller set up the null sink), monitor_source,
        fallback_sink (the real sink saved at routing setup).
    portaudio, optional: realtime (the loop under MMCSS, default on).
"""
import sys
from typing import Callable, Optional, Tuple

from .constants import (
    DEFAULT_AAD_THRESHOLD_DB,
    DEFAULT_FRAME_SIZE,
    DEFAULT_MODEL,
    DEFAULT_SAMPLE_RATE,
    STATS_PRINT_INTERVAL_SEC,
    WINDOWS_BACKENDS,
)
from .logging_config import get_logger

_logger = get_logger(__name__)

CAPTURE_NOTICE = "Capture device not found. See log for fixes."
PLAYBACK_NOTICE = "Playback device not found. See log for fixes."


class SessionError(RuntimeError):
    """A session cannot run; ``notice`` is the UI's short message."""

    def __init__(self, message: str, notice: str):
        super().__init__(message)
        self.notice = notice


def build_processor(config: dict, engine=None):
    """The session's DenoiserAudioProcessor (48 kHz, the engine's frame).

    ``engine``: the engine to run; None creates a fresh one from config
    (engines hold streaming state), closed again if the processor cannot
    be built.
    """
    from .engines import create_engine
    from .processor import DenoiserAudioProcessor

    kwargs = {}
    if config.get("atten_lim_db") is not None:
        kwargs["atten_lim_db"] = float(config["atten_lim_db"])
    owned = engine is None
    if owned:
        engine_kwargs = dict(kwargs)
        if config.get("onnx_path"):
            engine_kwargs["onnx_path"] = config["onnx_path"]
        engine = create_engine(config.get("model") or DEFAULT_MODEL,
                               **engine_kwargs)
    try:
        return DenoiserAudioProcessor(
            engine,
            target_sr=DEFAULT_SAMPLE_RATE,
            frame_size=engine.required_frame_size or DEFAULT_FRAME_SIZE,
            enable_aad=bool(config.get("aad_enabled", True)),
            aad_threshold_db=float(config.get("aad_threshold_db",
                                              DEFAULT_AAD_THRESHOLD_DB)),
            **kwargs)
    except Exception:
        if owned:
            engine.close()
        raise


def run_session(processor, config: dict, should_stop=None,
                on_stats: Optional[Callable[[dict, float], None]] = None,
                on_started: Optional[Callable] = None,
                stats_interval_sec: float = STATS_PRINT_INTERVAL_SEC,
                wasapi_margin: Optional[int] = None,
                wasapi_pause_gc: bool = False) -> dict:
    """Run the loop config["backend"] names until ``should_stop``.

    Args:
        processor: From build_processor.
        should_stop: threading.Event, callable, or None (until Ctrl+C).
        on_stats: Optional callback(stats, elapsed_sec) every interval.
        on_started: Called with (backend, input, output) once audio runs,
            in that backend's terms: pulse source and sink, pipewire None
            and the sink asked for, the native path's endpoint names,
            PortAudio device IDs.
        wasapi_margin, wasapi_pause_gc: run_wasapi_loop's margin and
            pause_gc. The audio process passes the ones measured for it;
            the CLI keeps the defaults. The other loops always run with
            the collector off: both callers do nothing else.

    Returns:
        Final stats the loop adds to the processor's (pulse: empty_reads).
    """
    backend = config.get("backend")
    started = on_started or (lambda *_: None)
    loop = {"should_stop": should_stop, "on_stats": on_stats,
            "stats_interval_sec": stats_interval_sec}
    if backend == "pipewire":
        from .backends.pipewire_backend import run_pipewire_loop
        options = {key: config[key] for key in
                   ("route_default", "node_name", "description")
                   if config.get(key) is not None}
        sink = config.get("output_device") or None
        started(backend, None, sink)
        run_pipewire_loop(processor, sink, pause_gc=True, **loop, **options)
        return {}
    if backend == "pulse":
        from .backends.pulse_backend import run_pulse_loop
        source, sink = pulse_endpoints(config)
        started(backend, source, sink)
        _final, empty_reads = run_pulse_loop(processor, source, sink,
                                             pause_gc=True, **loop)
        return {"empty_reads": empty_reads}
    if backend in WINDOWS_BACKENDS and not sys.platform.startswith("linux"):
        _run_windows(processor, config, backend, loop, started,
                     wasapi_margin, wasapi_pause_gc)
        return {}
    raise ValueError(f"unknown audio backend {backend!r}")


def pulse_endpoints(config: dict) -> Tuple[str, str]:
    """(source, sink) names for pulse-simple. Fails fast rather than
    capturing the default input, which would record silence while the
    default sink points at the null sink (100% AAD bypass)."""
    from .backends.platform.linux import (
        find_monitor_source_pulsectl, get_default_sink_name, wait_for_source)

    source = config.get("input_device")
    monitor = config.get("monitor_source")
    if source:
        pass
    elif config.get("routed"):
        if not monitor:
            raise SessionError(
                "Audio routing did not provide a monitor source.",
                CAPTURE_NOTICE)
        source = wait_for_source(monitor)
        if source is None:
            raise SessionError(
                f"Null sink monitor '{monitor}' not visible at the "
                "PulseAudio level. Not starting: capturing the default "
                "input instead would record silence. Fixes: check "
                "pavucontrol/PipeWire Pulse backend, or start without "
                "automatic routing (--no-vb-cable).", CAPTURE_NOTICE)
    else:
        # No router: capture the default sink's monitor.
        found = find_monitor_source_pulsectl()
        source = found.name if found else None
        if source is None:
            raise SessionError(
                "No PulseAudio monitor source found. Fixes: check "
                "pavucontrol/PipeWire Pulse backend.", CAPTURE_NOTICE)
    # Explicit selection, else the real sink saved at routing setup, else
    # the current default.
    sink = (config.get("output_device") or config.get("fallback_sink")
            or get_default_sink_name())
    if not sink:
        raise SessionError("No PulseAudio sink found for playback.",
                           PLAYBACK_NOTICE)
    return source, sink


def _run_windows(processor, config: dict, backend: str, loop: dict,
                 started: Callable, wasapi_margin: Optional[int],
                 wasapi_pause_gc: bool) -> None:
    """The native path ("wasapi"), PortAudio ("portaudio"), or the native
    path with PortAudio as the fallback when it cannot start ("auto")."""
    from .backends.wasapi_backend import (
        WasapiStartError, run_wasapi_loop, select_windows_backend)

    chosen, reason = select_windows_backend(backend)
    _logger.info("Windows backend: %s (%s)", chosen, reason)
    if chosen == "wasapi":
        try:
            capture = _device_name(config.get("input_device"), "input")
            render = _device_name(config.get("output_device"), "output")
            run_wasapi_loop(
                processor, capture, render,
                on_started=lambda: started("wasapi", capture, render),
                margin=wasapi_margin, pause_gc=wasapi_pause_gc, **loop)
            return
        except WasapiStartError as e:
            if backend == "wasapi":
                raise
            _logger.warning(
                "Native audio path did not start (%s); using PortAudio", e)
    from .backends.sounddevice_backend import run_portaudio_loop
    run_portaudio_loop(
        processor, config.get("input_device"), config.get("output_device"),
        on_started=lambda i, o: started("portaudio", i, o), pause_gc=True,
        realtime=bool(config.get("realtime", True)), **loop)


def _device_name(device, kind: str) -> Optional[str]:
    """A WASAPI endpoint name for the native path: names pass through,
    PortAudio IDs are looked up; None finds CABLE Output (input) or keeps
    the default (output)."""
    if isinstance(device, str) or (device is None and kind == "output"):
        return device or None
    import sounddevice as sd
    if device is None:
        from .device_utils import find_loopback_device
        device = find_loopback_device(None)
    return sd.query_devices(int(device))["name"]
