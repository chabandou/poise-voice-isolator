"""
Box: the framed, numbered panel every part of the screen sits in.

The top border carries the panel's number and name on the left
(``2 isolation``) and an optional note on the right (a key hint, the
session state). Textual
draws one title per edge, so the two are joined by a run of the border's
own line character; that run takes the title color, which the stylesheet
keeps equal to the border color (and both turn to the accent while the
box holds focus).
"""
from typing import Callable, Union

from textual.containers import Vertical
from textual.content import Content

from .. import palette as P

# Cells the border keeps around a title: a corner and a blank each side.
_TITLE_RESERVED = 4


# Title markup, or a function giving it (colors are read when drawn).
Markup = Union[str, Callable[[], str]]


def _text(markup: Markup) -> str:
    return markup() if callable(markup) else markup


class Box(Vertical):
    """A framed panel, focused with its number key."""

    def __init__(self, *children, number: int, label: str,
                 prefix: Markup = "", right: Markup = "", **kwargs) -> None:
        super().__init__(*children, **kwargs)
        self.number = number
        self.label = label
        self.prefix = prefix
        self._right = right

    @property
    def left_title(self) -> str:
        # Full-size digits: a terminal draws superscripts too small to read.
        prefix = _text(self.prefix)
        head = f"{prefix}  " if prefix else ""
        return f"{head}[b {P.ACCENT}]{self.number}[/] [b {P.INK}]{self.label}[/]"

    def set_right(self, markup: Markup) -> None:
        if markup != self._right:
            self._right = markup
            self._draw_title()

    def on_mount(self) -> None:
        self._draw_title()

    def on_resize(self) -> None:
        self._draw_title()

    def _draw_title(self) -> None:
        left = self.left_title
        right = _text(self._right)
        free = (self.size.width - _TITLE_RESERVED
                - Content.from_markup(left).cell_length)
        if right:
            # " ─── right": two blanks around the run, at least one cell.
            run = free - Content.from_markup(right).cell_length - 2
            if run >= 1:
                left = f"{left} {'─' * run} {right}"
        self.border_title = left

    def focus_box(self) -> None:
        """Focus the box, or the first thing in it that takes focus."""
        if self.can_focus:
            self.focus()
            return
        for widget in self.query("*"):
            if widget.focusable:
                widget.focus()
                return
