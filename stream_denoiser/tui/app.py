"""
Poise Voice Isolator TUI App

Main Textual application with audio processing integration.
"""
import asyncio
import atexit
import signal
import time
from pathlib import Path
from typing import Optional
import threading

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static
from textual.containers import Horizontal, Vertical
from textual.binding import Binding

from .widgets import DeviceList, StatsPanel, StatusLine
from .widgets.status_line import TUIStatusHandler
from ..logging_config import set_tui_mode


class PoiseApp(App):
    """Poise Voice Isolator TUI Application."""
    
    TITLE = "[ POISE ISOLATOR ]"
    CSS_PATH = "styles.tcss"
    ENABLE_COMMAND_PALETTE = False
    
    BINDINGS = [
        Binding("space", "toggle_processing", "Start/Stop", priority=True),
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh_devices", "Refresh"),
        Binding("escape", "quit", "Quit", show=False),
        Binding("minus", "decrease_threshold", "VAD -"),
        Binding("plus", "increase_threshold", "VAD +"),
    ]
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.is_processing = False
        self.processor = None
        self.onnx_session = None
        self.linux_router = None
        self.processing_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.start_time = 0.0
        self.log_handler = TUIStatusHandler()
        self._cleanup_done = False
        self._setup_logging()
        self._setup_cleanup_handlers()
    
    def _setup_logging(self) -> None:
        """Set up logging to TUI."""
        import logging
        
        # Enable TUI mode to suppress console logging
        set_tui_mode(True)
        
        # Get the stream_denoiser logger
        logger = logging.getLogger('stream_denoiser')
        # Remove existing handlers to avoid clutter
        logger.handlers = []
        logger.addHandler(self.log_handler)
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
    
    def compose(self) -> ComposeResult:
        """Create the UI layout."""
        # yield Header(show_clock=False)
        
        from .font import get_outlined_block_text
        from .widgets import VADPanel
        # Use block text with outline/shadow effect
        yield Static(get_outlined_block_text("POISE"), id="app-title")
        
        with Vertical(id="main-container"):
            with Horizontal(id="panels-container"):
                yield DeviceList(id="device-panel")
                yield StatsPanel(id="stats-panel")
                yield VADPanel(id="vad-panel")
            yield StatusLine(id="status-line")
        
        yield Footer()
    
    def on_mount(self) -> None:
        """Called when app is mounted."""
        # Connect log handler to status line
        status_line = self.query_one("#status-line", StatusLine)
        self.log_handler.set_widget(status_line)
        
        # Load ONNX model
        self._load_model()
        
        # Start stats update timer
        self.set_interval(0.5, self._update_stats)
    
    def _load_model(self) -> None:
        """Load the ONNX model."""
        status_line = self.query_one("#status-line", StatusLine)
        
        try:
            from ..processor import load_onnx_model
            status_line.notify("Loading ONNX model...")
            self.onnx_session = load_onnx_model()
            status_line.notify("Model loaded successfully. Ready.", "success")
        except Exception as e:
            status_line.notify(f"Failed to load model: {e}", "error")
    
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
        
        if self.onnx_session is None:
            status_line.notify("Cannot start: Model not loaded", "error")
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
                status_line.notify("Null sink routing enabled. Processing...", "success")
            else:
                status_line.notify("Using default audio capture. Processing...", "warning")
        except ImportError:
            status_line.notify("Linux router not available. Processing...", "warning")
        
        # Start processing in background thread
        self.stop_event.clear()
        self.start_time = time.time()
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
        self.processor = None
        status_line.set_running(False)
        self.screen.remove_class("-running")
        self.query_one("#stats-panel", StatsPanel).set_running(False)
        status_line.notify("Processing stopped.", "info")
    
    def _processing_loop(self, output_device: Optional[int]) -> None:
        """Audio processing loop (runs in background thread)."""
        try:
            import sounddevice as sd
            import numpy as np
            
            from ..processor import DenoiserAudioProcessor
            from ..constants import DEFAULT_SAMPLE_RATE, DEFAULT_FRAME_SIZE
            
            # Create processor
            self.processor = DenoiserAudioProcessor(
                self.onnx_session,
                target_sr=DEFAULT_SAMPLE_RATE,
                frame_size=DEFAULT_FRAME_SIZE,
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
            
            # Open streams
            with sd.InputStream(device=input_device, samplerate=input_sr, channels=1, 
                              dtype='float32', blocksize=block_size) as inp, \
                 sd.OutputStream(device=output_device, samplerate=DEFAULT_SAMPLE_RATE, 
                               channels=2, dtype='float32', blocksize=block_size) as out:
                
                self.processor.setup_output_resampler(DEFAULT_SAMPLE_RATE)
                
                while not self.stop_event.is_set():
                    # Read audio
                    audio_chunk, overflowed = inp.read(block_size)
                    
                    if audio_chunk is None or len(audio_chunk) == 0:
                        continue
                    
                    # Process
                    audio_chunk = audio_chunk.flatten()
                    audio_output = self.processor.process_chunk(audio_chunk)
                    
                    if audio_output is not None:
                        # Duplicate mono to stereo for proper playback on both channels
                        stereo_output = np.column_stack((audio_output, audio_output)).astype(np.float32)
                        out.write(stereo_output)
        
        except Exception as e:
            # Log error (will be picked up by main thread)
            import logging
            logging.getLogger('stream_denoiser').error(f"Processing error: {e}")
    
    def _update_stats(self) -> None:
        """Update stats display (called periodically)."""
        if not self.is_processing or self.processor is None:
            return
        
        try:
            stats_panel = self.query_one("#stats-panel", StatsPanel)
            stats = self.processor.get_stats()
            running_time = time.time() - self.start_time
            stats_panel.update_stats(stats, running_time)
        except Exception:
            pass
    
    def action_quit(self) -> None:
        """Quit the application."""
        if self.is_processing:
            self._stop_processing()
        self.exit()
