"""
Device List Widget

Box 3: the output devices, by name — PulseAudio's sinks on Linux; on macOS
the Core Audio outputs, because a Mac has no PulseAudio server and the tap
carries every app's audio (so there is no capture device to pick). The one
in use carries a gold dot; ↑ ↓ move, enter picks. Locked while a session
runs (the output is chosen at start).
"""
from typing import List, Optional, Tuple

from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Label, ListItem, ListView, Static

from .. import palette as P
from ...platform_utils import is_macos
from .box import Box

NAME_MAX = 40

# (device name the audio backend is given, the line shown in the list)
DeviceEntries = List[Tuple[str, str]]


def _pulse_sinks() -> Optional[Tuple[DeviceEntries, Optional[str]]]:
    """([(sink name, description)], default sink's name), or None.

    None when there is no PulseAudio module to ask at all. A machine without
    a PulseAudio server answers with an empty list instead (that is how macOS
    answers), which is a different thing to say on screen.
    """
    try:
        from ...backends.platform.linux import (
            get_default_sink_name, list_pulseaudio_sinks,
        )
        from ...constants import PW_NODE_NAME
    except ImportError:
        return None
    try:
        sinks = [s for s in list_pulseaudio_sinks()
                 if s.name not in ("Poise_Capture", PW_NODE_NAME)]
        # Exclude other null/virtual sinks from the picker.
        sinks = [s for s in sinks if "null" not in s.name.lower()]
    except Exception:
        return None
    try:
        default_sink = get_default_sink_name()
    except Exception:
        default_sink = None
    return [(s.name, s.description) for s in sinks], default_sink


def _core_audio_outputs() -> Optional[Tuple[DeviceEntries, Optional[str]]]:
    """([(device name, description)], the default output's name) on macOS.

    The output devices only: Poise taps all system audio, so there is no
    capture device to choose (backends/platform/macos.py). The name is what
    the app resolves to a UID before it starts; a Poise aggregate another
    run left behind is not a choice.
    """
    try:
        from ...backends.platform.macos import (
            default_output_device, list_core_audio_devices,
        )

        devices = [d for d in list_core_audio_devices()
                   if d.can_play and not d.name.startswith("Poise")]
        default = default_output_device()
    except Exception:
        return None
    entries = [(d.name, f"{d.name} ({d.transport or '?'}, "
                        f"{d.nominal_rate // 1000} kHz)") for d in devices]
    return entries, (default.name if default is not None else None)


class DeviceListItem(ListItem):
    """A single output device in the list."""

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
    """Widget to display and select audio output devices (see
    refresh_devices for the platform's source)."""

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
        """While a session runs the output cannot change."""
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
        """Refresh the output list from this platform's device source."""
        sources = _pulse_sinks()
        what = "PulseAudio sinks"
        if is_macos() and not (sources and sources[0]):
            # A Mac has no PulseAudio server, so its sink list is empty (or
            # unavailable) by definition: the Core Audio outputs are the
            # list there.
            sources = _core_audio_outputs()
            what = "Core Audio output devices"
        if sources is None:
            self.devices = []
            self.selected_device = None
            return
        entries, default_sink = sources
        try:
            self.devices = []
            list_view = self.query_one("#device-list", ListView)
            list_view.clear()

            for name, description in entries:
                self.devices.append((name, description))
                list_view.append(DeviceListItem(name, description))

            # Prefer the last picked device, then the platform's default,
            # else the first one.
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
                self._note(f"No {what} found", "error")
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
