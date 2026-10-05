"""
Status Line Widget

Two-line status block for the top-right corner:
line 1 = processing state pill, line 2 = latest message.

The status line is driven ONLY by explicit, UX-friendly notify() calls.
Log records are never forwarded here (they go to the file log); this
keeps the widget free of raw tracebacks and diagnostic chatter.
"""
from textual.widgets import Static
from textual.reactive import reactive


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
