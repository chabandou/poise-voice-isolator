"""
Poise Voice Isolator TUI App

Main Textual application with audio processing integration.
"""
import asyncio
import atexit
import logging
import signal
import time
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.message import Message
from textual.widgets import Header, Footer, Rule, Static
from textual.containers import Horizontal, Vertical
from textual.binding import Binding

from .settings import TuiSettings
from .widgets import DeviceList, StatsPanel, StatusLine
from ..audio_host import AudioHost
from ..constants import DEFAULT_MODEL
from ..logging_config import set_tui_mode, get_log_file_path


class AudioEvent(Message):
    """An event from the audio process (see audio_host), posted to the app
    from the host's reader thread."""

    def __init__(self, data: dict) -> None:
        super().__init__()
        self.data = data


class PoiseApp(App):
    """Poise Voice Isolator TUI Application."""
    
    TITLE = "[ POISE ISOLATOR ]"
    CSS_PATH = "styles.tcss"
    ENABLE_COMMAND_PALETTE = False
    
    BINDINGS = [
        Binding("space", "toggle_processing", "Start/Stop", priority=True),
        Binding("m", "cycle_model", "Switch model"),
        Binding("r", "refresh_devices", "Refresh"),
        Binding("minus", "decrease_threshold", "AAD -"),
        Binding("plus", "increase_threshold", "AAD +"),
        Binding("escape", "quit", "Quit", show=False),
        Binding("q", "quit", "Quit"),
    ]
    
    def __init__(self, model: Optional[str] = None, **kwargs):
        """model: an explicit choice (--model) for this session only;
        None uses the last model picked, else the default."""
        super().__init__(**kwargs)
        self.settings = TuiSettings()
        self.model = model or self._saved_model()
        self.is_processing = False
        self.engine = None
        self.onnx_session = None  # Backward-compat alias (unused for rnnoise)
        self.linux_router = None
        self.backend: Optional[str] = None  # "pipewire" or "pulse", per run
        # The audio loop runs in its own process (own GIL and garbage
        # collector), spawned at mount so Start does not wait for imports.
        self.audio = AudioHost(on_event=self._post_audio_event)
        self.start_time = 0.0
        self._audio_error: Optional[str] = None
        self._cleanup_done = False
        self._last_perf_log = 0.0
        self._setup_logging()
        self._setup_cleanup_handlers()
    
    def _setup_logging(self) -> None:
        """File logging on Linux; the status line is never log-driven.

        The status line (upper right) is updated only via explicit,
        UX-friendly ``StatusLine.notify()`` calls. No logging handler is
        attached to it, so raw log records can never leak into line 2.
        """
        import logging
        import sys

        # Enable file logging first (Linux only; no-op elsewhere) so the
        # shared file handler exists before console output is suppressed.
        # Entry points (poise_tui.py / cli.py) already set this up and
        # announced the path; this is a no-op safety net for direct
        # PoiseApp() use.
        if sys.platform.startswith("linux"):
            from ..logging_config import setup_file_logging_from_env
            setup_file_logging_from_env()

        # Enable TUI mode to suppress console logging (keeps file handlers)
        set_tui_mode(True)

        # Get the stream_denoiser logger
        logger = logging.getLogger('stream_denoiser')
        # Keep it file-only: drop console handlers, keep file handlers, and
        # attach the shared file handler in case this logger predates it.
        # Nothing log-driven is attached to the status line widget.
        logger.propagate = False
        logger.handlers = [
            h for h in logger.handlers if isinstance(h, logging.FileHandler)
        ]
        try:
            from ..logging_config import get_file_handler as _get_shared_fh
            _shared_fh = _get_shared_fh()
            if _shared_fh is not None and _shared_fh not in logger.handlers:
                logger.addHandler(_shared_fh)
        except Exception:
            pass
        # Respect --verbose (file handler at DEBUG): don't filter debug out.
        try:
            _levels = [h.level for h in logger.handlers
                       if isinstance(h, logging.FileHandler)]
            logger.setLevel(min(_levels) if _levels else logging.INFO)
        except Exception:
            logger.setLevel(logging.INFO)
    
    def _setup_cleanup_handlers(self) -> None:
        """Set up signal handlers and atexit hook for graceful cleanup."""
        # Register atexit handler for cleanup on normal exit
        atexit.register(self._emergency_cleanup)
        
        # Register signal handlers for abrupt termination
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            try:
                signal.signal(sig, self._signal_handler)
            except (OSError, ValueError):
                # Some signals may not be available on all platforms
                pass
    
    def _signal_handler(self, signum, frame) -> None:
        """Handle termination signals."""
        self._emergency_cleanup()
        # Re-raise signal to allow normal termination
        signal.signal(signum, signal.SIG_DFL)
        signal.raise_signal(signum)
    
    def _emergency_cleanup(self) -> None:
        """
        Emergency cleanup for when the app is terminated abruptly.
        Restores original audio sink and removes the virtual null sink.
        """
        if self._cleanup_done:
            return
        self._cleanup_done = True

        # End the audio process (its session restores the routing it set)
        try:
            self.audio.shutdown(timeout=1.0)
        except Exception:
            pass

        # Restore audio routing
        if self.linux_router:
            try:
                self.linux_router.restore_original_sink()
            except Exception:
                pass
            self.linux_router = None
    
    def get_line_filters(self):
        """Drop Textual's ANSI→truecolor rewrite so `ansi_default`
        backgrounds reach the terminal untouched.

        Every rendered line otherwise passes through ANSIToTruecolor,
        which maps the terminal-default background to the static MONOKAI
        dark color — repainting the dark rectangle `ansi_default` is meant
        to remove. Our palette is truecolor hex throughout (only the base
        background uses an ANSI color), so nothing else changes.
        """
        try:
            from textual.filter import ANSIToTruecolor
        except ImportError:
            return super().get_line_filters()
        return [
            f for f in super().get_line_filters()
            if not isinstance(f, ANSIToTruecolor)
        ]

    def on_resize(self, event) -> None:
        """Toggle narrow layout below 100 columns (stack panels, trim title)."""
        try:
            self.screen.set_class(event.size.width < 100, "-narrow")
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        """Create the UI layout."""
        # yield Header(show_clock=False)
        
        from .font import get_block_text
        from .widgets import AADPanel
        # Top bar: logo left, two-line status block right
        with Horizontal(id="top-bar"):
            with Horizontal(id="title-row"):
                yield Static(get_block_text("POISE"), id="app-title")
                yield Rule(orientation="vertical", id="title-divider")
                yield Static("REAL-TIME\nVOICE\nISOLATOR", id="app-subtitle")
            yield StatusLine(id="status-line")
        
        with Vertical(id="main-container"):
            with Horizontal(id="panels-container"):
                yield DeviceList(preferred=self.settings.output_device,
                                 id="device-panel")
                yield StatsPanel(id="stats-panel")
                threshold = self.settings.aad_threshold_db
                yield AADPanel(
                    threshold_db=-40.0 if threshold is None else threshold,
                    id="aad-panel")
        
        yield Footer()
    
    def on_mount(self) -> None:
        """Called when app is mounted."""
        # Log session header to file (Linux only) for remote diagnosis
        self._log_session_header()

        try:
            self.audio.launch()
        except Exception as e:
            # Start tries again and reports the failure.
            logging.getLogger("stream_denoiser").warning(
                "Could not start the audio process: %s", e)

        # Load ONNX model
        self._load_model()

        # Start stats update timer
        self.set_interval(0.5, self._update_stats)

    @staticmethod
    def _cpu_model() -> str:
        """Best-effort CPU model string (Linux /proc/cpuinfo)."""
        try:
            with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except Exception:
            pass
        return "unknown"

    def _log_session_header(self) -> None:
        """Write a one-time session header to the file log."""
        import logging
        import sys
        if not sys.platform.startswith("linux"):
            return
        logger = logging.getLogger("stream_denoiser")
        path = get_log_file_path()
        try:
            from .. import __version__ as _ver
        except Exception:
            _ver = "unknown"
        try:
            from ..engines import available_models as _avail
            models = ",".join(_avail())
        except Exception:
            models = "unknown"
        logger.info(
            "session start: poise=%s model=%s available=[%s] cpu=%s platform=%s log=%s",
            _ver, self.model, models, self._cpu_model(), sys.platform, path,
        )
    
    def _saved_model(self) -> str:
        """The last model picked, if this machine can still run it."""
        from ..engines import model_unavailable_reason
        saved = self.settings.model
        if saved and model_unavailable_reason(saved) is None:
            return saved
        return DEFAULT_MODEL

    def _load_model(self) -> None:
        """Validate the selected denoising engine is available."""
        status_line = self.query_one("#status-line", StatusLine)
        
        try:
            from ..engines import create_engine
            from ..constants import DEFAULT_FRAME_SIZE
            status_line.notify(f"Loading {self.model} engine...")
            engine = create_engine(self.model)
            frame_size = engine.required_frame_size or DEFAULT_FRAME_SIZE
            engine.close()
            self.engine = True  # marker: engine validated
            self._show_model_on_panel(self.model, frame_size)
            status_line.notify(f"Model '{self.model}' ready.", "success")
            logging.getLogger("stream_denoiser").info(
                "engine ready: model=%s frame_size=%s", self.model, frame_size
            )
        except Exception as e:
            self.engine = None
            # Single-line widget: show only the first line, log the rest.
            first_line = str(e).splitlines()[0] if str(e) else type(e).__name__
            status_line.notify(
                f"Failed to load model '{self.model}': {first_line}", "error"
            )
            _logger = logging.getLogger("stream_denoiser")
            _logger.warning(f"Model load failed: {self.model}: {first_line}")
            _logger.debug(f"Model load failed: {e!r}")

    def _show_model_on_panel(self, model_id: str, frame_size=None) -> None:
        """Pre-fill the performance panel's model block (works idle too)."""
        try:
            from .widgets import StatsPanel
            from ..constants import MODEL_INFO, DEFAULT_SAMPLE_RATE
            panel = self.query_one("#stats-panel", StatsPanel)
            info = MODEL_INFO.get(model_id, {})
            panel.model = info.get("label", model_id)
            panel.model_blurb = info.get("blurb", "")
            if frame_size is not None:
                panel.model_frame = f"{frame_size}-frame @ {DEFAULT_SAMPLE_RATE // 1000}kHz"
        except Exception:
            pass

    def check_action(self, action: str, parameters) -> bool | None:
        """Dim the model switch in the footer while processing."""
        if action == "cycle_model" and self.is_processing:
            return None
        return True

    def action_cycle_model(self) -> None:
        """Open the model picker (blocked while running)."""
        status_line = self.query_one("#status-line", StatusLine)
        if self.is_processing:
            status_line.notify("Stop processing to change model", "warning")
            return
        try:
            from .widgets import ModelPickerScreen
            self.push_screen(
                ModelPickerScreen(current=self.model),
                self._on_model_picked,
            )
        except Exception as e:
            status_line.notify(f"Model switch failed: {e}", "error")

    def _on_model_picked(self, model_id) -> None:
        """Validate and apply the model chosen in the picker."""
        if not model_id:
            return
        if model_id != self.model:
            self.model = model_id
            self._load_model()
            self.query_one("#status-line", StatusLine).notify(
                f"Model: {model_id}")
        # Remember it only if it loads, so the next start does not fail.
        if self.engine is not None:
            self.settings.model = model_id
    
    def action_toggle_processing(self) -> None:
        """Toggle audio processing on/off."""
        if self.is_processing:
            self._stop_processing()
        else:
            self._start_processing()
    
    def action_refresh_devices(self) -> None:
        """Refresh the device list."""
        device_list = self.query_one("#device-panel", DeviceList)
        device_list.refresh_devices()
        
        status_line = self.query_one("#status-line", StatusLine)
        status_line.notify("Devices refreshed")

    def on_device_list_picked(self, event: DeviceList.Picked) -> None:
        self.settings.output_device = event.sink_name
    
    def action_increase_threshold(self) -> None:
        """Increase AAD threshold (less sensitive)."""
        self._adjust_threshold(5.0)
    
    def action_decrease_threshold(self) -> None:
        """Decrease AAD threshold (more sensitive)."""
        self._adjust_threshold(-5.0)
    
    def _adjust_threshold(self, delta: float) -> None:
        """Adjust AAD threshold by delta dB."""
        from .widgets import AADPanel
        aad_panel = self.query_one("#aad-panel", AADPanel)
        
        # Clamp threshold between -80 and 0 dB
        new_threshold = max(-80.0, min(0.0, aad_panel.threshold_db + delta))
        aad_panel.set_threshold(new_threshold)
        self.settings.aad_threshold_db = new_threshold
        
        # Update the running session (the next one starts with the panel's)
        self.audio.set(aad_threshold_db=new_threshold)
        
        status_line = self.query_one("#status-line", StatusLine)
        status_line.notify(f"AAD threshold: {new_threshold:.1f} dB")
    
    def _start_processing(self) -> None:
        """Start audio processing."""
        status_line = self.query_one("#status-line", StatusLine)
        
        if self.engine is None:
            status_line.notify(f"Cannot start: model '{self.model}' not loaded", "error")
            return
        
        stats_panel = self.query_one("#stats-panel", StatsPanel)
        device_list = self.query_one("#device-panel", DeviceList)
        
        # Get selected output device
        output_device = device_list.selected_device
        
        status_line.notify("Starting audio processing...")
        self.screen.add_class("-running")
        
        # Update widgets running state
        self.query_one("#stats-panel", StatsPanel).set_running(True)
        
        # Backend: the PipeWire node when available (fixed delay; it routes
        # itself from the audio process), else pulse-simple through the
        # null sink set up here.
        try:
            from ..backends.pipewire_backend import (
                linux_backend_preference, select_linux_backend)
            self.backend, reason = select_linux_backend(
                linux_backend_preference())
        except Exception as e:
            first_line = str(e).splitlines()[0] if str(e) else type(e).__name__
            logging.getLogger("stream_denoiser").error(
                "Cannot start: %s", e)
            status_line.notify(f"Cannot start: {first_line}", "error")
            self.screen.remove_class("-running")
            stats_panel.set_running(False)
            return
        logging.getLogger("stream_denoiser").info(
            "backend: %s (%s)", self.backend, reason)

        if self.backend == "pipewire":
            self.linux_router = None
            status_line.notify("Routing through the Poise sink.", "success")
        else:
            try:
                from ..backends.platform.linux import LinuxAudioRouter
                self.linux_router = LinuxAudioRouter(auto_switch=True)
                if self.linux_router.get_monitor_source_name():
                    status_line.notify("Null sink routing enabled.", "success")
                else:
                    status_line.notify("Using default audio capture.", "warning")
            except ImportError:
                status_line.notify("Linux router not available.", "warning")
        
        # Start the session in the audio process. Linux input is always
        # 48000 Hz; the audio process resolves pulse-simple's source and
        # sink (waiting for the null sink's monitor to appear).
        from .widgets import AADPanel
        router = self.linux_router
        config = {
            "model": self.model,
            "backend": self.backend,
            "output_device": output_device or None,
            "aad_threshold_db": self.query_one(
                "#aad-panel", AADPanel).threshold_db,
            "routed": router is not None,
            "monitor_source": (router.get_monitor_source_name()
                               if router else None),
            "fallback_sink": router.original_sink_name if router else None,
        }
        self.start_time = time.time()
        self._last_perf_log = 0.0
        self._audio_error = None
        try:
            self.audio.start(config)
        except Exception as e:
            logging.getLogger("stream_denoiser").error(
                "Cannot start: %s", e)
            status_line.notify("Cannot start: audio process unavailable.",
                               "error")
            if self.linux_router:
                self.linux_router.restore_original_sink()
                self.linux_router = None
            self.screen.remove_class("-running")
            stats_panel.set_running(False)
            return

        self.is_processing = True
        self.refresh_bindings()
        status_line.set_running(True)
    
    def _stop_processing(self) -> None:
        """Stop audio processing."""
        status_line = self.query_one("#status-line", StatusLine)
        
        status_line.notify("Stopping audio processing...")
        
        # End the session; returns once the audio process has closed its
        # streams and restored the routing it owns (the PipeWire node's).
        final = self.audio.stop()
        
        # Restore audio routing
        if self.linux_router:
            self.linux_router.restore_original_sink()
            self.linux_router = None
        
        self.is_processing = False
        self.refresh_bindings()
        if final.get("frame_count") is not None:
            logging.getLogger("stream_denoiser").info(
                "run stop: frames=%s avg_ms=%.2f rtf=%.3f "
                "aad_total=%s aad_bypassed=%s bypass_ratio=%.2f "
                "overflows=%s empty_reads=%s elapsed=%.1fs log=%s",
                final.get("frame_count"), final.get("avg_time_ms", 0.0),
                final.get("rtf", 0.0), final.get("aad_total"),
                final.get("aad_bypassed"),
                final.get("aad_bypass_ratio", 0.0),
                0,  # neither backend can report overruns
                final.get("empty_reads", 0),
                time.time() - self.start_time if self.start_time else 0.0,
                get_log_file_path(),
            )
        status_line.set_running(False)
        self.screen.remove_class("-running")
        self.query_one("#stats-panel", StatsPanel).set_running(False)
        status_line.notify("Processing stopped.", "info")
    
    def _notify_status(self, message: str, level: str = "info") -> None:
        """Explicit, UX-friendly status-line update (app thread only)."""
        try:
            self.query_one("#status-line", StatusLine).notify(message, level)
        except Exception:
            pass

    def _post_audio_event(self, data: dict) -> None:
        """AudioHost callback (its reader thread): hand over to the app."""
        self.post_message(AudioEvent(data))

    def on_audio_event(self, message: AudioEvent) -> None:
        """Errors get a short status note (the log has the detail); a
        session that ended on its own (error, crash) resets the UI."""
        kind = message.data.get("event")
        if kind == "error":
            self._audio_error = (message.data.get("notice")
                                 or "Audio error. See log for details.")
            self._notify_status(self._audio_error, "error")
        elif kind == "stopped" and self.is_processing \
                and not self.audio.running:
            self._stop_processing()
            if self._audio_error:
                # Keep the reason up rather than "Processing stopped."
                self._notify_status(self._audio_error, "error")

    def _update_stats(self) -> None:
        """Update stats display (called periodically)."""
        # Sent by the audio process every 0.5 s; empty until the first.
        stats = self.audio.stats
        if not self.is_processing or not stats:
            return
        
        try:
            stats_panel = self.query_one("#stats-panel", StatsPanel)
            running_time = time.time() - self.start_time
            stats_panel.update_stats(stats, running_time)
            # Throttled file snapshot (~every 5s): distinguishes AAD-bypass
            # zeros (silence) from genuine slow-inference RTF on weak CPUs.
            now = time.monotonic()
            if now - getattr(self, "_last_perf_log", 0.0) >= 5.0:
                self._last_perf_log = now
                logging.getLogger("stream_denoiser").info(
                    "perf: frames=%s avg_ms=%.2f rtf=%.3f aad_total=%s "
                    "aad_active=%s aad_bypassed=%s bypass_ratio=%.2f "
                    "overflows=%s empty_reads=%s elapsed=%.1fs "
                    "in_block=%s backlog=%s dropped=%s",
                    stats.get("frame_count"), stats.get("avg_time_ms", 0.0),
                    stats.get("rtf", 0.0), stats.get("aad_total"),
                    stats.get("aad_active"), stats.get("aad_bypassed"),
                    stats.get("aad_bypass_ratio", 0.0),
                    0, 0,  # only known at the end of a run (run stop line)
                    running_time,
                    stats.get("input_block_size"),
                    stats.get("resampler_backlog"),
                    stats.get("resampler_dropped"),
                )
        except Exception:
            pass
    
    def action_quit(self) -> None:
        """Quit the application."""
        if self.is_processing:
            self._stop_processing()
        self.audio.shutdown()
        self.exit()
