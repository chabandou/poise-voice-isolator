"""
Device List Widget

Displays available output devices with selection.
"""
from textual.widgets import Static, ListView, ListItem, Label
from textual.containers import Vertical
from textual.reactive import reactive
from typing import List, Tuple, Optional


class DeviceListItem(ListItem):
    """A single device in the list."""
    
    def __init__(self, device_id: int, device_name: str, host_api: str = "") -> None:
        super().__init__()
        self.device_id = device_id
        self.device_name = device_name
        self.host_api = host_api
    
    def compose(self):
        # Truncate long names
        display_name = self.device_name[:40] + "..." if len(self.device_name) > 43 else self.device_name
        yield Label(f"{display_name}")


class DeviceList(Static):
    """Widget to display and select audio output devices."""
    
    DEFAULT_CSS = """
    DeviceList {
        border: heavy $border;
    }
    """
    
    selected_device: reactive[Optional[int]] = reactive(None)
    
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.devices: List[Tuple[int, str, str]] = []  # (id, name, host_api)
        self.border_title = "\[ OUTPUT DEVICES ]"
    
    def compose(self):
        yield ListView(id="device-list")
    
    def on_mount(self) -> None:
        """Load devices when widget mounts."""
        self.refresh_devices()
    
    def refresh_devices(self) -> None:
        """Refresh the device list from sounddevice."""
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            
            self.devices = []
            list_view = self.query_one("#device-list", ListView)
            list_view.clear()
            
            # First pass: collect PulseAudio devices
            pulse_devices = []
            alsa_devices = []
            
            for i, device in enumerate(devices):
                if device.get('max_output_channels', 0) == 0:
                    continue
                    
                name = device.get('name', f'Device {i}')
                name_lower = name.lower()
                
                # Skip monitors, null sinks, and virtual devices
                if any(skip in name_lower for skip in ['monitor', 'null', 'denoiser', 'default']):
                    continue
                
                host_api = sd.query_hostapis(device['hostapi'])['name']
                
                if 'pulse' in host_api.lower():
                    pulse_devices.append((i, name, host_api))
                elif 'alsa' in host_api.lower():
                    # Skip raw ALSA hw devices if we have PulseAudio
                    if not name.startswith('HDA ') and not name.startswith('hw:'):
                        alsa_devices.append((i, name, host_api))
            
            # Prefer PulseAudio, fall back to ALSA
            devices_to_show = pulse_devices if pulse_devices else alsa_devices
            
            for device_id, name, host_api in devices_to_show:
                self.devices.append((device_id, name, host_api))
                list_view.append(DeviceListItem(device_id, name, host_api))
            
            # Select first device by default
            if self.devices and list_view.children:
                list_view.index = 0
                self.selected_device = self.devices[0][0]
                
        except ImportError:
            self.devices = []
    
    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle device selection."""
        if isinstance(event.item, DeviceListItem):
            self.selected_device = event.item.device_id
            # Show feedback in status line
            try:
                from .status_line import StatusLine
                status_line = self.app.query_one("#status-line", StatusLine)
                # Truncate name for status
                name = event.item.device_name[:30] + "..." if len(event.item.device_name) > 33 else event.item.device_name
                status_line.notify(f"Selected: {name}", "success")
            except Exception:
                pass
