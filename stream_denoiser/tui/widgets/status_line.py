"""
Status Line Widget

Two-line status block for the top-right corner:
line 1 = processing state pill, line 2 = latest message.
"""
from textual.widgets import Static
from textual.reactive import reactive
from typing import Optional
import logging


class StatusLine(Static):
    """Widget to display processing status and messages (top-right)."""
    
    current_message: reactive[str] = reactive("")
    current_level: reactive[str] = reactive("info")
    is_running: reactive[bool] = reactive(False)
    
    def compose(self):
        yield Static(id="status-state")
        yield Static(id="status-text")

    def on_mount(self) -> None:
        self._update_display()
    
    def watch_current_message(self, message: str) -> None:
        self._update_display()
    
    def watch_is_running(self, running: bool) -> None:
        self._update_display()

    def _update_display(self) -> None:
        # Line 1: bare status text (no pill background, so its width stays
        # independent of the message line below). Line 2: level-colored msg.
        if self.is_running:
            state = "[#6eff25]● ACTIVE[/]"
        else:
            state = "[#888888]●[/] [white]IDLE[/]"
        
        if self.current_message:
            # White while running, dimmed gray while idle/paused.
            color = "white" if self.is_running else "#888888"
            message = f"[{color}]{self.current_message}[/]"
        else:
            message = ""
            
        try:
            self.query_one("#status-state", Static).update(state)
            self.query_one("#status-text", Static).update(message)
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
    """Custom logging handler that updates the TUI status line.

    Only warnings and above reach the status line (line 2). Routine
    INFO/DEBUG chatter is file-only; direct notify() calls are unaffected.
    """

    def __init__(self, status_line: Optional[StatusLine] = None):
        super().__init__(level=logging.WARNING)
        self.status_line = status_line
    
    def set_widget(self, status_line: StatusLine) -> None:
        self.status_line = status_line
    
    def emit(self, record: logging.LogRecord) -> None:
        if self.status_line is None:
            return
        if record.levelno < logging.WARNING:
            # Routine chatter stays in the file log, off the status line.
            return

        try:
            msg = self.format(record)
            level = record.levelname.lower()
            if level == "critical":
                level = "error"

            self.status_line.notify(msg, level)
        except Exception:
            pass
