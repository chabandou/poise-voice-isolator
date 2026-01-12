"""
Windows Platform Audio Utilities

Windows-specific audio functionality:
- VB Cable switching via PowerShell
- WASAPI loopback device detection

This module is EXCLUDED from Linux builds via PyInstaller spec.
"""
import subprocess
import time
from typing import Optional

from ...constants import (
    POWERSHELL_CHECK_TIMEOUT_SEC,
    POWERSHELL_DEFAULT_TIMEOUT_SEC,
    POWERSHELL_MODULE_CHECK_TIMEOUT_SEC,
    POWERSHELL_MODULE_INSTALL_TIMEOUT_SEC,
    DEVICE_SWITCH_SETTLE_TIME_SEC,
    MSG_DEVICE_SWITCH_ERROR,
)
from ...logging_config import get_logger

_logger = get_logger(__name__)


class VBCableSwitcher:
    """
    Manages switching Windows default playback device to VB Cable.
    Uses PowerShell AudioDeviceCmdlets module to change default audio device.
    
    This is the new location for VB Cable functionality.
    The old vb_cable.py is kept for backwards compatibility during migration.
    """
    
    # PowerShell command templates
    _PS_IMPORT_MODULE = "Import-Module AudioDeviceCmdlets -ErrorAction SilentlyContinue"
    _PS_GET_DEFAULT_DEVICE = f"{_PS_IMPORT_MODULE}; (Get-AudioDevice -PlaybackDevice).Name"
    _PS_GET_DEVICE_LIST = f"{_PS_IMPORT_MODULE}; Get-AudioDevice -List"
    
    def __init__(self, vb_cable_name: str = "CABLE Input (VB-Audio Virtual Cable)", 
                 auto_switch: bool = True):
        """
        Initialize VB Cable switcher.
        
        Args:
            vb_cable_name: Exact name of VB Cable playback device
            auto_switch: Whether to automatically switch to VB Cable on init
        """
        self.vb_cable_name = vb_cable_name
        self.original_device: Optional[str] = None
        self.auto_switch = auto_switch
        self._powershell_available = self._check_powershell_available()
        
        if auto_switch and self._powershell_available:
            self._ensure_powershell_module()
            self.switch_to_vb_cable()
    
    def _run_powershell_command(self, command: str, timeout: int = 5) -> Optional[str]:
        """Execute a PowerShell command and return stdout on success."""
        full_command = f'powershell -NoProfile -Command "{command}"'
        try:
            result = subprocess.run(
                full_command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except subprocess.TimeoutExpired:
            pass
        except Exception:
            pass
        return None
    
    def _check_powershell_available(self) -> bool:
        """Check if PowerShell is available on the system."""
        try:
            subprocess.run(
                ['powershell', '-NoProfile', '-Command', 'exit 0'],
                capture_output=True,
                timeout=POWERSHELL_CHECK_TIMEOUT_SEC
            )
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
    
    def _ensure_powershell_module(self) -> None:
        """Ensure AudioDeviceCmdlets module is installed."""
        check_result = self._run_powershell_command(
            "Get-Module -ListAvailable -Name AudioDeviceCmdlets",
            timeout=POWERSHELL_MODULE_CHECK_TIMEOUT_SEC
        )
        
        if check_result:
            return  # Module already installed
        
        _logger.info("Installing AudioDeviceCmdlets PowerShell module (one-time setup)...")
        install_cmd = "Install-Module -Name AudioDeviceCmdlets -Scope CurrentUser -Force -AllowClobber"
        
        try:
            result = subprocess.run(
                f'powershell -NoProfile -Command "{install_cmd}"',
                shell=True,
                capture_output=True,
                text=True,
                timeout=POWERSHELL_MODULE_INSTALL_TIMEOUT_SEC
            )
            if result.returncode != 0:
                _logger.warning(f"Could not install AudioDeviceCmdlets: {result.stderr}")
        except subprocess.TimeoutExpired:
            _logger.warning("PowerShell module installation timed out")
        except Exception as e:
            _logger.warning(f"Could not install PowerShell module: {e}")
    
    def get_current_default_device(self) -> Optional[str]:
        """Get current default playback device name."""
        if not self._powershell_available:
            return None
        
        commands = [
            f"{self._PS_IMPORT_MODULE}; (Get-AudioDevice -PlaybackDevice).Name",
            f"{self._PS_IMPORT_MODULE}; (Get-AudioDevice -List | Where-Object {{$_.Type -eq 'Playback' -and $_.Default -eq $true}}).Name",
        ]
        
        for cmd in commands:
            result = self._run_powershell_command(cmd)
            if result:
                return result
        
        return None
    
    def find_vb_cable_device(self) -> Optional[str]:
        """Find VB Cable device name using prioritized search patterns."""
        if not self._powershell_available:
            return None
        
        search_patterns = [
            ("$_.Name -eq 'CABLE Input (VB-Audio Virtual Cable)'", False),
            ("$_.Name -like 'CABLE Input*' -and $_.Name -like '*VB-Audio*'", False),
            ("$_.Name -like '*CABLE Input*'", True),
        ]
        
        for pattern, warn_on_match in search_patterns:
            cmd = f"{self._PS_GET_DEVICE_LIST} | Where-Object {{{pattern}}} | Select-Object -First 1 -ExpandProperty Name"
            result = self._run_powershell_command(cmd)
            if result:
                if warn_on_match:
                    _logger.warning(f"Found CABLE device but not exact match: {result}")
                return result
        
        return None
    
    def get_device_index(self, device_name: str) -> Optional[int]:
        """Get device index by name."""
        if not self._powershell_available:
            return None
        
        escaped_name = device_name.replace("'", "''")
        cmd = f"{self._PS_GET_DEVICE_LIST} | Where-Object {{$_.Name -eq '{escaped_name}'}} | Select-Object -ExpandProperty Index"
        result = self._run_powershell_command(cmd)
        
        if result:
            try:
                return int(result)
            except ValueError:
                _logger.warning(f"Could not parse device index: {result}")
        return None
    
    def _switch_audio_device(self, device_name: str, verify_contains: Optional[str] = None) -> bool:
        """Switch Windows default playback to specified device."""
        device_index = self.get_device_index(device_name)
        
        if device_index is not None:
            cmd = f"{self._PS_IMPORT_MODULE}; Set-AudioDevice -Index {device_index}"
        else:
            escaped_name = device_name.replace("'", "''")
            cmd = f"{self._PS_IMPORT_MODULE}; Set-AudioDevice -Name '{escaped_name}'"
        
        try:
            result = subprocess.run(
                f'powershell -NoProfile -Command "{cmd}"',
                shell=True,
                capture_output=True,
                text=True,
                timeout=POWERSHELL_DEFAULT_TIMEOUT_SEC
            )
            
            if result.returncode == 0:
                time.sleep(DEVICE_SWITCH_SETTLE_TIME_SEC)
                
                if verify_contains:
                    new_device = self.get_current_default_device()
                    if new_device and verify_contains.upper() in new_device.upper():
                        return True
                    _logger.warning(f"Device switch may have failed. Current device: {new_device}")
                    return False
                return True
            else:
                error_msg = result.stderr.strip() if result.stderr else result.stdout.strip()
                _logger.error(MSG_DEVICE_SWITCH_ERROR.format(error_msg))
                return False
                
        except subprocess.TimeoutExpired:
            _logger.error("PowerShell command timed out")
            return False
        except Exception as e:
            _logger.error(MSG_DEVICE_SWITCH_ERROR.format(e))
            return False
    
    def switch_to_vb_cable(self) -> bool:
        """Switch default playback device to VB Cable."""
        if not self._powershell_available:
            _logger.warning("PowerShell not available - cannot switch audio device")
            return False
        
        if self.original_device is None:
            self.original_device = self.get_current_default_device()
        
        current_device = self.get_current_default_device()
        if current_device:
            if current_device == self.vb_cable_name:
                _logger.info(f"VB Cable already set as default device: {current_device}")
                return True
        
        if self.get_device_index(self.vb_cable_name) is None:
            _logger.info(f"Device '{self.vb_cable_name}' not found, searching for alternatives...")
            found_device = self.find_vb_cable_device()
            if found_device:
                self.vb_cable_name = found_device
                _logger.info(f"Using found device: {self.vb_cable_name}")
            else:
                _logger.error("No VB Cable device found")
                return False
        
        _logger.info(f"Switching default playback device to: {self.vb_cable_name}")
        
        success = self._switch_audio_device(self.vb_cable_name, verify_contains="CABLE")
        if success:
            _logger.info(f"Successfully switched to VB Cable: {self.vb_cable_name}")
        else:
            _logger.warning("Make sure VB Cable is installed and AudioDeviceCmdlets module is available")
        return success
    
    def restore_original_device(self) -> bool:
        """Restore original default playback device."""
        if not self._powershell_available or self.original_device is None:
            return False
        
        current_device = self.get_current_default_device()
        if current_device == self.original_device:
            return True
        
        print(f"Restoring default playback device to: {self.original_device}")
        
        success = self._switch_audio_device(self.original_device)
        if success:
            _logger.info(f"Successfully restored original device: {self.original_device}")
        return success


# Alias for backwards compatibility
VB_CableSwitcher = VBCableSwitcher
