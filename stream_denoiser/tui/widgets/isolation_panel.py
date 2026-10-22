"""
Isolation panel: the controls that shape the sound.

↑ ↓ pick a row, ← → change it. Strength (the engines' attenuation limit)
and the skip-silence threshold apply to a running session at once; the
model row opens the picker (only while stopped). The panel shows and
asks; the app decides and saves.
"""
from typing import Optional

from textual.binding import Binding
from textual.message import Message
from textual.widgets import Static

from .. import palette as P
from ..settings import AAD_MAX_DB, AAD_MIN_DB, ATTEN_MAX_DB, ATTEN_MIN_DB
from .box import Box

LABEL_W = 11
ROWS = ("strength", "skip", "model")


class IsolationPanel(Box):
    """Box 2: strength, skip below, model, backend."""

    can_focus = True

    BINDINGS = [
        Binding("up", "move(-1)", "Move", show=False),
        Binding("down", "move(1)", "Move", show=False),
        Binding("left", "adjust(-1)", "Adjust", show=False),
        Binding("right", "adjust(1)", "Adjust", show=False),
        Binding("enter", "adjust(0)", "Select", show=False),
    ]

    class Adjust(Message):
        """``row`` asked to change by ``step`` (-1, +1; 0 for enter)."""

        def __init__(self, row: str, step: int) -> None:
            super().__init__()
            self.row = row
            self.step = step

    def __init__(self, strength_db: float, threshold_db: float,
                 **kwargs) -> None:
        super().__init__(number=2, label="isolation",
                         right=lambda: f"[{P.ACCENT}]←→[/] [{P.MUTED}]adjust[/]",
                         **kwargs)
        self.strength_db = strength_db
        self.threshold_db = threshold_db
        self.model = ""
        self.backend = "—"
        self.running = False
        self.row = 0

    def compose(self):
        yield Static(id="isolation-body")

    def on_mount(self) -> None:
        self._draw()

    def on_resize(self) -> None:
        # The body takes its new width in the same layout pass.
        self.call_after_refresh(self._draw)

    def update_values(self, **values) -> None:
        """Any of strength_db, threshold_db, model, backend, running."""
        for key, value in values.items():
            setattr(self, key, value)
        self._draw()

    def action_move(self, step: int) -> None:
        self.row = (self.row + step) % len(ROWS)
        self._draw()

    def action_adjust(self, step: int) -> None:
        self.post_message(self.Adjust(ROWS[self.row], step))

    def _line(self, index: int, label: str, value: str, focused: bool,
              adjustable: bool = True, value_color: str = P.INK) -> str:
        width = self._width()
        selected = index == self.row and focused
        if selected and adjustable:
            tail = f"[{P.ACCENT}]‹ [/][b {P.GOLD}]{value}[/][{P.ACCENT}] › [/]"
            tail_len = len(value) + 5
        else:
            tail = f"[b {value_color}]{value}[/]  "
            tail_len = len(value) + 2
        gap = max(1, width - (LABEL_W + 1) - tail_len)
        line = f"[{P.MUTED}] {label:<{LABEL_W}}[/]{' ' * gap}{tail}"
        return f"[on {P.PILL}]{line}[/]" if selected else line

    def _width(self) -> int:
        try:
            return max(20, self.query_one("#isolation-body").size.width)
        except Exception:
            return 36

    def _draw(self, focused: Optional[bool] = None) -> None:
        """``focused``: the focus state to draw (focus events arrive
        before has_focus changes); None reads it."""
        if focused is None:
            focused = self.has_focus
        try:
            body = self.query_one("#isolation-body", Static)
        except Exception:
            return
        bar_w = self._width() - 1
        strength = ((ATTEN_MAX_DB - self.strength_db)
                    / (ATTEN_MAX_DB - ATTEN_MIN_DB))
        skip = (self.threshold_db - AAD_MIN_DB) / (AAD_MAX_DB - AAD_MIN_DB)
        model_color = P.DIM if self.running else P.INK
        lines = [
            self._line(0, "strength", f"{self.strength_db:.0f} dB", focused),
            " " + P.meter(strength, bar_w, P.ACCENT),
            "",
            self._line(1, "skip below", f"{self.threshold_db:.0f} dB",
                       focused),
            " " + P.meter(skip, bar_w, P.ACCENT_DIM),
            "",
            self._line(2, "model", self.model, focused,
                       adjustable=not self.running,
                       value_color=model_color),
            self._line(-1, "backend", self.backend, focused,
                       adjustable=False),
        ]
        if self.running and self.row == 2 and focused:
            lines.append(f"[{P.DIM}] stop to change the model[/]")
        body.update("\n".join(lines))

    def on_focus(self) -> None:
        self._draw(focused=True)

    def on_blur(self) -> None:
        self._draw(focused=False)
