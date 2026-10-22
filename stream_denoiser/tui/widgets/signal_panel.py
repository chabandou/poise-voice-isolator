"""
Signal panel: what goes in and what comes out, side by side with the
session's numbers.

The scope scrolls one column per 100 ms level reading: the input above
the midline (grey, eighth blocks rising), the voice that leaves Poise
below it (accent, half blocks hanging), on the same dB scale, so what
was removed is the difference between the two. It stands still while
the terminal window is out of focus (when the terminal reports focus).
"""
from collections import deque
from typing import Optional

from rich.text import Text
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Static

from .. import palette as P
from .box import Box

FLOOR_DB = -60.0   # an empty column
CEIL_DB = -6.0     # a full column
ROWS = 6           # each half of the scope
TICK_SEC = 0.1     # one column per reading (the audio process's window)
# Readings waiting to be drawn: the audio process sends them every 0.5 s;
# beyond this many the scope skips ahead rather than lag.
MAX_BACKLOG = 8

_EIGHTHS = " ▁▂▃▄▅▆▇█"


def _fraction(db: float) -> float:
    return max(0.0, min(1.0, (db - FLOOR_DB) / (CEIL_DB - FLOOR_DB)))


def _db_label(db: Optional[float]) -> str:
    if db is None:
        return "—"
    if db <= FLOOR_DB:
        return "quiet"
    return f"{db:.0f} dB"


class LevelScope(Widget):
    """Input over output level, newest on the right."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._columns: deque = deque(maxlen=512)
        self._pending: deque = deque()
        # Shown while there is nothing to draw.
        self.hint = "space starts isolating"

    def set_hint(self, hint: str) -> None:
        self.hint = hint
        self.refresh()

    def on_mount(self) -> None:
        self.set_interval(TICK_SEC, self._tick)
        self.watch(self.app, "app_focus", self._app_focus_changed,
                   init=False)

    def _app_focus_changed(self, focused: bool) -> None:
        # Back in focus: carry on from now, not from where it stopped.
        self._pending.clear()

    @property
    def paused(self) -> bool:
        return not self.app.app_focus

    def push(self, levels) -> None:
        """Readings from the audio process, oldest first (dropped while
        the window is out of focus)."""
        if not self.paused:
            self._pending.extend(levels)

    def clear(self) -> None:
        self._columns.clear()
        self._pending.clear()
        self.refresh()

    def _tick(self) -> None:
        if not self._pending or self.paused:
            return
        while len(self._pending) > MAX_BACKLOG:
            self._columns.append(self._pending.popleft())
        self._columns.append(self._pending.popleft())
        self.refresh()

    def render(self) -> Text:
        width = max(1, self.size.width)
        cols = list(self._columns)[-width:]
        cols = [None] * (width - len(cols)) + cols
        text = Text(no_wrap=True, overflow="crop")

        # Input: bottom-anchored eighth blocks over ROWS rows.
        ins = [None if c is None else round(_fraction(c[0]) * ROWS * 8)
               for c in cols]
        upper_colors = P.scope_input_rows(ROWS)
        lower_colors = P.scope_voice_rows(ROWS)
        hint = self.hint if not self._columns else ""
        for r in range(ROWS):
            if hint and r == ROWS // 2:
                text.append(hint.center(width)[:width] + "\n", style=P.DIM)
                continue
            base = (ROWS - 1 - r) * 8
            row = "".join(" " if v is None else
                          _EIGHTHS[max(0, min(8, v - base))] for v in ins)
            text.append(row + "\n", style=upper_colors[r])

        # Midline: the latest readings.
        last = cols[-1]
        in_label = f"▲ in {_db_label(None if last is None else last[0])}"
        out_label = f"▼ voice {_db_label(None if last is None else last[1])}"
        run = width - len(in_label) - len(out_label) - 2
        text.append("▲ in ", style=P.MUTED)
        text.append(in_label[5:], style=f"bold {P.SOFT}")
        if run > 0:
            text.append(" " + "╌" * run + " ", style=P.EDGE)
        text.append("▼ voice ", style=P.ACCENT)
        text.append(out_label[8:] + "\n", style=f"bold {P.ACCENT}")

        # Voice: top-anchored half blocks over ROWS rows, mirrored.
        outs = [None if c is None else round(_fraction(c[1]) * ROWS * 2)
                for c in cols]
        for r in range(ROWS):
            chars = []
            for v in outs:
                f = -1 if v is None else v - r * 2
                chars.append("█" if f >= 2 else "▀" if f == 1 else " ")
            text.append("".join(chars) + ("\n" if r < ROWS - 1 else ""),
                        style=lower_colors[r])
        return text


class SessionStats(Static):
    """The model and the running session's load."""

    KEY_W = 9
    VALUE_W = 9
    METER_W = 10

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.model = ""
        self.frame = ""
        self.stats: Optional[dict] = None

    def set_model(self, label: str, frame: str = "") -> None:
        self.model, self.frame = label, frame
        self._draw()

    def set_stats(self, stats: Optional[dict]) -> None:
        """None while idle: every value reads as a dash."""
        self.stats = stats
        self._draw()

    def on_mount(self) -> None:
        self._draw()

    def _row(self, key: str, value: str, value_color: str,
             fraction: Optional[float] = None,
             meter_color: Optional[str] = None) -> str:
        line = (f"[{P.MUTED}]{key:<{self.KEY_W}}[/]"
                f"[b {value_color}]{value:<{self.VALUE_W}}[/]")
        if fraction is not None:
            line += P.meter(fraction, self.METER_W,
                            meter_color or P.ACCENT)
        return line

    def _draw(self) -> None:
        lines = [f"[b {P.GOLD}]{self.model}[/]", f"[{P.MUTED}]{self.frame}[/]", ""]
        s = self.stats
        if not s:
            for key in ("load", "frame", "skipped", "frames"):
                lines.append(self._row(key, "—", P.DIM))
        else:
            rtf = float(s.get("rtf", 0.0))
            load_color = P.GREEN if rtf < 0.5 else P.YELLOW if rtf < 0.8 else P.RED
            lines.append(self._row("load", f"{rtf:.2f}x", load_color,
                                   rtf, load_color))
            lines.append(self._row(
                "frame", f"{float(s.get('avg_time_ms', 0.0)):.2f} ms", P.INK))
            if "aad_bypass_ratio" in s:
                ratio = float(s["aad_bypass_ratio"])
                lines.append(self._row("skipped", f"{ratio:.0%}", P.INK,
                                       ratio, P.GOLD))
            else:
                lines.append(self._row("skipped", "off", P.DIM))
            lines.append(self._row("frames", f"{s.get('frame_count', 0)}",
                                   P.INK))
        self.update("\n".join(lines))


class SignalPanel(Box):
    """Box 1: the scope, the model and the session's numbers."""

    can_focus = True

    def __init__(self, **kwargs) -> None:
        super().__init__(number=1, label="signal",
                         prefix=lambda: f"[b {P.ACCENT}]∿ poise[/]",
                         **kwargs)

    def compose(self):
        with Horizontal(id="signal-body"):
            yield LevelScope(id="scope")
            yield SessionStats(id="session-stats")
