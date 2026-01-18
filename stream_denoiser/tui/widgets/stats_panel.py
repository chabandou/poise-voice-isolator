"""
Stats Panel Widget

Displays real-time processing statistics.
"""
from textual.widgets import Static, Rule
from textual.containers import Vertical, Horizontal
from textual.reactive import reactive


class StatsPanel(Static):
    """Widget to display real-time processing statistics."""
    
    DEFAULT_CSS = """
    StatsPanel {
        border: heavy $border;
    }
    """
    
    # Reactive properties for auto-update
    status: reactive[str] = reactive("Stopped")
    rtf: reactive[float] = reactive(0.0)
    avg_ms: reactive[float] = reactive(0.0)
    frames: reactive[int] = reactive(0)
    vad_bypass: reactive[float] = reactive(0.0)
    running_time: reactive[float] = reactive(0.0)
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.border_title = "\[ STATS ]"
    
    
    def compose(self):
        with Vertical(id="stats-container"):
            # RTF
            with Horizontal(classes="stat-row"):
                yield Static("Real Time Factor (RTF)", classes="stat-label")
                yield Static("0.000", classes="stat-value", id="val-rtf")
            
            yield Rule(line_style="dashed")
            
            # Processing Time
            with Horizontal(classes="stat-row"):
                yield Static("Processing Time", classes="stat-label")
                yield Static("0.00 ms", classes="stat-value", id="val-avg")
            
            yield Rule(line_style="dashed")
            
            # Frames
            with Horizontal(classes="stat-row"):
                yield Static("Frames", classes="stat-label")
                yield Static("0", classes="stat-value", id="val-frames")
            
            yield Rule(line_style="dashed")
                
            # VAD Bypass
            with Horizontal(classes="stat-row"):
                yield Static("Voice Activity Detection Bypass", classes="stat-label")
                yield Static("0%", classes="stat-value", id="val-vad")
            
            yield Rule(line_style="dashed")
                
            # Duration
            with Horizontal(classes="stat-row"):
                yield Static("Running Time", classes="stat-label")
                yield Static("0s", classes="stat-value", id="val-time")
    
    def on_mount(self) -> None:
        self._update_display()
    
    def watch_status(self, value: str) -> None:
        self._update_display()
    
    def watch_rtf(self, value: float) -> None:
        self._update_display()
    
    def set_running(self, running: bool) -> None:
        """Set the running status."""
        self.status = "Running" if running else "Stopped"
        # We don't need to manually trigger update here if we rely on CSS for colors,
        # but we might want to update values if they are reset.
        self._update_display()
    
    def update_stats(self, stats: dict, running_time: float = 0.0) -> None:
        """
        Update displayed statistics from processor stats.
        
        Args:
            stats: Dictionary with stats from processor.get_stats()
            running_time: Total running time in seconds
        """
        self.rtf = stats.get('rtf', 0.0)
        self.avg_ms = stats.get('avg_time_ms', 0.0)
        self.frames = stats.get('frame_count', 0)
        self.vad_bypass = stats.get('vad_bypass_ratio', 0.0) * 100  # Convert to percentage
        self.running_time = running_time

    def _update_display(self) -> None:
        """Update the stats display."""
        # Format running time
        mins, secs = divmod(int(self.running_time), 60)
        time_str = f"{mins}:{secs:02d}" if mins > 0 else f"{secs}s"
        
        try:
            self.query_one("#val-rtf", Static).update(f"{self.rtf:.3f}")
            self.query_one("#val-avg", Static).update(f"{self.avg_ms:.2f} ms")
            self.query_one("#val-frames", Static).update(f"{self.frames}")
            self.query_one("#val-vad", Static).update(f"{self.vad_bypass:.0f}%")
            self.query_one("#val-time", Static).update(f"{time_str}")
        except Exception:
            pass
