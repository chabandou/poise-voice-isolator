"""
VAD Panel Widget

Displays Voice Activity Detector status and controls.
"""
from textual.widgets import Static, Switch, Label
from textual.containers import Vertical, Horizontal
from textual.reactive import reactive


class VADPanel(Static):
    """Widget to display and control Voice Activity Detector settings."""
    
    DEFAULT_CSS = """
    VADPanel {
        border: heavy $border;
    }
    """
    
    # Reactive properties
    vad_enabled: reactive[bool] = reactive(True)
    threshold_db: reactive[float] = reactive(-40.0)
    
    # Bar configuration
    BAR_WIDTH = 40
    MIN_DB = -80.0
    MAX_DB = 0.0
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.border_title = "\[ VOICE DETECTOR ]"
    
    def compose(self):
        with Vertical(id="vad-container"):
            # Enabled status row
            with Horizontal(classes="vad-row"):
                yield Static("Status", classes="vad-label")
                yield Static("● ENABLED", classes="vad-status", id="vad-status-indicator")
            
            # Threshold row with value
            with Horizontal(classes="vad-row"):
                yield Static("Threshold", classes="vad-label")
                yield Static("-40.0 dB", classes="vad-value", id="vad-threshold-value")
            
            # Visual bar
            with Horizontal(classes="vad-row"):
                yield Static("", classes="vad-label")  # spacer
                yield Static(self._render_bar(-40.0), classes="vad-bar", id="vad-threshold-bar")
            
            # Key hints
            with Horizontal(classes="vad-row"):
                yield Static("", classes="vad-label")  # spacer
                yield Static("[-] Quiet ←→ Loud [+]", classes="vad-hint")
    
    def _render_bar(self, threshold_db: float) -> str:
        """Render a visual bar for the threshold level."""
        # Map threshold from [MIN_DB, MAX_DB] to [0, BAR_WIDTH]
        normalized = (threshold_db - self.MIN_DB) / (self.MAX_DB - self.MIN_DB)
        filled = int(normalized * self.BAR_WIDTH)
        
        # Use block characters for visual bar
        bar = "█" * filled + "░" * (self.BAR_WIDTH - filled)
        return f"[{bar}]"
    
    def set_enabled(self, enabled: bool) -> None:
        """Update the enabled status display."""
        self.vad_enabled = enabled
        try:
            indicator = self.query_one("#vad-status-indicator", Static)
            if enabled:
                indicator.update("[#3be8ff]● ENABLED[/]")
            else:
                indicator.update("[dim]○ DISABLED[/]")
        except Exception:
            pass
    
    def set_threshold(self, threshold_db: float) -> None:
        """Update the threshold display and bar."""
        self.threshold_db = threshold_db
        try:
            self.query_one("#vad-threshold-value", Static).update(f"{threshold_db:.1f} dB")
            self.query_one("#vad-threshold-bar", Static).update(self._render_bar(threshold_db))
        except Exception:
            pass
