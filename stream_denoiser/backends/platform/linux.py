"""
Linux Platform Audio Utilities

Linux-specific audio functionality:
- PulseAudio/PipeWire device discovery via pulsectl (preferred)
- PortAudio device mapping for actual audio streaming
- ALSA device handling (fallback)

This module is EXCLUDED from Windows builds via PyInstaller spec.
"""
from typing import Optional, List, Tuple, Dict, Any
from dataclasses import dataclass

from ...logging_config import get_logger

_logger = get_logger(__name__)

# Try to import pulsectl for PulseAudio/PipeWire device discovery
try:
    import pulsectl
    USE_PULSECTL = True
except ImportError:
    USE_PULSECTL = False
    _logger.debug("pulsectl not available - using PortAudio-only device discovery")


@dataclass
class PulseAudioSource:
    """Represents a PulseAudio/PipeWire source (input device)."""
    index: int
    name: str  # Internal name (e.g., "alsa_output.pci-0000_00_1f.3.analog-stereo.monitor")
    description: str  # Human-readable (e.g., "Monitor of Built-in Audio Analog Stereo")
    is_monitor: bool
    sample_rate: int
    channels: int


@dataclass  
class PulseAudioSink:
    """Represents a PulseAudio/PipeWire sink (output device)."""
    index: int
    name: str
    description: str
    sample_rate: int
    channels: int


def list_pulseaudio_sources() -> List[PulseAudioSource]:
    """
    List all PulseAudio/PipeWire sources using pulsectl.
    
    Returns:
        List of PulseAudioSource objects
    """
    if not USE_PULSECTL:
        return []
    
    try:
        with pulsectl.Pulse('stream-denoiser-list') as pulse:
            sources = []
            for source in pulse.source_list():
                is_monitor = source.name.endswith('.monitor')
                sources.append(PulseAudioSource(
                    index=source.index,
                    name=source.name,
                    description=source.description,
                    is_monitor=is_monitor,
                    sample_rate=source.sample_spec.rate,
                    channels=source.sample_spec.channels
                ))
            return sources
    except pulsectl.PulseError as e:
        _logger.warning(f"Failed to list PulseAudio sources: {e}")
        return []


def list_pulseaudio_sinks() -> List[PulseAudioSink]:
    """
    List all PulseAudio/PipeWire sinks using pulsectl.
    
    Returns:
        List of PulseAudioSink objects
    """
    if not USE_PULSECTL:
        return []
    
    try:
        with pulsectl.Pulse('stream-denoiser-list') as pulse:
            sinks = []
            for sink in pulse.sink_list():
                sinks.append(PulseAudioSink(
                    index=sink.index,
                    name=sink.name,
                    description=sink.description,
                    sample_rate=sink.sample_spec.rate,
                    channels=sink.sample_spec.channels
                ))
            return sinks
    except pulsectl.PulseError as e:
        _logger.warning(f"Failed to list PulseAudio sinks: {e}")
        return []


def find_monitor_source_pulsectl() -> Optional[PulseAudioSource]:
    """
    Find the best monitor source for system audio capture using pulsectl.
    
    Priority:
    1. Monitor of the default sink
    2. Any monitor source with "built-in" or "analog" in name
    3. First available monitor source
    
    Returns:
        PulseAudioSource for the best monitor, or None
    """
    if not USE_PULSECTL:
        return None
    
    try:
        with pulsectl.Pulse('stream-denoiser-find') as pulse:
            # Get default sink to find its monitor
            server_info = pulse.server_info()
            default_sink_name = server_info.default_sink_name
            
            sources = pulse.source_list()
            monitor_sources = [s for s in sources if s.name.endswith('.monitor')]
            
            if not monitor_sources:
                _logger.warning("No monitor sources found in PulseAudio")
                return None
            
            # Priority 1: Monitor of default sink
            default_monitor_name = f"{default_sink_name}.monitor"
            for source in monitor_sources:
                if source.name == default_monitor_name:
                    _logger.info(f"Found default sink monitor: {source.description}")
                    return PulseAudioSource(
                        index=source.index,
                        name=source.name,
                        description=source.description,
                        is_monitor=True,
                        sample_rate=source.sample_spec.rate,
                        channels=source.sample_spec.channels
                    )
            
            # Priority 2: Built-in or analog monitor
            for source in monitor_sources:
                name_lower = source.name.lower()
                if 'built-in' in name_lower or 'analog' in name_lower or 'alsa_output' in name_lower:
                    _logger.info(f"Found built-in monitor: {source.description}")
                    return PulseAudioSource(
                        index=source.index,
                        name=source.name,
                        description=source.description,
                        is_monitor=True,
                        sample_rate=source.sample_spec.rate,
                        channels=source.sample_spec.channels
                    )
            
            # Priority 3: First available monitor
            source = monitor_sources[0]
            _logger.info(f"Using first available monitor: {source.description}")
            return PulseAudioSource(
                index=source.index,
                name=source.name,
                description=source.description,
                is_monitor=True,
                sample_rate=source.sample_spec.rate,
                channels=source.sample_spec.channels
            )
            
    except pulsectl.PulseError as e:
        _logger.warning(f"Failed to find monitor source: {e}")
        return None


def map_pulse_to_portaudio(pulse_source: PulseAudioSource, 
                           portaudio_devices: List[Dict[str, Any]]) -> Optional[int]:
    """
    Map a PulseAudio source to the best matching PortAudio device ID.
    
    Since PortAudio may not see PulseAudio devices directly, we try to find
    a matching device by name similarity. Strongly prefers ALSA devices over
    JACK to avoid memory corruption issues in PortAudio's JACK backend.
    
    Args:
        pulse_source: PulseAudio source to map
        portaudio_devices: List of devices from sounddevice.query_devices()
        
    Returns:
        PortAudio device ID, or None if no match found
    """
    if not pulse_source:
        return None
    
    try:
        import sounddevice as sd
    except ImportError:
        return None
    
    # Extract keywords from PulseAudio source for matching
    pulse_name_lower = pulse_source.name.lower()
    pulse_desc_lower = pulse_source.description.lower()
    
    # Separate by host API (prefer PulseAudio > ALSA > JACK)
    pulse_matches = []
    alsa_matches = []
    jack_matches = []
    
    for i, device in enumerate(portaudio_devices):
        if device.get('max_input_channels', 0) == 0:
            continue
        
        device_name = device.get('name', '')
        device_name_lower = device_name.lower()
        host_api = sd.query_hostapis(device['hostapi'])['name']
        is_pulse = 'pulse' in host_api.lower()
        is_alsa = 'alsa' in host_api.lower() and not is_pulse
        is_jack = 'jack' in host_api.lower()
        
        score = 0
        
        # Exact match for PulseAudio monitor (best case)
        if pulse_source.name in device_name or device_name in pulse_source.name:
            score += 100  # Exact match
        
        # Check for partial matches
        if 'monitor' in device_name_lower and 'monitor' in pulse_desc_lower:
            score += 50
        if 'analog' in pulse_name_lower and 'analog' in device_name_lower:
            score += 10
        if 'built-in' in pulse_desc_lower and 'built-in' in device_name_lower:
            score += 5
        
        if score > 0:
            if is_pulse:
                pulse_matches.append((score, i, device))
            elif is_alsa:
                alsa_matches.append((score, i, device))
            elif is_jack:
                jack_matches.append((score, i, device))
    
    # Prefer PulseAudio devices (direct access to PipeWire sources)
    if pulse_matches:
        pulse_matches.sort(key=lambda x: x[0], reverse=True)
        score, best_idx, best_device = pulse_matches[0]
        _logger.info(f"Mapped PulseAudio '{pulse_source.description}' -> PortAudio PulseAudio device {best_idx}")
        return best_idx
    
    # Fall back to ALSA if no PulseAudio match
    if alsa_matches:
        alsa_matches.sort(key=lambda x: x[0], reverse=True)
        score, best_idx, best_device = alsa_matches[0]
        _logger.info(f"Mapped PulseAudio '{pulse_source.description}' -> PortAudio ALSA device {best_idx}")
        return best_idx
    
    # Fall back to JACK if no ALSA match (with warning)
    if jack_matches:
        jack_matches.sort(key=lambda x: x[0], reverse=True)
        score, best_idx, best_device = jack_matches[0]
        _logger.warning(f"Using JACK device (may be unstable): {best_device.get('name')} (ID: {best_idx})")
        return best_idx
    
    # No match found - look for any PulseAudio device with 'monitor' in name
    for i, device in enumerate(portaudio_devices):
        host_api = sd.query_hostapis(device['hostapi'])['name']
        if 'pulse' in host_api.lower() and 'monitor' in device.get('name', '').lower():
            if device.get('max_input_channels', 0) > 0:
                _logger.info(f"Using PulseAudio monitor: {device.get('name')} (ID: {i})")
                return i
    
    _logger.warning(f"Could not map PulseAudio source '{pulse_source.description}' to PortAudio device")
    return None


def find_loopback_hybrid(device_id: Optional[int] = None) -> Optional[int]:
    """
    Hybrid loopback device detection for Linux.
    
    Uses pulsectl to find monitor sources, then maps to PortAudio device.
    Falls back to PortAudio-only detection if pulsectl unavailable.
    
    Args:
        device_id: User-specified device ID (returned as-is if provided)
        
    Returns:
        PortAudio device ID for loopback capture
    """
    # If user specified a device, return it
    if device_id is not None:
        return device_id
    
    # Try pulsectl first
    if USE_PULSECTL:
        monitor = find_monitor_source_pulsectl()
        if monitor:
            # Import sounddevice here to avoid circular imports
            try:
                import sounddevice as sd
                portaudio_devices = sd.query_devices()
                mapped_id = map_pulse_to_portaudio(monitor, portaudio_devices)
                if mapped_id is not None:
                    return mapped_id
                
                # If mapping failed but we found a monitor, log helpful info
                _logger.info(f"PulseAudio monitor found: {monitor.description}")
                _logger.info(f"  Name: {monitor.name}")
                _logger.info(f"  Index: {monitor.index}, Rate: {monitor.sample_rate}Hz")
            except ImportError:
                pass
    
    # Fall back to PortAudio-only detection
    return None


def list_pulseaudio_sources_formatted() -> str:
    """
    Get formatted string of PulseAudio sources for CLI display.
    
    Returns:
        Formatted string for display, or empty string if unavailable
    """
    sources = list_pulseaudio_sources()
    if not sources:
        return ""
    
    lines = []
    for source in sources:
        monitor_marker = " [MONITOR]" if source.is_monitor else ""
        lines.append(f"Index {source.index}: {source.description}{monitor_marker}")
        lines.append(f"    Name: {source.name}")
        lines.append(f"    Sample rate: {source.sample_rate}Hz, Channels: {source.channels}")
        lines.append("")
    
    return "\n".join(lines)


def find_monitor_sources(devices: List[Dict[str, Any]]) -> List[Tuple[int, Dict[str, Any]]]:
    """
    Find PulseAudio/PipeWire monitor sources for loopback capture.
    
    Monitor sources capture audio playing on output devices (equivalent to
    WASAPI loopback on Windows).
    
    Args:
        devices: List of audio devices from sounddevice.query_devices()
        
    Returns:
        List of (device_id, device_info) tuples for monitor sources
    """
    monitor_devices = []
    
    for i, device in enumerate(devices):
        device_name = device.get('name', '')
        device_name_lower = device_name.lower()
        
        # Must be an input device to capture from
        if device.get('max_input_channels', 0) == 0:
            continue
        
        # Check for monitor source patterns
        # PulseAudio/PipeWire: "Monitor of X", "X.monitor"
        is_monitor = (
            'monitor of' in device_name_lower or
            '.monitor' in device_name_lower or
            device_name_lower.endswith(' monitor')
        )
        
        if is_monitor:
            monitor_devices.append((i, device))
            _logger.debug(f"Found monitor source: {device_name} (ID: {i})")
    
    return monitor_devices


def find_loopback_device_linux(devices: List[Dict[str, Any]], 
                                preferred_output: Optional[str] = None) -> Optional[int]:
    """
    Find the best loopback device for audio capture on Linux.
    
    Priority:
    1. Monitor of the preferred output device (if specified)
    2. Monitor of "Built-in" or default audio
    3. Any available monitor source
    4. Default input device (fallback)
    
    Args:
        devices: List of audio devices from sounddevice.query_devices()
        preferred_output: Name of preferred output device to find monitor for
        
    Returns:
        Device ID for loopback capture, or None if not found
    """
    monitors = find_monitor_sources(devices)
    
    if not monitors:
        _logger.warning("No monitor sources found. Audio capture may require PipeWire/PulseAudio.")
        return None
    
    # If preferred output specified, find its monitor
    if preferred_output:
        preferred_lower = preferred_output.lower()
        for device_id, device in monitors:
            device_name_lower = device['name'].lower()
            if preferred_lower in device_name_lower:
                _logger.info(f"Found monitor for preferred output: {device['name']} (ID: {device_id})")
                return device_id
    
    # Look for built-in audio monitor
    for device_id, device in monitors:
        device_name_lower = device['name'].lower()
        if 'built-in' in device_name_lower or 'internal' in device_name_lower:
            _logger.info(f"Found built-in audio monitor: {device['name']} (ID: {device_id})")
            return device_id
    
    # Return first available monitor
    if monitors:
        device_id, device = monitors[0]
        _logger.info(f"Using first available monitor: {device['name']} (ID: {device_id})")
        return device_id
    
    return None


def get_linux_output_devices(devices: List[Dict[str, Any]]) -> List[Tuple[int, Dict[str, Any]]]:
    """
    Get list of output devices suitable for playback on Linux.
    
    Filters out virtual devices and monitors, prioritizing real hardware.
    
    Args:
        devices: List of audio devices from sounddevice.query_devices()
        
    Returns:
        List of (device_id, device_info) tuples for output devices
    """
    output_devices = []
    
    for i, device in enumerate(devices):
        device_name = device.get('name', '')
        device_name_lower = device_name.lower()
        
        # Must support output
        if device.get('max_output_channels', 0) == 0:
            continue
        
        # Skip monitor sources (they're for input capture)
        if 'monitor' in device_name_lower:
            continue
        
        # Skip null sinks (virtual devices for routing)
        if 'null' in device_name_lower:
            continue
        
        output_devices.append((i, device))
    
    return output_devices


class LinuxAudioRouter:
    """
    Automatic audio routing for Linux using PulseAudio/PipeWire.
    
    Similar to VB Cable on Windows, this class:
    1. Creates a null sink (virtual audio device)
    2. Sets it as the default sink (apps route audio there)
    3. Provides the null sink's monitor for capture
    4. Restores original routing on exit
    """
    
    SINK_NAME = "Denoiser_Capture"
    SINK_DESCRIPTION = "Denoiser Audio Capture"
    
    def __init__(self, auto_switch: bool = True):
        """
        Initialize the Linux audio router.
        
        Args:
            auto_switch: If True, automatically switch default sink on init
        """
        self._module_id: Optional[int] = None
        self._original_default_sink: Optional[str] = None
        self._sink_name: Optional[str] = None
        self._monitor_source: Optional[str] = None
        self._auto_switch = auto_switch
        
        if auto_switch:
            self._setup_routing()
    
    def _setup_routing(self) -> bool:
        """Set up null sink and switch default sink."""
        if not USE_PULSECTL:
            _logger.warning("pulsectl not available - cannot set up automatic routing")
            return False
        
        try:
            with pulsectl.Pulse('denoiser-router') as pulse:
                # Get current default sink
                server_info = pulse.server_info()
                current_default = server_info.default_sink_name
                
                # Check if our sink already exists
                existing_null_sink = None
                for sink in pulse.sink_list():
                    if sink.name == self.SINK_NAME:
                        existing_null_sink = sink
                        break
                
                # If current default IS our null sink, we need to find the real hardware sink
                if current_default == self.SINK_NAME:
                    _logger.warning("Current default is our null sink (from previous crash?)")
                    # Find a real hardware sink to restore to
                    for sink in pulse.sink_list():
                        if sink.name != self.SINK_NAME and 'null' not in sink.name.lower():
                            self._original_default_sink = sink.name
                            _logger.info(f"Found real hardware sink: {sink.name}")
                            break
                    if not self._original_default_sink:
                        _logger.warning("Could not find a hardware sink to restore to")
                else:
                    self._original_default_sink = current_default
                    _logger.info(f"Original default sink: {self._original_default_sink}")
                
                # Reuse existing null sink if present
                if existing_null_sink:
                    _logger.info(f"Reusing existing null sink: {self.SINK_NAME}")
                    self._sink_name = existing_null_sink.name
                    self._monitor_source = f"{existing_null_sink.name}.monitor"
                    pulse.sink_default_set(existing_null_sink)
                    _logger.info(f"Set default sink to: {self.SINK_NAME}")
                    return True
                
                # Create null sink using pactl (pulsectl doesn't support module loading directly)
                import subprocess
                result = subprocess.run(
                    ['pactl', 'load-module', 'module-null-sink',
                     f'sink_name={self.SINK_NAME}',
                     f'sink_properties=device.description="{self.SINK_DESCRIPTION}"'],
                    capture_output=True, text=True
                )
                
                if result.returncode != 0:
                    _logger.error(f"Failed to create null sink: {result.stderr}")
                    return False
                
                self._module_id = int(result.stdout.strip())
                self._sink_name = self.SINK_NAME
                self._monitor_source = f"{self.SINK_NAME}.monitor"
                _logger.info(f"Created null sink: {self.SINK_NAME} (module ID: {self._module_id})")
                
                # Set as default sink
                # Need to refresh sink list
                for sink in pulse.sink_list():
                    if sink.name == self.SINK_NAME:
                        pulse.sink_default_set(sink)
                        _logger.info(f"Set default sink to: {self.SINK_NAME}")
                        break
                
                return True
                
        except pulsectl.PulseError as e:
            _logger.error(f"PulseAudio error during routing setup: {e}")
            return False
        except Exception as e:
            _logger.error(f"Error setting up routing: {e}")
            return False
    
    def get_monitor_source_name(self) -> Optional[str]:
        """Get the name of the null sink's monitor source for capture."""
        return self._monitor_source
    
    def get_monitor_device_id(self) -> Optional[int]:
        """
        Get the PortAudio device ID for the null sink's monitor.
        
        Returns:
            PortAudio device ID, or None if not found
        """
        if not self._monitor_source:
            return None
        
        try:
            import sounddevice as sd
            import time
            
            # Give PulseAudio time to register the new sink with PortAudio
            time.sleep(0.5)
            
            # Force PortAudio to refresh device list
            try:
                sd._terminate()
                sd._initialize()
            except Exception:
                pass  # Ignore errors, just try to refresh
            
            devices = sd.query_devices()
            
            # Look for our null sink monitor
            for i, device in enumerate(devices):
                device_name = device.get('name', '')
                if self._sink_name and self._sink_name.lower() in device_name.lower():
                    if device.get('max_input_channels', 0) > 0:
                        _logger.info(f"Found null sink monitor: {device_name} (ID: {i})")
                        return i
            
            # Also try matching by 'denoiser' in name
            for i, device in enumerate(devices):
                device_name = device.get('name', '').lower()
                if 'denoiser' in device_name and device.get('max_input_channels', 0) > 0:
                    _logger.info(f"Found Denoiser monitor: {device.get('name')} (ID: {i})")
                    return i
            
            _logger.warning(f"Could not find PortAudio device for monitor: {self._monitor_source}")
            return None
        except ImportError:
            return None
    
    def restore_original_sink(self) -> bool:
        """Restore the original default sink and clean up null sink."""
        success = True
        
        if not USE_PULSECTL:
            return True
        
        try:
            with pulsectl.Pulse('denoiser-router-cleanup') as pulse:
                # Restore original default sink
                if self._original_default_sink:
                    try:
                        for sink in pulse.sink_list():
                            if sink.name == self._original_default_sink:
                                pulse.sink_default_set(sink)
                                _logger.info(f"Restored default sink to: {self._original_default_sink}")
                                break
                    except pulsectl.PulseError as e:
                        _logger.warning(f"Could not restore original sink: {e}")
                        success = False
                
                # Unload null sink module
                if self._module_id is not None:
                    import subprocess
                    result = subprocess.run(
                        ['pactl', 'unload-module', str(self._module_id)],
                        capture_output=True, text=True
                    )
                    if result.returncode == 0:
                        _logger.info(f"Unloaded null sink module: {self._module_id}")
                    else:
                        _logger.warning(f"Could not unload module: {result.stderr}")
                        success = False
                    self._module_id = None
                
        except pulsectl.PulseError as e:
            _logger.error(f"PulseAudio error during cleanup: {e}")
            success = False
        
        return success
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - restore original routing."""
        self.restore_original_sink()
        return False
    
    @staticmethod
    def get_routing_instructions() -> str:
        """Get user-friendly instructions for manual audio routing."""
        return """
Linux Audio Routing (Automatic):
================================

The denoiser automatically creates a virtual audio sink and routes system audio
through it. When you stop the denoiser, original routing is restored.

If automatic routing doesn't work, you can set it up manually:

Option 1: Use PipeWire/PulseAudio GUI tools
  - Install 'pavucontrol' or 'helvum'
  - Redirect application audio to "Denoiser Audio Capture"
  - The denoiser captures from this sink's monitor

Option 2: Manual command line setup
  # Create null sink
  pactl load-module module-null-sink sink_name=Denoiser_Capture sink_properties=device.description="Denoiser_Capture"
  
  # Set as default (apps will use it automatically)
  pactl set-default-sink Denoiser_Capture
  
  # Run denoiser - it will capture from the null sink's monitor
  python -m stream_denoiser
"""

