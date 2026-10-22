"""
Device List Widget

Box 3: the PulseAudio output sinks (by name). The one in use carries a
gold dot; ↑ ↓ move, enter picks. Locked while a session runs (the sink
is chosen at start).
"""
from typing import List, Optional, Tuple

from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Label, ListItem, ListView, Static

from .. import palette as P
from .box import Box

NAME_MAX = 40


class DeviceListItem(ListItem):
    """A single sink in the list."""

    def __init__(self, sink_name: str, description: str) -> None:
        super().__init__()
        self.sink_name = sink_name
        self.device_name = description
        self.in_use = False

    def compose(self):
        yield Label(self._text())

    def _text(self) -> str:
        name = self.device_name
        if len(name) > NAME_MAX + 3:
            name = name[:NAME_MAX] + "..."
        name = name.replace("[", "\\[")
        if self.in_use:
            return f"[{P.GOLD}]●[/] [b]{name}[/]"
        return f"  [{P.MUTED}]{name}[/]"

    def repaint(self) -> None:
        try:
            self.query_one(Label).update(self._text())
        except Exception:
            pass

    def set_in_use(self, in_use: bool) -> None:
        if in_use != self.in_use:
            self.in_use = in_use
            try:
                self.query_one(Label).update(self._text())
            except Exception:
                pass


class DeviceList(Box):
    """Widget to display and select audio output sinks (Pulse names)."""

    selected_device: reactive[Optional[str]] = reactive(None)

    class Picked(Message):
        """The user picked a sink (not posted for the automatic choice)."""

        def __init__(self, sink_name: str) -> None:
            super().__init__()
            self.sink_name = sink_name

    def __init__(self, preferred: Optional[str] = None, **kwargs) -> None:
        super().__init__(number=3, label="output",
                         right=lambda: f"[{P.ACCENT}]r[/] [{P.MUTED}]refresh[/]",
                         **kwargs)
        # The sink to select whenever it is present (the last one picked).
        self.preferred = preferred
        self.devices: List[Tuple[str, str]] = []  # (sink_name, description)

    def compose(self):
        yield ListView(id="device-list")
        yield Static("", id="device-note")

    def on_mount(self) -> None:
        """Load devices when widget mounts."""
        self.refresh_devices()

    def watch_selected_device(self, sink_name: Optional[str]) -> None:
        for item in self.query(DeviceListItem):
            item.set_in_use(item.sink_name == sink_name)

    def set_locked(self, locked: bool) -> None:
        """While a session runs the sink cannot change."""
        try:
            self.query_one("#device-list", ListView).disabled = locked
            self.query_one("#device-note", Static).update(
                f"[{P.DIM}]  locked while isolating[/]" if locked else "")
        except Exception:
            pass

    def _note(self, message: str, level: str = "info") -> None:
        note = getattr(self.app, "note", None)
        if note is not None:
            note(message, level)

    def refresh_devices(self) -> None:
        """Refresh the sink list from PulseAudio."""
        try:
            from ...backends.platform.linux import (
                list_pulseaudio_sinks, get_default_sink_name,
            )
        except ImportError:
            self.devices = []
            return
        try:
            from ...constants import PW_NODE_NAME
            sinks = [s for s in list_pulseaudio_sinks()
                     if s.name not in ("Poise_Capture", PW_NODE_NAME)]
            # Exclude other null/virtual sinks from the picker.
            sinks = [s for s in sinks if "null" not in s.name.lower()]
            self.devices = []
            list_view = self.query_one("#device-list", ListView)
            list_view.clear()

            default_sink = None
            try:
                default_sink = get_default_sink_name()
            except Exception:
                default_sink = None

            for sink in sinks:
                self.devices.append((sink.name, sink.description))
                list_view.append(DeviceListItem(sink.name, sink.description))

            # Prefer the last picked sink, then the original default sink,
            # else the first sink.
            selected = None
            if self.devices:
                names = [name for name, _ in self.devices]
                if self.preferred in names:
                    selected = self.preferred
                elif default_sink in names:
                    selected = default_sink
                else:
                    selected = names[0]
                try:
                    list_view.index = names.index(selected)
                except Exception:
                    list_view.index = 0
                self.selected_device = selected
                # New items: mark the one in use even if it did not change.
                self.watch_selected_device(selected)
            else:
                self.selected_device = None
                self._note("No PulseAudio sinks found", "error")
        except Exception:
            self.devices = []
            self.selected_device = None

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle sink selection."""
        if isinstance(event.item, DeviceListItem):
            self.selected_device = event.item.sink_name
            self.preferred = event.item.sink_name
            self.post_message(self.Picked(event.item.sink_name))
            name = event.item.device_name
            if len(name) > 33:
                name = name[:30] + "..."
            self._note(f"output → {name}", "success")
