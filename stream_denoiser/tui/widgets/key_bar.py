"""
Key bar: the bottom line of key hints, quit on the far right.

Drawn from the app's state (start or stop; the model key is dimmed while
a session runs), so it says what each key does right now.
"""
from textual.widgets import Static

from .. import palette as P


def _key(key: str, what: str, enabled: bool = True) -> str:
    if not enabled:
        return f"[b {P.DIM}]{key}[/] [{P.DIM}]{what}[/]"
    return f"[b {P.ACCENT}]{key}[/] [{P.MUTED}]{what}[/]"


class KeyBar(Static):
    """One line of key hints."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.running = False

    def on_mount(self) -> None:
        self._draw()

    def on_resize(self) -> None:
        self._draw()

    def set_running(self, running: bool) -> None:
        self.running = running
        self._draw()

    def _draw(self) -> None:
        keys = [
            ("space", "stop" if self.running else "start", True),
            ("1-4", "focus box", True),
            ("m", "model", not self.running),
            ("r", "refresh", True),
            ("t", "theme", True),
        ]
        quit_key = ("q", "quit")
        width = self.size.width
        used = sum(len(k) + len(w) + 1 for k, w, _ in keys) + 3 * (len(keys) - 1)
        used += len(quit_key[0]) + len(quit_key[1]) + 1
        gap = max(3, width - used - 4)
        line = "   ".join(_key(*k) for k in keys)
        self.update(f"  {line}{' ' * gap}{_key(*quit_key)}")
