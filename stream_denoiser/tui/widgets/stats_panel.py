"""
Stats Panel Widget

Displays real-time processing statistics.
"""
from textual.widgets import Static
from textual.containers import Vertical
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
        self.border_title = "Stats"
    
    def compose(self):
        yield Static(id="stats-content")
    
    def on_mount(self) -> None:
        self._update_display()
    
    def watch_status(self, value: str) -> None:
        self._update_display()
    
    def watch_rtf(self, value: float) -> None:
        self._update_display()
    
    def _update_display(self) -> None:
        """Update the stats display."""
        # Format running time
        mins, secs = divmod(int(self.running_time), 60)
        time_str = f"{mins}:{secs:02d}" if mins > 0 else f"{secs}s"
        
        # Clean minimal layout - just stats, no status
        content = f"""[dim]RTF[/]         {self.rtf:.3f}
[dim]Processing[/]  {self.avg_ms:.2f} ms
[dim]Frames[/]      {self.frames}
[dim]VAD Bypass[/]  {self.vad_bypass:.0f}%
[dim]Duration[/]    {time_str}"""
        
        try:
            stats_content = self.query_one("#stats-content", Static)
            stats_content.update(content)
        except Exception:
            pass
    
    def update_stats(self, stats: dict, running_time: float) -> None:
        """Update stats from processor stats dict."""
        self.rtf = stats.get('last_rtf', 0.0)
        self.avg_ms = stats.get('avg_processing_time', 0.0) * 1000
        self.frames = stats.get('frames_processed', 0)
        self.vad_bypass = stats.get('vad_bypass_ratio', 0.0) * 100
        self.running_time = running_time
    
    def set_running(self, running: bool) -> None:
        """Set the running status."""
        self.status = "Running" if running else "Stopped"
