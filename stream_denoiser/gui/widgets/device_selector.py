"""
Poise Voice Isolator - Device Selector Widget

Dropdown widget for audio device selection with refresh capability.
"""
from typing import Optional, List, Dict, Any

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QComboBox, QPushButton, QLabel, QVBoxLayout
from PyQt6.QtCore import pyqtSignal

try:
    import sounddevice as sd
    USE_SOUNDDEVICE = True
except ImportError:
    USE_SOUNDDEVICE = False


class DeviceSelector(QWidget):
    """
    Dropdown widget for selecting audio devices.
    
    Includes a refresh button to rescan devices.
    """
    
    device_changed = pyqtSignal(object)  # Emits device ID (int or None)
    
    def __init__(self, label: str, device_type: str = "input", parent=None):
        """
        Initialize device selector.
        
        Args:
            label: Label text for the selector
            device_type: "input" or "output"
            parent: Parent widget
        """
        super().__init__(parent)
        
        self._device_type = device_type
        self._devices: List[Dict[str, Any]] = []
        
        self._setup_ui(label)
        self.refresh_devices()
    
    def _setup_ui(self, label: str):
        """Setup the widget UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        
        # Label
        self._label = QLabel(label)
        layout.addWidget(self._label)
        
        # Combo box only
        self._combo = QComboBox()
        self._combo.currentIndexChanged.connect(self._on_selection_changed)
        layout.addWidget(self._combo)
    
    def refresh_devices(self):
        """Refresh the list of available devices."""
        if not USE_SOUNDDEVICE:
            self._combo.clear()
            self._combo.addItem("sounddevice not available", None)
            return
        
        # Remember current selection
        current_id = self.selected_device_id
        
        self._combo.blockSignals(True)
        self._combo.clear()
        
        # Add default option
        self._combo.addItem("Default", None)
        
        # Get devices
        try:
            devices = sd.query_devices()
            self._devices = list(devices)
            
            for i, device in enumerate(self._devices):
                # Filter by device type
                if self._device_type == "input":
                    if device['max_input_channels'] <= 0:
                        continue
                    # Prefer WASAPI devices
                    host_api = sd.query_hostapis(device['hostapi'])['name']
                    if 'wasapi' not in host_api.lower():
                        continue
                elif self._device_type == "output":
                    if device['max_output_channels'] <= 0:
                        continue
                    # Prefer WASAPI devices
                    host_api = sd.query_hostapis(device['hostapi'])['name']
                    if 'wasapi' not in host_api.lower():
                        continue
                
                # Add to dropdown
                display_name = f"{device['name']}"
                self._combo.addItem(display_name, i)
            
        except Exception as e:
            self._combo.addItem(f"Error: {str(e)}", None)
        
        # Restore selection if possible
        if current_id is not None:
            for i in range(self._combo.count()):
                if self._combo.itemData(i) == current_id:
                    self._combo.setCurrentIndex(i)
                    break
        
        self._combo.blockSignals(False)
    
    def _on_selection_changed(self, index: int):
        """Handle selection change."""
        device_id = self._combo.itemData(index)
        self.device_changed.emit(device_id)
    
    @property
    def selected_device_id(self) -> Optional[int]:
        """Get the currently selected device ID."""
        return self._combo.currentData()
    
    @selected_device_id.setter
    def selected_device_id(self, device_id: Optional[int]):
        """Set the selected device by ID."""
        for i in range(self._combo.count()):
            if self._combo.itemData(i) == device_id:
                self._combo.setCurrentIndex(i)
                return
        
        # If not found, select default
        self._combo.setCurrentIndex(0)
    
    def set_enabled(self, enabled: bool):
        """Enable or disable the selector."""
        self._combo.setEnabled(enabled)
