"""
Native WASAPI backend (Windows).

Poise captures CABLE Output and plays to the speakers from a native
thread with MMCSS priority (poise_wasapi.dll) that never waits on
Python; this module runs inference for it on a Python thread, the way
the PipeWire node does on Linux.

The PortAudio loop (sounddevice_backend) read, processed and wrote on one
Python thread with ~20 ms of buffering on each side. Every time it fell
behind (the GUI holding the GIL, a slow frame) the speakers ran dry and
the capture overflowed, and the two devices' clocks were left to fight
it out the same way. Here a frame that is not ready in time plays
unprocessed for that moment, the delay stays put, and the clocks are
bridged by slow resampling.
"""
import ctypes
import os
import sys
import time
from contextlib import contextmanager
from typing import Callable, Optional, Tuple

from ..audio_gc import gc_paused
from ..constants import (
    DEFAULT_SAMPLE_RATE,
    STATS_PRINT_INTERVAL_SEC,
    WIN_FADE_SAMPLES,
    WIN_FIFO_SAFETY_SAMPLES,
    WIN_MARGIN_SAMPLES,
    WIN_RENDER_FILL_SAMPLES,
    WINDOWS_BACKENDS,
)
from ..logging_config import get_logger, get_log_file_path
from . import pipewire_backend
from .pipewire_backend import BACKEND_ENV, _worker_loop
from .pipewire_node import PipeWireNodeError
from .wasapi_node import WasapiError, WasapiNode, WasapiUnavailable, load_library

_logger = get_logger(__name__)

MARGIN_ENV = "POISE_WIN_MARGIN_MS"
RATE = DEFAULT_SAMPLE_RATE
# SetThreadPriority level for the inference thread when MMCSS is
# unavailable.
THREAD_PRIORITY_HIGHEST = 2


class WasapiStartError(WasapiError):
    """The native path could not start; the caller may use PortAudio."""


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------

def windows_backend_preference(requested: Optional[str] = None) -> str:
    """The requested Windows backend: CLI value, else POISE_BACKEND, else auto."""
    value = (requested or os.environ.get(BACKEND_ENV) or "auto").strip().lower()
    if value not in WINDOWS_BACKENDS:
        raise ValueError(
            f"Unknown backend {value!r} "
            f"(choose from {', '.join(WINDOWS_BACKENDS)})")
    return value


def wasapi_status() -> Tuple[bool, str]:
    """Whether the native path can run here: (ok, detail)."""
    if sys.platform != "win32":
        return False, "Windows only"
    try:
        load_library()
    except WasapiUnavailable as e:
        return False, f"native audio path unavailable: {e}"
    return True, "native WASAPI"


def select_windows_backend(preference: str = "auto") -> Tuple[str, str]:
    """Pick "wasapi" or "portaudio": (backend, reason).

    Raises RuntimeError when "wasapi" is requested but unavailable.
    """
    if preference == "portaudio":
        return "portaudio", "requested"
    ok, detail = wasapi_status()
    if ok:
        return "wasapi", detail
    if preference == "wasapi":
        raise RuntimeError(f"WASAPI backend unavailable: {detail}")
    return "portaudio", detail


def margin_samples(default: int = WIN_MARGIN_SAMPLES) -> int:
    """Worker margin in samples (POISE_WIN_MARGIN_MS overrides ``default``)."""
    value = os.environ.get(MARGIN_ENV)
    if value:
        try:
            return max(0, int(float(value) * RATE / 1000.0))
        except ValueError:
            _logger.warning("Ignoring %s=%r (not a number)", MARGIN_ENV, value)
    return int(default)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _ms(samples: int) -> float:
    return samples * 1000.0 / RATE


def _log_sync(node: WasapiNode) -> None:
    st, io = node.stats(), node.io_stats()
    _logger.info(
        "sync: latency=%.1fms (io=%d delay=%d engine=%d samples) wet=%d "
        "dry=%d late=%d skipped=%d bridge=%.1f/%.1fms headroom=%.1fms "
        "rate=%+.0fppm starved=%d resyncs=%d capture_glitches=%d "
        "render_underruns=%d render_late=%d max_render_gap=%.1fms",
        _ms(node.latency_samples), node.io_latency_samples,
        node.delay_samples, node.engine_latency, st["frames_wet"],
        st["frames_dry"], st["frames_late"], st["frames_skipped"],
        _ms(io["fifo_level"]), _ms(io["fifo_target"]),
        _ms(io["fifo_headroom"]),
        io["rate_ppb"] / 1000.0, io["fifo_starved"], io["fifo_resyncs"],
        io["capture_glitches"], io["render_underruns"], io["render_late"],
        io["render_gap_max_us"] / 1000.0)


# Device-side events worth a log line each.
_IO_EVENTS = (
    ("render_underruns", "the output buffer ran dry (audible gap)"),
    ("capture_glitches", "capture overflowed (audio lost)"),
    ("fifo_starved", "capture fell short of a cycle; silence inserted"),
    ("fifo_stalls", "capture stalled (50 ms or more without audio)"),
    ("fifo_resyncs", "capture ran far ahead; excess dropped"),
)


def _log_events(node: WasapiNode, seen: dict, gap_max: float,
                busy_max: float) -> dict:
    """The core's events (as on PipeWire) plus the device side's."""
    st = pipewire_backend._log_events(node, seen, gap_max, busy_max)
    io = node.io_stats()
    for key, what in _IO_EVENTS:
        if io[key] > seen.get(key, 0):
            _logger.info("sync: %s (%d)", what, io[key] - seen.get(key, 0))
    return {**st, **io}


# ---------------------------------------------------------------------------
# Processing loop
# ---------------------------------------------------------------------------

@contextmanager
def _raised_thread_priority():
    """Run the inference thread above other programs, so they (a video
    player decoding, a build) delay its frames less.

    HIGHEST alone is not enough: with every core busy, Windows lifts
    starved normal threads to priority 15 for a quantum now and then,
    and those preempt it (measured: DF3 frames up to 46 ms instead of
    ~2 ms). MMCSS "Pro Audio", as the audio thread uses, puts it in the
    realtime range (p99 4 ms under the same load); HIGHEST stays as the
    fallback when MMCSS is unavailable.
    """
    from .platform.windows import MMCSS_TASK, mmcss_thread

    try:
        k32 = ctypes.windll.kernel32
        thread = k32.GetCurrentThread()
        previous = k32.GetThreadPriority(thread)
        k32.SetThreadPriority(thread, THREAD_PRIORITY_HIGHEST)
    except Exception:
        yield
        return
    try:
        with mmcss_thread() as mmcss:
            _logger.info("Inference thread: %s",
                         f"MMCSS {MMCSS_TASK!r}" if mmcss
                         else "HIGHEST (no MMCSS)")
            yield
    finally:
        k32.SetThreadPriority(thread, previous)


def run_wasapi_loop(processor,
                    capture: Optional[str],
                    render: Optional[str] = None,
                    should_stop=None,
                    on_stats: Optional[Callable[[dict, float], None]] = None,
                    stats_interval_sec: float = STATS_PRINT_INTERVAL_SEC,
                    on_started: Optional[Callable[[], None]] = None,
                    margin: Optional[int] = None,
                    pause_gc: bool = False) -> dict:
    """Run Poise on the native WASAPI path until ``should_stop``.

    Args:
        processor: Configured DenoiserAudioProcessor (engine already set).
        capture: Capture device name (CABLE Output); None = default input.
        render: Output device name; None = the default output.
        should_stop: threading.Event, callable, or None (until Ctrl+C).
        on_stats: Optional callback(stats, elapsed_sec) every interval.
        stats_interval_sec: Stats callback cadence.
        on_started: Called once the devices are open and running.
        margin: Time the inference thread gets per frame (samples);
            None = WIN_MARGIN_SAMPLES, sized for a thread in the UI's
            process. POISE_WIN_MARGIN_MS overrides either.
        pause_gc: Keep the garbage collector off while the devices are
            open (only in a process that does nothing else; see audio_gc).

    on_stats also gets the node's counters (frames_dry, fifo_level, ...)
    and its latency in samples.

    Raises:
        WasapiStartError: the devices could not be opened (nothing ran).
        WasapiError: the audio thread failed while running.

    Returns:
        The processor's final stats.
    """
    # Fixed 48 kHz: WASAPI converts at the devices.
    processor.setup_resampler(RATE)
    processor.setup_output_resampler(RATE)
    frame = processor.frame_size
    engine = processor.engine
    engine_latency = int(getattr(engine, "latency_samples", 0) or 0)
    margin = margin_samples(WIN_MARGIN_SAMPLES if margin is None else margin)
    with gc_paused(pause_gc):
        return _run_node(processor, capture, render, should_stop, on_stats,
                         stats_interval_sec, on_started, frame,
                         engine_latency, margin)


def _run_node(processor, capture, render, should_stop, on_stats,
              stats_interval_sec, on_started, frame, engine_latency,
              margin) -> dict:
    engine = processor.engine
    try:
        node = WasapiNode(
            capture=capture, render=render, frame=frame,
            engine_latency=engine_latency, margin=margin,
            fade=WIN_FADE_SAMPLES,
            dry_gain=float(getattr(processor, "output_gain", 1.0)),
            fifo_safety=WIN_FIFO_SAFETY_SAMPLES,
            render_fill=WIN_RENDER_FILL_SAMPLES)
    except (WasapiUnavailable, WasapiError) as e:
        raise WasapiStartError(str(e)) from e
    io = node.io_stats()
    _logger.info(
        "run start: model=%s frame_size=%s capture=%r output=%r "
        "backend=wasapi latency=%.1fms (io=%d delay=%d engine=%d margin=%d; "
        "capture period/buffer=%d/%d output period/buffer/fill=%d/%d/%d "
        "mmcss=%d) log=%s",
        getattr(engine, "name", "?"), frame, capture, render,
        _ms(node.latency_samples), node.io_latency_samples,
        node.delay_samples, engine_latency, margin, io["capture_period"],
        io["capture_buffer"], io["render_period"], io["render_buffer"],
        io["render_fill"], io["mmcss"], get_log_file_path())
    if on_started is not None:
        on_started()
    if on_stats is not None:
        report = on_stats

        def on_stats(stats, elapsed):
            report({**stats, **node.stats(), **node.io_stats(),
                    "latency": node.latency_samples}, elapsed)
    start_time = time.time()
    try:
        with _raised_thread_priority():
            try:
                _worker_loop(node, processor, should_stop, on_stats,
                             stats_interval_sec, start_time,
                             log_sync=_log_sync, log_events=_log_events)
            except PipeWireNodeError as e:   # the shared loop's error type
                raise WasapiError(str(e)) from e
        error = node.error()
        if error:
            raise WasapiError(error)
    finally:
        try:
            _log_sync(node)
            _logger.info("run stop: frames=%s elapsed=%.1fs",
                         processor.get_stats().get("frame_count"),
                         time.time() - start_time)
        except Exception:
            pass
        node.close()
    return processor.get_stats()


def process_with_wasapi(processor, capture: Optional[str],
                        render: Optional[str]) -> None:
    """Blocking CLI entry point: run on the native path until Ctrl+C.

    Raises WasapiStartError if the devices could not be opened.
    """
    from ..device_utils import print_stats, print_final_stats

    _logger.info("Using native WASAPI backend")
    print("\nStarting real-time system audio processing (native WASAPI)...")
    print(f"Input device: {capture or 'default'}")
    print(f"Output device: {render or 'default'}")
    print("Press Ctrl+C to stop...\n")
    try:
        final_stats = run_wasapi_loop(
            processor, capture, render,
            on_stats=lambda stats, elapsed: print_stats(stats, elapsed))
    except KeyboardInterrupt:
        print("\n\nStopping...")
        final_stats = processor.get_stats()
    print_final_stats(final_stats)
