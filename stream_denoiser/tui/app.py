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
import threading

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Rule, Static
from textual.containers import Horizontal, Vertical
from textual.binding import Binding

from .widgets import DeviceList, StatsPanel, StatusLine
from ..constants import DEFAULT_MODEL
from ..logging_config import set_tui_mode, get_log_file_path
from ..backend_detection import USE_SOUNDDEVICE, sd, SOUNDDEVICE_ERROR, SOUNDDEVICE_INSTALL_HINT


class PoiseApp(App):
    """Poise Voice Isolator TUI Application."""
    
    TITLE = "[ POISE ISOLATOR ]"
    CSS_PATH = "styles.tcss"
    ENABLE_COMMAND_PALETTE = False
    
    BINDINGS = [
        Binding("space", "toggle_processing", "Start/Stop", priority=True),
        Binding("m", "cycle_model", "Switch model"),
        Binding("r", "refresh_devices", "Refresh"),
        Binding("minus", "decrease_threshold", "VAD -"),
        Binding("plus", "increase_threshold", "VAD +"),
        Binding("escape", "quit", "Quit", show=False),
        Binding("q", "quit", "Quit"),
    ]
    
    def __init__(self, model: str = DEFAULT_MODEL, **kwargs):
        super().__init__(**kwargs)
        self.model = model
        self.is_processing = False
        self.processor = None
        self.engine = None
        self.onnx_session = None  # Backward-compat alias (unused for rnnoise)
        self.linux_router = None
        self.processing_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.start_time = 0.0
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
        
        # Stop processing thread
        self.stop_event.set()
        if self.processing_thread and self.processing_thread.is_alive():
            self.processing_thread.join(timeout=1.0)
        
        # Restore audio routing
        if self.linux_router:
            try:
                self.linux_router.restore_original_sink()
            except Exception:
                pass
            self.linux_router = None
    
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
        from .widgets import VADPanel
        # Top bar: logo left, two-line status block right
        with Horizontal(id="top-bar"):
            with Horizontal(id="title-row"):
                yield Static(get_block_text("POISE"), id="app-title")
                yield Rule(orientation="vertical", id="title-divider")
                yield Static("REAL-TIME\nVOICE\nISOLATOR", id="app-subtitle")
            yield StatusLine(id="status-line")
        
        with Vertical(id="main-container"):
            with Horizontal(id="panels-container"):
                yield DeviceList(id="device-panel")
                yield StatsPanel(id="stats-panel")
                yield VADPanel(id="vad-panel")
        
        yield Footer()
    
    def on_mount(self) -> None:
        """Called when app is mounted."""
        # Log session header to file (Linux only) for remote diagnosis
        self._log_session_header()

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
        if not model_id or model_id == self.model:
            return
        status_line = self.query_one("#status-line", StatusLine)
        self.model = model_id
        self._load_model()
        status_line.notify(f"Model: {model_id}")
    
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
    
    def action_increase_threshold(self) -> None:
        """Increase VAD threshold (less sensitive)."""
        self._adjust_threshold(5.0)
    
    def action_decrease_threshold(self) -> None:
        """Decrease VAD threshold (more sensitive)."""
        self._adjust_threshold(-5.0)
    
    def _adjust_threshold(self, delta: float) -> None:
        """Adjust VAD threshold by delta dB."""
        from .widgets import VADPanel
        vad_panel = self.query_one("#vad-panel", VADPanel)
        
        # Clamp threshold between -80 and 0 dB
        new_threshold = max(-80.0, min(0.0, vad_panel.threshold_db + delta))
        vad_panel.set_threshold(new_threshold)
        
        # Update processor if running
        if self.processor and self.processor.vad:
            self.processor.vad.set_threshold(new_threshold)
        
        status_line = self.query_one("#status-line", StatusLine)
        status_line.notify(f"VAD threshold: {new_threshold:.1f} dB")
    
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
        
        # Set up Linux audio routing
        try:
            from ..backends.platform.linux import LinuxAudioRouter
            self.linux_router = LinuxAudioRouter(auto_switch=True)
            if self.linux_router.get_monitor_source_name():
                status_line.notify("Null sink routing enabled.", "success")
            else:
                status_line.notify("Using default audio capture.", "warning")
        except ImportError:
            status_line.notify("Linux router not available.", "warning")
        
        # Start processing in background thread
        self.stop_event.clear()
        self.start_time = time.time()
        self._last_perf_log = 0.0
        self._input_overflows = 0
        self._empty_reads = 0
        self.processing_thread = threading.Thread(
            target=self._processing_loop,
            args=(output_device,),
            daemon=True
        )
        self.processing_thread.start()
        
        self.is_processing = True
        status_line.set_running(True)
    
    def _stop_processing(self) -> None:
        """Stop audio processing."""
        status_line = self.query_one("#status-line", StatusLine)
        stats_panel = self.query_one("#stats-panel", StatsPanel)
        
        status_line.notify("Stopping audio processing...")
        
        # Signal thread to stop
        self.stop_event.set()
        
        # Wait for thread to finish
        if self.processing_thread and self.processing_thread.is_alive():
            self.processing_thread.join(timeout=2.0)
        
        # Restore audio routing
        if self.linux_router:
            self.linux_router.restore_original_sink()
            self.linux_router = None
        
        # Mark cleanup as done to prevent double cleanup from atexit/signals
        self._cleanup_done = True
        
        self.is_processing = False
        if self.processor is not None:
            try:
                import logging as _logging
                try:
                    _stats = self.processor.get_stats()
                    _logging.getLogger("stream_denoiser").info(
                        "run stop: frames=%s avg_ms=%.2f rtf=%.3f "
                        "vad_total=%s vad_bypassed=%s bypass_ratio=%.2f "
                        "overflows=%s empty_reads=%s elapsed=%.1fs log=%s",
                        _stats.get("frame_count"), _stats.get("avg_time_ms", 0.0),
                        _stats.get("rtf", 0.0), _stats.get("vad_total"),
                        _stats.get("vad_bypassed"),
                        _stats.get("vad_bypass_ratio", 0.0),
                        getattr(self, "_input_overflows", 0),
                        getattr(self, "_empty_reads", 0),
                        time.time() - self.start_time if self.start_time else 0.0,
                        get_log_file_path(),
                    )
                except Exception:
                    pass
                self.processor.close()
            except Exception:
                pass
            self.processor = None
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

    def _notify_status_from_thread(self, message: str, level: str = "error") -> None:
        """Thread-safe wrapper for background threads (never a log record)."""
        try:
            self.call_from_thread(self._notify_status, message, level)
        except Exception:
            pass

    def _processing_loop(self, output_device: Optional[int]) -> None:
        """Audio processing loop (runs in background thread)."""
        try:
            if not USE_SOUNDDEVICE or sd is None:
                import logging
                msg = "sounddevice is not available"
                if SOUNDDEVICE_ERROR:
                    msg = f"sounddevice/PortAudio unavailable: {SOUNDDEVICE_ERROR}"
                if SOUNDDEVICE_INSTALL_HINT:
                    msg = f"{msg} {SOUNDDEVICE_INSTALL_HINT}"
                logging.getLogger('stream_denoiser').error(msg)
                self._notify_status_from_thread(
                    "Audio backend unavailable. See log for details.", "error"
                )
                return
            import numpy as np
            
            from ..processor import DenoiserAudioProcessor
            from ..engines import create_engine
            from ..constants import DEFAULT_SAMPLE_RATE, DEFAULT_FRAME_SIZE
            
            # Create a fresh engine per run (engines hold streaming state)
            engine = create_engine(self.model)
            # Create processor (frame size follows the engine)
            self.processor = DenoiserAudioProcessor(
                engine,
                target_sr=DEFAULT_SAMPLE_RATE,
                frame_size=engine.required_frame_size or DEFAULT_FRAME_SIZE,
                enable_vad=True,
                vad_threshold_db=-40.0
            )
            
            # Get input device (null sink monitor)
            input_device = None
            if self.linux_router:
                input_device = self.linux_router.get_monitor_device_id()
            
            # Get device info
            if input_device is not None:
                input_info = sd.query_devices(input_device)
                input_sr = int(input_info['default_samplerate'])
            else:
                input_sr = DEFAULT_SAMPLE_RATE
            
            self.processor.setup_resampler(input_sr)
            # Output runs at the device rate; configure its resampler BEFORE
            # opening the stream so out_block_size matches what the pipeline
            # actually produces (mismatched block sizes reintroduce drift).
            self.processor.setup_output_resampler(DEFAULT_SAMPLE_RATE)

            block_size = self.processor.frame_size
            # Read input in rate-scaled blocks so each read resamples to
            # ~one engine frame; a fixed frame_size read at a non-48kHz input
            # rate lets the resampler backlog grow without bound (A/V desync
            # that becomes visible after a few minutes).
            in_block_size = self.processor.input_block_size
            out_block_size = self.processor.output_resample_size

            import logging as _logging
            _run_logger = _logging.getLogger('stream_denoiser')
            try:
                _monitor = self.linux_router.get_monitor_source_name() if self.linux_router else None
            except Exception:
                _monitor = None
            _run_logger.info(
                "run start: model=%s frame_size=%s target_sr=%s input_device=%s "
                "input_sr=%s output_device=%s monitor=%s resampler=%s log=%s",
                self.model, block_size, DEFAULT_SAMPLE_RATE, input_device,
                input_sr, output_device, _monitor,
                f"active(in_block={in_block_size})"
                if self.processor.resampler is not None else "off",
                get_log_file_path(),
            )
            
            # Open streams
            with sd.InputStream(device=input_device, samplerate=input_sr, channels=1,
                              dtype='float32', blocksize=in_block_size) as inp, \
                  sd.OutputStream(device=output_device, samplerate=DEFAULT_SAMPLE_RATE,
                                 channels=2, dtype='float32', blocksize=out_block_size) as out:
                
                # Reused stereo buffer with one sample of headroom: output
                # takes dither around out_block_size (e.g. 470/471).
                stereo_output = np.empty((out_block_size + 1, 2), dtype=np.float32)
                while not self.stop_event.is_set():
                    # Read audio (dithered around the rate-scaled block so
                    # each read resamples to ~one frame on average).
                    audio_chunk, overflowed = inp.read(
                        self.processor.next_input_block_size())

                    if overflowed:
                        self._input_overflows = getattr(self, "_input_overflows", 0) + 1
                    
                    if audio_chunk is None or len(audio_chunk) == 0:
                        self._empty_reads = getattr(self, "_empty_reads", 0) + 1
                        continue
                    
                    # Process
                    audio_chunk = audio_chunk.flatten()
                    audio_output = self.processor.process_chunk(audio_chunk)
                    
                    if audio_output is not None:
                        # Duplicate mono to stereo for proper playback on both channels.
                        # Write exactly what the pipeline produced: padding with
                        # zeros would insert silence and shift A/V sync.
                        n = min(len(audio_output), len(stereo_output))
                        stereo_output[:n, 0] = audio_output[:n]
                        stereo_output[:n, 1] = audio_output[:n]
                        out.write(stereo_output[:n])
        
        except Exception as e:
            # File log holds the full detail; the status line gets only a
            # short UX-friendly note (never the raw record/traceback).
            import logging
            import traceback
            logging.getLogger('stream_denoiser').error(f"Processing error: {e}")
            logging.getLogger('stream_denoiser').debug(traceback.format_exc())
            self._notify_status_from_thread(
                "Audio error. See log for details.", "error"
            )
    
    def _update_stats(self) -> None:
        """Update stats display (called periodically)."""
        if not self.is_processing or self.processor is None:
            return
        
        try:
            stats_panel = self.query_one("#stats-panel", StatsPanel)
            stats = self.processor.get_stats()
            running_time = time.time() - self.start_time
            stats_panel.update_stats(stats, running_time)
            # Throttled file snapshot (~every 5s): distinguishes VAD-bypass
            # zeros (silence) from genuine slow-inference RTF on weak CPUs.
            now = time.monotonic()
            if now - getattr(self, "_last_perf_log", 0.0) >= 5.0:
                self._last_perf_log = now
                import logging as _logging
                _diag = self.processor.get_diagnostics()
                _logging.getLogger("stream_denoiser").info(
                    "perf: frames=%s avg_ms=%.2f rtf=%.3f vad_total=%s "
                    "vad_active=%s vad_bypassed=%s bypass_ratio=%.2f "
                    "overflows=%s empty_reads=%s elapsed=%.1fs "
                    "in_block=%s backlog=%s dropped=%s",
                    stats.get("frame_count"), stats.get("avg_time_ms", 0.0),
                    stats.get("rtf", 0.0), stats.get("vad_total"),
                    stats.get("vad_active"), stats.get("vad_bypassed"),
                    stats.get("vad_bypass_ratio", 0.0),
                    getattr(self, "_input_overflows", 0),
                    getattr(self, "_empty_reads", 0), running_time,
                    _diag.get("input_block_size"),
                    _diag.get("resampler_backlog"),
                    _diag.get("resampler_dropped"),
                )
        except Exception:
            pass
    
    def action_quit(self) -> None:
        """Quit the application."""
        if self.is_processing:
            self._stop_processing()
        self.exit()
