"""
Poise Voice Isolator - Persistent Settings

Uses QSettings to persist user preferences across sessions.
"""
import sys
import os
from PyQt6.QtCore import QSettings
from typing import Optional, Any


def _get_resource_path(relative_path: str) -> str:
    """
    Get absolute path to a resource file.
    
    Works both in development and when bundled with PyInstaller.
    When bundled, looks for resources next to the executable or in sys._MEIPASS.
    When not bundled, looks relative to the script location.
    
    Args:
        relative_path: Relative path to the resource (e.g., "denoiser_model.onnx")
        
    Returns:
        Absolute path to the resource
    """
    # Check if running as a PyInstaller bundle
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        if hasattr(sys, '_MEIPASS'):
            # One-file mode: resources are in temporary extraction directory
            base_path = sys._MEIPASS
        else:
            # One-folder mode: resources are next to the executable
            base_path = os.path.dirname(sys.executable)
    else:
        # Running as script: look relative to the script location
        # Try to find the project root (where denoiser_model.onnx should be)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        # Go up from stream_denoiser/gui/ to project root
        base_path = os.path.dirname(os.path.dirname(os.path.dirname(script_dir)))
    
    resource_path = os.path.join(base_path, relative_path)
    
    # If not found in primary location, try next to executable (for one-folder mode)
    if not os.path.exists(resource_path) and getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        alt_path = os.path.join(exe_dir, relative_path)
        if os.path.exists(alt_path):
            return alt_path
    
    return resource_path


class Settings:
    """Manages persistent application settings using QSettings."""
    
    ORGANIZATION = "Poise"
    APPLICATION = "VoiceIsolator"
    
    # Setting keys
    KEY_INPUT_DEVICE = "audio/input_device"
    KEY_OUTPUT_DEVICE = "audio/output_device"
    KEY_VAD_ENABLED = "audio/vad_enabled"
    KEY_VAD_THRESHOLD = "audio/vad_threshold"
    KEY_ATTEN_LIM_DB = "audio/atten_lim_db"
    KEY_VB_CABLE_ENABLED = "audio/vb_cable_enabled"
    KEY_VB_CABLE_NAME = "audio/vb_cable_name"
    
    KEY_WINDOW_GEOMETRY = "window/geometry"
    KEY_WINDOW_STATE = "window/state"
    
    KEY_MINIMIZE_TO_TRAY = "behavior/minimize_to_tray"
    KEY_MINIMIZE_TO_TRAY_ASKED = "behavior/minimize_to_tray_asked"
    KEY_SHOW_TRAY_ICON = "behavior/show_tray_icon"
    
    KEY_ONNX_MODEL_PATH = "model/onnx_path"
    
    # Default values
    DEFAULTS = {
        KEY_INPUT_DEVICE: None,
        KEY_OUTPUT_DEVICE: None,
        KEY_VAD_ENABLED: True,
        KEY_VAD_THRESHOLD: -40.0,
        KEY_ATTEN_LIM_DB: -60.0,
        KEY_VB_CABLE_ENABLED: True,
        KEY_VB_CABLE_NAME: None,
        KEY_MINIMIZE_TO_TRAY: True,
        KEY_MINIMIZE_TO_TRAY_ASKED: False,
        KEY_SHOW_TRAY_ICON: True,
        KEY_ONNX_MODEL_PATH: "denoiser_model.onnx",
    }
    
    def __init__(self):
        """Initialize settings manager."""
        self._settings = QSettings(self.ORGANIZATION, self.APPLICATION)
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a setting value.
        
        Args:
            key: Setting key
            default: Default value if not set (uses DEFAULTS if None)
            
        Returns:
            Setting value
        """
        if default is None:
            default = self.DEFAULTS.get(key)
        
        value = self._settings.value(key, default)
        
        # Handle type conversions for QSettings quirks
        if isinstance(default, bool) and isinstance(value, str):
            return value.lower() == 'true'
        if isinstance(default, (int, float)) and isinstance(value, str):
            try:
                return type(default)(value)
            except (ValueError, TypeError):
                return default
        
        return value
    
    def set(self, key: str, value: Any) -> None:
        """
        Set a setting value.
        
        Args:
            key: Setting key
            value: Value to set
        """
        self._settings.setValue(key, value)
    
    def remove(self, key: str) -> None:
        """Remove a setting."""
        self._settings.remove(key)
    
    def sync(self) -> None:
        """Force sync settings to disk."""
        self._settings.sync()
    
    # Convenience properties for common settings
    
    @property
    def input_device(self) -> Optional[int]:
        """Get last selected input device ID."""
        val = self.get(self.KEY_INPUT_DEVICE)
        return int(val) if val is not None else None
    
    @input_device.setter
    def input_device(self, value: Optional[int]) -> None:
        self.set(self.KEY_INPUT_DEVICE, value)
    
    @property
    def output_device(self) -> Optional[int]:
        """Get last selected output device ID."""
        val = self.get(self.KEY_OUTPUT_DEVICE)
        return int(val) if val is not None else None
    
    @output_device.setter
    def output_device(self, value: Optional[int]) -> None:
        self.set(self.KEY_OUTPUT_DEVICE, value)
    
    @property
    def vad_enabled(self) -> bool:
        """Get VAD enabled state."""
        return self.get(self.KEY_VAD_ENABLED, True)
    
    @vad_enabled.setter
    def vad_enabled(self, value: bool) -> None:
        self.set(self.KEY_VAD_ENABLED, value)
    
    @property
    def vad_threshold(self) -> float:
        """Get VAD threshold in dB."""
        return float(self.get(self.KEY_VAD_THRESHOLD, -40.0))
    
    @vad_threshold.setter
    def vad_threshold(self, value: float) -> None:
        self.set(self.KEY_VAD_THRESHOLD, value)
    
    @property
    def atten_lim_db(self) -> float:
        """Get attenuation limit in dB."""
        return float(self.get(self.KEY_ATTEN_LIM_DB, -60.0))
    
    @atten_lim_db.setter
    def atten_lim_db(self, value: float) -> None:
        self.set(self.KEY_ATTEN_LIM_DB, value)
    
    @property
    def vb_cable_enabled(self) -> bool:
        """Get VB Cable auto-switch enabled state."""
        return self.get(self.KEY_VB_CABLE_ENABLED, True)
    
    @vb_cable_enabled.setter
    def vb_cable_enabled(self, value: bool) -> None:
        self.set(self.KEY_VB_CABLE_ENABLED, value)
    
    @property
    def minimize_to_tray(self) -> bool:
        """Get minimize to tray preference."""
        return self.get(self.KEY_MINIMIZE_TO_TRAY, True)
    
    @minimize_to_tray.setter
    def minimize_to_tray(self, value: bool) -> None:
        self.set(self.KEY_MINIMIZE_TO_TRAY, value)
    
    @property
    def minimize_to_tray_asked(self) -> bool:
        """Check if user has been asked about minimize to tray behavior."""
        return self.get(self.KEY_MINIMIZE_TO_TRAY_ASKED, False)
    
    @minimize_to_tray_asked.setter
    def minimize_to_tray_asked(self, value: bool) -> None:
        self.set(self.KEY_MINIMIZE_TO_TRAY_ASKED, value)
    
    @property
    def onnx_model_path(self) -> str:
        """Get ONNX model path."""
        path = self.get(self.KEY_ONNX_MODEL_PATH, "denoiser_model.onnx")
        
        # If it's the default relative path, resolve it relative to executable
        if path == "denoiser_model.onnx" or not os.path.isabs(path):
            resolved_path = _get_resource_path(path)
            # Only use resolved path if it exists, otherwise return original
            if os.path.exists(resolved_path):
                return resolved_path
        
        return path
    
    @onnx_model_path.setter
    def onnx_model_path(self, value: str) -> None:
        self.set(self.KEY_ONNX_MODEL_PATH, value)
    
    def save_window_geometry(self, geometry: bytes) -> None:
        """Save window geometry."""
        self.set(self.KEY_WINDOW_GEOMETRY, geometry)
    
    def load_window_geometry(self) -> Optional[bytes]:
        """Load window geometry."""
        return self.get(self.KEY_WINDOW_GEOMETRY)
    
    def save_window_state(self, state: bytes) -> None:
        """Save window state."""
        self.set(self.KEY_WINDOW_STATE, state)
    
    def load_window_state(self) -> Optional[bytes]:
        """Load window state."""
        return self.get(self.KEY_WINDOW_STATE)


# Global settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get the global settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
