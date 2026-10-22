"""
Model Picker Modal

Popup list for switching denoising engines. Shows every known model with a
friendly name, a one-line tradeoff note, and availability status —
so future models appear here with just a MODEL_INFO entry.

As designed: "Choose model" on an accent border over a dimmed screen,
two lines per model, the highlighted one filled with the accent
(▶ name, "current" on the right for the model in use).
"""
from typing import Optional

from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, ListItem, ListView

from ...constants import ALL_MODELS, MODEL_INFO
from .. import palette as P


class ModelPickerItem(ListItem):
    """One model row in the picker."""

    def __init__(self, model_id: str, label: str, detail: str,
                 current: bool = False, usable: bool = True) -> None:
        super().__init__()
        self.model_id = model_id
        self.label = label
        self.detail = detail
        self.current = current
        self.usable = usable
        self.set_class(not usable, "-unusable")

    def compose(self):
        with Horizontal(classes="model-head"):
            yield Label(self._marker(), classes="model-marker")
            yield Label(self.label.replace("[", "\\["), classes="model-name")
            yield Label("current" if self.current else "",
                        classes="model-tag")
        yield Label(self.detail.replace("[", "\\["), classes="model-detail")

    def _marker(self) -> str:
        return "▶" if self.highlighted else ""

    def watch_highlighted(self, value: bool) -> None:
        super().watch_highlighted(value)
        try:
            self.query_one(".model-marker", Label).update(self._marker())
        except Exception:
            pass


class ModelPickerScreen(ModalScreen[Optional[str]]):
    """Modal model picker. Dismisses with the chosen model id (or None)."""

    DEFAULT_CSS = """
    ModelPickerScreen {
        align: center middle;
    }
    ModelPickerScreen > Vertical {
        width: 56;
        height: auto;
        max-height: 20;
        border: round $poise-accent;
        border-title-color: $poise-accent;
        border-title-style: bold;
        padding: 1 1 0 1;
    }
    ModelPickerScreen ListView {
        height: auto;
        max-height: 14;
    }
    ModelPickerScreen ListItem {
        height: auto;
        padding: 0 1;
        margin-bottom: 1;
    }
    ModelPickerScreen .model-head {
        height: 1;
    }
    ModelPickerScreen .model-marker {
        width: 2;
    }
    ModelPickerScreen .model-name {
        width: 1fr;
        color: $poise-text;
    }
    ModelPickerScreen .model-tag {
        width: auto;
        color: $poise-muted;
    }
    ModelPickerScreen .model-detail {
        color: $poise-muted;
        padding-left: 2;
    }
    ModelPickerScreen ListItem.-unusable .model-name {
        color: $poise-dim;
    }
    ModelPickerScreen .picker-hint {
        width: 1fr;
        content-align: center middle;
        margin-bottom: 1;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, current: str) -> None:
        super().__init__()
        self._current = current

    def on_mount(self) -> None:
        self.query_one(Vertical).border_title = "Choose model"
        # Start the highlight on the current model
        try:
            items = list(self.query(ModelPickerItem))
            ids = [item.model_id for item in items]
            self.query_one("#model-picker-list", ListView).index = ids.index(
                self._current
            )
        except (ValueError, Exception):
            pass

    def compose(self):
        from ...engines import available_models, model_unavailable_reason

        usable = set(available_models())
        with Vertical():
            with ListView(id="model-picker-list"):
                for model_id in ALL_MODELS:
                    info = MODEL_INFO.get(model_id, {})
                    label = info.get("label", model_id)
                    # Picker shows the tradeoff blurb (independent of the
                    # performance panel's pipeline description).
                    detail = info.get("picker_blurb", info.get("blurb", ""))
                    ok = model_id in usable
                    if not ok:
                        detail = (model_unavailable_reason(model_id)
                                  or "unavailable")
                    yield ModelPickerItem(model_id, label, detail,
                                          current=model_id == self._current,
                                          usable=ok)
            key = f"[b {P.ACCENT}]{{}}[/]"
            yield Label(
                f"{key.format('↑ ↓')} [{P.MUTED}]move[/]   "
                f"{key.format('enter')} [{P.MUTED}]pick[/]   "
                f"{key.format('esc')} [{P.MUTED}]cancel[/]",
                classes="picker-hint")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Confirm the highlighted model."""
        if isinstance(event.item, ModelPickerItem):
            self.dismiss(event.item.model_id)

    def action_cancel(self) -> None:
        """Close without changing the model."""
        self.dismiss(None)
