"""
Status Line Widget

Displays single-line status updates.
"""
from textual.widgets import Static
from textual.reactive import reactive
from typing import Optional
import logging


class StatusLine(Static):
    """Widget to display single-line status messages with processing status."""
    
    current_message: reactive[str] = reactive("")
    current_level: reactive[str] = reactive("info")
    is_running: reactive[bool] = reactive(False)
    pulse_timer = None
    
    def compose(self):
        yield Static(id="status-text")
    
    def watch_current_message(self, message: str) -> None:
        self._update_display()
    
    def watch_is_running(self, running: bool) -> None:
        self._update_display()
        if running:
            self._start_pulse()
        else:
            self._stop_pulse()
    
    def _start_pulse(self) -> None:
        """Start the pulse animation."""
        self._stop_pulse()
        self.add_class("-pulse-dim")
        self.pulse_timer = self.set_interval(0.8, self._toggle_pulse)
        
    def _stop_pulse(self) -> None:
        """Stop the pulse animation."""
        if self.pulse_timer:
            self.pulse_timer.stop()
            self.pulse_timer = None
        self.remove_class("-pulse-dim")
        
    def _toggle_pulse(self) -> None:
        """Toggle the pulse class."""
        self.toggle_class("-pulse-dim")

    def _update_display(self) -> None:
        # Powerline arrow character (U+E0B0)
        ARROW = "\ue0b8"
        PIPE = "\ue0b6"
        
        # Status segment (mode-like)
        if self.is_running:
            status_bg = "#6eff25"  # Green
            status_text = "● ACTIVE"
        else:
            status_bg = "#3be8ff"  # Blue
            status_text = "○ IDLE"
        
        # Message segment
        if self.current_message:
            icon = "ℹ"
            msg_bg = "#00262bff"  # Blue
            
            if self.current_level == "error":
                icon = "✖"
                msg_bg = "#c62828"  # Red
            elif self.current_level == "warning":
                icon = "⚠"
                msg_bg = "#f9a825"  # Yellow
            elif self.current_level == "success":
                icon = "✔"
                msg_bg = "#2e7d32"  # Green
            
            # Status pill -> Arrow -> Message pill -> Arrow
            content = (
                f"[{status_bg}]{PIPE}"
                f"[bold black on {status_bg}] {status_text} [/]"
                f"[{status_bg} on {msg_bg}]{ARROW}[/]"
                f"[bold white on {msg_bg}] {icon} {self.current_message} [/]"
                f"[{msg_bg} on #1a1a1a]{ARROW}[/]"
            )
        else:
            # Just status pill -> Arrow
            content = (
                f"{status_bg}]{PIPE}"
                f"[bold black on {status_bg}] {status_text} [/]"
                f"[{status_bg} on #1a1a1a]{ARROW}[/]"
            )
            
        try:
            self.query_one("#status-text", Static).update(content)
        except Exception:
            pass
            
    def notify(self, message: str, level: str = "info") -> None:
        """Update the status line."""
        self.current_message = message
        self.current_level = level
    
    def set_running(self, running: bool) -> None:
        """Set the processing status."""
        self.is_running = running
    
    def clear(self) -> None:
        self.current_message = ""


class TUIStatusHandler(logging.Handler):
    """Custom logging handler that updates the TUI status line."""
    
    def __init__(self, status_line: Optional[StatusLine] = None):
        super().__init__()
        self.status_line = status_line
    
    def set_widget(self, status_line: StatusLine) -> None:
        self.status_line = status_line
    
    def emit(self, record: logging.LogRecord) -> None:
        if self.status_line is None:
            return
        
        try:
            msg = self.format(record)
            level = record.levelname.lower()
            if level == "critical":
                level = "error"
            elif level == "debug":
                # Don't show debug messages on status line unless necessary
                return
            
            self.status_line.notify(msg, level)
        except Exception:
            pass
