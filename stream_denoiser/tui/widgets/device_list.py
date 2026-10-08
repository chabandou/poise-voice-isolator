"""
Device List Widget

Displays available PulseAudio output sinks (by name) with selection.
"""
from textual.widgets import Static, ListView, ListItem, Label
from textual.containers import Vertical
from textual.reactive import reactive
from typing import List, Tuple, Optional


class DeviceListItem(ListItem):
    """A single sink in the list."""

    def __init__(self, sink_name: str, description: str) -> None:
        super().__init__()
        self.sink_name = sink_name
        self.device_name = description

    def compose(self):
        # Truncate long names
        display_name = self.device_name[:40] + "..." if len(self.device_name) > 43 else self.device_name
        yield Label(f"{display_name}")


class DeviceList(Static):
    """Widget to display and select audio output sinks (Pulse names)."""

    DEFAULT_CSS = """
    DeviceList {
        border: heavy $border;
    }
    """

    selected_device: reactive[Optional[str]] = reactive(None)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.devices: List[Tuple[str, str]] = []  # (sink_name, description)
        self.border_title = "\\[ OUTPUT DEVICES ]"

    def compose(self):
        yield ListView(id="device-list")

    def on_mount(self) -> None:
        """Load devices when widget mounts."""
        self.refresh_devices()

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
            sinks = [s for s in list_pulseaudio_sinks()
                     if s.name != "Poise_Capture"]
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

            # Default to the original default sink, else the first sink.
            selected = None
            if self.devices:
                names = [name for name, _ in self.devices]
                if default_sink in names:
                    selected = default_sink
                else:
                    selected = names[0]
                try:
                    list_view.index = names.index(selected)
                except Exception:
                    list_view.index = 0
                self.selected_device = selected
            else:
                self.selected_device = None
                try:
                    from .status_line import StatusLine
                    status_line = self.app.query_one("#status-line", StatusLine)
                    status_line.notify("No PulseAudio sinks found", "error")
                except Exception:
                    pass
        except Exception:
            self.devices = []
            self.selected_device = None

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle sink selection."""
        if isinstance(event.item, DeviceListItem):
            self.selected_device = event.item.sink_name
            # Show feedback in status line
            try:
                from .status_line import StatusLine
                status_line = self.app.query_one("#status-line", StatusLine)
                # Truncate name for status
                name = event.item.device_name[:30] + "..." if len(event.item.device_name) > 33 else event.item.device_name
                status_line.notify(f"Selected: {name}", "success")
            except Exception:
                pass
