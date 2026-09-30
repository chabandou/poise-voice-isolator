"""
Model Picker Modal

Popup list for switching denoising engines. Shows every known model with a
friendly name, a one-line tradeoff note, and availability status —
so future models appear here with just a MODEL_INFO entry.

Styled after the app sections: transparent-dark surface, round accent
border with accent title, dim-gray hints.
"""
from typing import Optional

from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, ListItem, ListView

from ...constants import ALL_MODELS, MODEL_INFO


class ModelPickerItem(ListItem):
    """One model row in the picker."""

    def __init__(self, model_id: str, label: str, detail: str) -> None:
        super().__init__()
        self.model_id = model_id
        self.label = label
        self.detail = detail

    def compose(self):
        yield Label(self.label, classes="model-name")
        yield Label(self.detail, classes="model-detail")


class ModelPickerScreen(ModalScreen[Optional[str]]):
    """Modal model picker. Dismisses with the chosen model id (or None)."""

    DEFAULT_CSS = """
    ModelPickerScreen {
        align: center middle;
    }
    ModelPickerScreen > Vertical {
        width: 60;
        height: auto;
        max-height: 18;
        background: #1a1a1a;
        border: round $accent;
        border-title-color: $accent;
        border-title-background: transparent;
        border-title-style: bold;
        padding: 1 2 0 2;
    }
    ModelPickerScreen ListView {
        height: auto;
        max-height: 12;
        background: transparent;
    }
    ModelPickerScreen ListItem {
        height: auto;
        padding: 0 1;
        margin-bottom: 1;
        background: transparent;
    }
    ModelPickerScreen ListItem.--highlight {
        background: $accent;
    }
    ModelPickerScreen ListItem.--highlight > Label {
        background: transparent;
        color: #1a1a1a;
    }
    ModelPickerScreen .model-name {
        color: $text;
    }
    ModelPickerScreen .model-detail {
        color: #888888;
    }
    ModelPickerScreen .picker-hint {
        color: #888888;
        content-align: center middle;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, current: str) -> None:
        super().__init__()
        self._current = current

    def on_mount(self) -> None:
        container = self.query_one(Vertical)
        # NB: brackets must be escaped — "[ MODEL ]" parses as a style tag.
        container.border_title = "\\[ MODEL ]"
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
                    blurb = info.get("picker_blurb", info.get("blurb", ""))
                    if model_id == self._current:
                        marker, detail = "● ", f"{blurb} (current)"
                    elif model_id in usable:
                        marker, detail = "○ ", blurb
                    else:
                        reason = model_unavailable_reason(model_id) or "unavailable"
                        marker, detail = "✕ ", f"{reason}"
                        if blurb:
                            detail = f"{blurb} — {reason}"
                    yield ModelPickerItem(model_id, f"{marker}{label}", detail)
            yield Label("Enter: select   Esc: cancel", classes="picker-hint")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Confirm the highlighted model."""
        if isinstance(event.item, ModelPickerItem):
            self.dismiss(event.item.model_id)

    def action_cancel(self) -> None:
        """Close without changing the model."""
        self.dismiss(None)
