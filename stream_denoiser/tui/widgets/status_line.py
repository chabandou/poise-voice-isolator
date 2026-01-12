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
    
    def compose(self):
        yield Static(id="status-text")
    
    def watch_current_message(self, message: str) -> None:
        self._update_display()
    
    def watch_is_running(self, running: bool) -> None:
        self._update_display()

    def _update_display(self) -> None:
        # Processing status indicator
        if self.is_running:
            status_part = "[green]● Running[/]"
        else:
            status_part = "[yellow]○ Stopped[/]"
        
        # Message part
        if self.current_message:
            icon = "ℹ"
            color = "blue"
            
            if self.current_level == "error":
                icon = "✖"
                color = "red"
            elif self.current_level == "warning":
                icon = "⚠"
                color = "yellow"
            elif self.current_level == "success":
                icon = "✔"
                color = "green"
            
            msg_part = f" │ [{color}]{icon}[/] {self.current_message}"
        else:
            msg_part = ""
            
        content = f"{status_part}{msg_part}"
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
