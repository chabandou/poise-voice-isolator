"""
Events panel: box 4, what Poise has been doing, newest first.

Two sources: the app's own notes (add()), and its log, cleaned up
(log_events.py; the log file keeps every record whole). Nothing piles
up: a line repeated as is counts up (×3) instead, a burst of changes to
one setting shares one line, and a sticky line (a periodic summary) is
updated where it stands.
"""
import time
from collections import deque
from typing import Optional

from textual.widgets import Static

from .. import palette as P
from .box import Box

KEEP = 100
# Repeated changes to one setting within this long share one line.
MERGE_SEC = 3.0

_DEFAULT_TAGS = {"warning": "warn", "error": "error"}


def _tag_color(level: str) -> str:
    return {"success": P.GREEN, "warning": P.YELLOW,
            "error": P.RED}.get(level, P.MUTED)


class Event:
    __slots__ = ("when", "message", "level", "tag", "key", "count")

    def __init__(self, message: str, level: str, tag: Optional[str],
                 key: Optional[str]) -> None:
        self.when = time.time()
        self.message = message
        self.level = level
        self.tag = tag
        self.key = key
        self.count = 1


class EventsPanel(Box):
    """Box 4: timestamped notes."""

    can_focus = True

    def __init__(self, **kwargs) -> None:
        super().__init__(number=4, label="events", **kwargs)
        self.events: deque = deque(maxlen=KEEP)

    @property
    def latest(self) -> Optional[Event]:
        return self.events[0] if self.events else None

    def compose(self):
        yield Static(id="events-body")

    def on_mount(self) -> None:
        self._draw()

    def merges(self, key: str) -> bool:
        """An add() with ``key`` now would replace the newest line."""
        latest = self.latest
        return (latest is not None and latest.key == key
                and time.time() - latest.when < MERGE_SEC)

    def add(self, message: str, level: str = "info",
            tag: Optional[str] = None, key: Optional[str] = None,
            sticky: bool = False) -> None:
        """Note ``message``; ``tag`` (default: by level) leads it in the
        level's color. A ``key`` replaces the newest line when it has the
        same key and is recent (one line per burst of key presses); with
        ``sticky`` it replaces that key's line wherever it is."""
        if tag is None:
            tag = _DEFAULT_TAGS.get(level)
        if sticky and key is not None:
            for event in self.events:
                if event.key == key:
                    event.message, event.level, event.tag = message, level, tag
                    event.when = time.time()
                    self._draw()
                    return
        latest = self.latest
        if (latest is not None and latest.message == message
                and latest.level == level and latest.tag == tag):
            latest.count += 1
            latest.when = time.time()
            self._draw()
            return
        if key is not None and not sticky and self.merges(key):
            self.events.popleft()
        self.events.appendleft(Event(message, level, tag, key))
        self._draw()

    def _draw(self) -> None:
        try:
            body = self.query_one("#events-body", Static)
        except Exception:
            return
        lines = []
        for event in self.events:
            stamp = time.strftime("%H:%M", time.localtime(event.when))
            message = event.message.replace("[", "\\[")
            tag = ""
            if event.tag:
                color = _tag_color(event.level)
                tag = f"[{color}]{event.tag}[/]  "
            count = f" [{P.DIM}]×{event.count}[/]" if event.count > 1 else ""
            lines.append(
                f"[{P.DIM}]{stamp}[/]  {tag}[{P.MUTED}]{message}[/]{count}")
        body.update("\n".join(lines))
