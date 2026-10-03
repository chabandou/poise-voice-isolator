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
from .widgets.status_line import TUIStatusHandler
from ..constants import DEFAULT_MODEL
from ..logging_config import set_tui_mode, ensure_file_logging, get_log_file_path
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
        self.log_handler = TUIStatusHandler()
        self._cleanup_done = False
        self._last_perf_log = 0.0
        self._setup_logging()
        self._setup_cleanup_handlers()
    
    def _setup_logging(self) -> None:
        """Set up logging to TUI (file logging on Linux is preserved)."""
        import logging
        import sys

        # Enable file logging first (Linux only; no-op elsewhere) so the
        # shared file handler exists before console output is suppressed.
        if sys.platform.startswith("linux"):
            import os as _os
            if _os.environ.get("POISE_DISABLE_FILE_LOG") != "1":
                ensure_file_logging(
                    log_file=_os.environ.get("POISE_LOG_FILE") or None,
                    level=_os.environ.get("POISE_LOG_LEVEL", "INFO"),
                )

        # Enable TUI mode to suppress console logging (keeps file handlers)
        set_tui_mode(True)

        # Get the stream_denoiser logger
        logger = logging.getLogger('stream_denoiser')
        # Remove existing handlers to avoid clutter, but keep file handlers
        file_handlers = [h for h in logger.handlers if isinstance(h, logging.FileHandler)]
        logger.handlers = []
        logger.addHandler(self.log_handler)
        for h in file_handlers:
            logger.addHandler(h)
        # Re-attach the shared file handler in case this logger predates it
        try:
            from ..logging_config import _file_handler as _shared_fh
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
        # Connect log handler to status line
        status_line = self.query_one("#status-line", StatusLine)
        self.log_handler.set_widget(status_line)

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
            
            block_size = self.processor.frame_size

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
                "active" if self.processor.resampler is not None else "off",
                get_log_file_path(),
            )
            
            # Open streams
            with sd.InputStream(device=input_device, samplerate=input_sr, channels=1, 
                              dtype='float32', blocksize=block_size) as inp, \
                 sd.OutputStream(device=output_device, samplerate=DEFAULT_SAMPLE_RATE, 
                                channels=2, dtype='float32', blocksize=block_size) as out:
                
                self.processor.setup_output_resampler(DEFAULT_SAMPLE_RATE)

                # Reused stereo buffer: avoids one alloc per 10ms frame
                stereo_output = np.empty((block_size, 2), dtype=np.float32)
                while not self.stop_event.is_set():
                    # Read audio
                    audio_chunk, overflowed = inp.read(block_size)

                    if overflowed:
                        self._input_overflows = getattr(self, "_input_overflows", 0) + 1
                    
                    if audio_chunk is None or len(audio_chunk) == 0:
                        self._empty_reads = getattr(self, "_empty_reads", 0) + 1
                        continue
                    
                    # Process
                    audio_chunk = audio_chunk.flatten()
                    audio_output = self.processor.process_chunk(audio_chunk)
                    
                    if audio_output is not None:
                        # Duplicate mono to stereo for proper playback on both channels
                        n = min(len(audio_output), block_size)
                        stereo_output[:n, 0] = audio_output[:n]
                        stereo_output[:n, 1] = audio_output[:n]
                        if n < block_size:
                            stereo_output[n:, 0] = 0
                            stereo_output[n:, 1] = 0
                        out.write(stereo_output)
        
        except Exception as e:
            # Log error (will be picked up by main thread)
            import logging
            import traceback
            logging.getLogger('stream_denoiser').error(f"Processing error: {e}")
            logging.getLogger('stream_denoiser').debug(traceback.format_exc())
    
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
                _logging.getLogger("stream_denoiser").info(
                    "perf: frames=%s avg_ms=%.2f rtf=%.3f vad_total=%s "
                    "vad_active=%s vad_bypassed=%s bypass_ratio=%.2f "
                    "overflows=%s empty_reads=%s elapsed=%.1fs",
                    stats.get("frame_count"), stats.get("avg_time_ms", 0.0),
                    stats.get("rtf", 0.0), stats.get("vad_total"),
                    stats.get("vad_active"), stats.get("vad_bypassed"),
                    stats.get("vad_bypass_ratio", 0.0),
                    getattr(self, "_input_overflows", 0),
                    getattr(self, "_empty_reads", 0), running_time,
                )
        except Exception:
            pass
    
    def action_quit(self) -> None:
        """Quit the application."""
        if self.is_processing:
            self._stop_processing()
        self.exit()
