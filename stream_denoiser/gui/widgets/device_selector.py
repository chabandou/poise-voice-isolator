"""
Poise Voice Isolator - Device Selector Widget

Dropdown widget for audio device selection with refresh capability.
"""
from typing import Optional, List, Dict, Any

from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)
from PyQt6.QtCore import Qt, pyqtSignal

from .phosphor import MotionIcon
from ..animations import flash_colour
from ..themes import current as current_theme
from .chip import IconChip
from .combo import BLURB_ROLE, TITLE_ROLE, AnimatedComboBox
from ..scaling import sp

try:
    import sounddevice as sd
    USE_SOUNDDEVICE = True
except ImportError:
    USE_SOUNDDEVICE = False


def is_vb_cable(name: str) -> bool:
    """True for VB-Audio's virtual cable endpoints (e.g. "CABLE Input (VB-Audio
    Virtual Cable)"), even when WASAPI truncates the name. VB-Audio always
    capitalises CABLE, which keeps e.g. "Cable Modem Speakers" out."""
    return "vb-audio" in name.lower() or name.startswith("CABLE ")


def card_text(name: str, is_default: bool = False):
    """(title, blurb) for a device's card in the open list: WASAPI names
    read "Speakers (Realtek(R) Audio)", so the endpoint is the title and
    the hardware the blurb (truncated names may lose the last ")")."""
    title, _, hardware = name.partition(" (")
    hardware = hardware[:-1] if hardware.endswith(")") else hardware
    if not title.strip():
        title, hardware = name, ""
    notes = [part for part in (hardware.strip(),
                               "System default" if is_default else "")
             if part]
    return title.strip(), " · ".join(notes)


class DeviceSelector(QWidget):
    """
    Dropdown widget for selecting audio devices.
    
    Includes a refresh button to rescan devices.
    """
    
    device_changed = pyqtSignal(object)  # Emits device ID (int or None)
    LOCKED_NOTE = "Locked while running"
    
    def __init__(self, label: str, device_type: str = "input",
                 subtitle: str = "", parent=None):
        """
        Initialize device selector.
        
        Args:
            label: Title text for the selector
            device_type: "input" or "output"
            subtitle: One-line caption under the title
            parent: Parent widget
        """
        super().__init__(parent)
        
        self._device_type = device_type
        self._devices: List[Dict[str, Any]] = []
        self._caption = subtitle   # restored when unlocked
        
        self._setup_ui(label, subtitle)
        self.refresh_devices()
    
    def _setup_ui(self, label: str, subtitle: str = ""):
        """Setup the widget UI (icon chip + title row, boxed combo)."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(sp(14))

        header = QHBoxLayout()
        header.setSpacing(sp(14))
        self._chip = IconChip(
            "monitor" if self._device_type == "input" else "speaker",
            size=48, icon_size=24)
        header.addWidget(self._chip)
        titles = QVBoxLayout()
        titles.setSpacing(sp(2))
        self._label = QLabel(label)
        self._label.setObjectName("device-title")
        self._label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        titles.addWidget(self._label)
        self._subtitle = QLabel(subtitle)
        self._subtitle.setObjectName("row-sub")
        self._subtitle.setVisible(bool(subtitle))
        titles.addWidget(self._subtitle)
        header.addLayout(titles)
        header.addStretch()

        self._refresh_btn = QPushButton()
        self._refresh_btn.setObjectName("icon-btn")
        self._refresh_icon = MotionIcon(
            "refresh", color=current_theme()["secondary"], size=15)
        # Let the button (not the icon) own hover so its wash paints.
        self._refresh_icon.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        # Centred: the button is the icon plus equal padding (~28 px in
        # all). Fixed 6 px margins left the boosted icon (isp) more room
        # than it had, so it overflowed right and down, off-centre.
        glyph = self._refresh_icon.width()
        pad = max(sp(4), (sp(28) - glyph) // 2)
        self._refresh_btn.setFixedSize(glyph + 2 * pad, glyph + 2 * pad)
        refresh_layout = QHBoxLayout(self._refresh_btn)
        refresh_layout.setContentsMargins(0, 0, 0, 0)
        refresh_layout.addWidget(self._refresh_icon,
                                 alignment=Qt.AlignmentFlag.AlignCenter)
        self._refresh_btn.setToolTip("Rescan audio devices")
        self._refresh_btn.clicked.connect(self._refresh_icon.spin)
        self._refresh_btn.clicked.connect(self.refresh_devices)
        # Hidden while locked (its icon can't grey out); keeps its room.
        policy = self._refresh_btn.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self._refresh_btn.setSizePolicy(policy)
        header.addWidget(self._refresh_btn)
        layout.addLayout(header)

        # Combo box only
        self._combo = AnimatedComboBox()
        self._combo.setObjectName("device-combo")
        # Long device names elide (full name in the tooltip) instead of
        # setting the card's minimum width.
        self._combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._combo.setMinimumContentsLength(14)
        self._combo.currentIndexChanged.connect(self._on_selection_changed)
        layout.addWidget(self._combo)

        # Pin header + combo to the top: extra column height (the top
        # card stretches on tall windows) must collect below, not
        # between the label and the dropdown.
        layout.addStretch(1)
    
    def refresh_devices(self):
        """Refresh the list of available devices.

        There is no "Default" entry: Poise switches the system default
        playback to VB-Cable while running, so the list only names real
        devices (VB-Cable itself is left out of the outputs). The previous
        choice is kept when it still exists, otherwise the system default
        device is selected (and announced via device_changed).
        """
        if not USE_SOUNDDEVICE:
            self._combo.clear()
            self._combo.addItem("sounddevice not available", None)
            return
        
        # Remember current selection
        current_id = self.selected_device_id
        
        self._combo.blockSignals(True)
        self._combo.clear()
        
        try:
            self._devices = list(sd.query_devices())
            default_id = self._system_default_id()
            for i, device in enumerate(self._devices):
                if self._accepts(device):
                    self._combo.addItem(f"{device['name']}", i)
                    title, blurb = card_text(device['name'], i == default_id)
                    row = self._combo.count() - 1
                    self._combo.setItemData(row, title, TITLE_ROLE)
                    self._combo.setItemData(row, blurb, BLURB_ROLE)
        except Exception as e:
            self._combo.addItem(f"Error: {str(e)}", None)
        if self._combo.count() == 0:
            self._combo.addItem(f"No {self._device_type} devices found", None)
        
        self._select(current_id)
        self._combo.blockSignals(False)
        self._combo.setToolTip(self._combo.currentText())
        if self.selected_device_id != current_id:
            self.device_changed.emit(self.selected_device_id)

    def _accepts(self, device) -> bool:
        """WASAPI devices of the right direction (outputs: not VB-Cable)."""
        key = ('max_input_channels' if self._device_type == "input"
               else 'max_output_channels')
        if device[key] <= 0:
            return False
        host_api = sd.query_hostapis(device['hostapi'])['name']
        if 'wasapi' not in host_api.lower():
            return False
        if self._device_type == "output" and is_vb_cable(device['name']):
            return False
        return True

    def _system_default_id(self) -> Optional[int]:
        """The WASAPI default device (PortAudio's own default is MME)."""
        key = ('default_input_device' if self._device_type == "input"
               else 'default_output_device')
        try:
            for api in sd.query_hostapis():
                if 'wasapi' in api['name'].lower():
                    index = api.get(key, -1)
                    return index if index is not None and index >= 0 else None
        except Exception:
            pass
        return None

    def _select(self, device_id: Optional[int]) -> None:
        """Select device_id, else the system default, else the first item."""
        for wanted in (device_id, self._system_default_id()):
            if wanted is None:
                continue
            index = self._combo.findData(wanted)
            if index >= 0:
                self._combo.setCurrentIndex(index)
                return
        self._combo.setCurrentIndex(0)
    
    def _on_selection_changed(self, index: int):
        """Handle selection change."""
        device_id = self._combo.itemData(index)
        self._combo.setToolTip(self._combo.itemText(index))
        self.device_changed.emit(device_id)
    
    @property
    def selected_device_id(self) -> Optional[int]:
        """Get the currently selected device ID."""
        return self._combo.currentData()
    
    @selected_device_id.setter
    def selected_device_id(self, device_id: Optional[int]):
        """Set the selected device by ID (falls back like refresh_devices)."""
        self._select(device_id)
    
    def set_subtitle(self, text: str) -> None:
        """Change the caption (shown again after an unlock)."""
        self._caption = text
        if not self.is_locked:
            self._show_subtitle(text)

    def _show_subtitle(self, text: str) -> None:
        self._subtitle.setText(text)
        self._subtitle.setVisible(bool(text))

    def set_locked(self, locked: bool) -> None:
        """No picking or rescanning while running; the caption says why."""
        self._combo.setEnabled(not locked)
        self._refresh_btn.setEnabled(not locked)
        self._refresh_btn.setVisible(not locked)
        self._show_subtitle(self.LOCKED_NOTE if locked else self._caption)

    @property
    def is_locked(self) -> bool:
        return not self._combo.isEnabled()

    def enterEvent(self, event):  # noqa: N802 (Qt override)
        self._chip.play()   # the speaker's waves emit
        super().enterEvent(event)

    def mousePressEvent(self, event):  # noqa: N802 (Qt override)
        # A click on the locked (disabled) combo arrives here: say why.
        if self.is_locked and self._combo.geometry().contains(
                event.position().toPoint()):
            self._combo.jiggle()
            flash_colour(self._subtitle, current_theme()["secondary"])
        super().mousePressEvent(event)

    def refresh_theme(self) -> None:
        self._chip.refresh_theme()
        self._refresh_icon.set_color(current_theme()["secondary"])

    def set_enabled(self, enabled: bool):
        """Enable or disable the selector."""
        self._combo.setEnabled(enabled)
