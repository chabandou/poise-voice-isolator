"""
Audio Device Utilities

Functions for discovering and managing audio devices.
Supports both Windows (WASAPI loopback) and Linux (PulseAudio/ALSA monitors).
"""
from typing import Optional, List, Dict, Any, Tuple

from .backend_detection import (
    USE_SOUNDDEVICE, USE_PYAUDIO, USE_PYAUDIOWPATCH,
    sd, pyaudio
)
from .platform_utils import is_windows, is_linux, is_acceptable_host_api
from .logging_config import get_logger

_logger = get_logger(__name__)


def list_audio_devices() -> List[Dict[str, Any]]:
    """List all available audio devices."""
    if USE_SOUNDDEVICE:
        devices = sd.query_devices()
        return devices
    elif USE_PYAUDIO:
        p = pyaudio.PyAudio()
        devices = []
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            devices.append({
                'name': info['name'],
                'max_input_channels': info['maxInputChannels'],
                'max_output_channels': info['maxOutputChannels'],
                'default_samplerate': info['defaultSampleRate'],
                'hostapi': p.get_host_api_info_by_index(info['hostApi'])['name']
            })
        p.terminate()
        return devices
    else:
        return []


def _validate_device_id(device_id: int, devices: List[Dict[str, Any]]) -> None:
    """
    Validate that device ID is within valid range.
    
    Args:
        device_id: Device ID to validate
        devices: List of available audio devices
        
    Raises:
        ValueError: If device ID is out of range
    """
    if device_id >= len(devices):
        raise ValueError(f"Device ID {device_id} is out of range. Available devices: 0-{len(devices)-1}")


def _find_wasapi_loopback_pyaudio() -> Optional[int]:
    """
    Find WASAPI loopback device using PyAudioWPatch.
    Prioritizes VB Cable Output device.
    Only searches WASAPI devices.
    
    Returns:
        Device index if found, None otherwise
    """
    if not USE_PYAUDIOWPATCH:
        return None
    
    p = pyaudio.PyAudio()
    try:
        # Get WASAPI Host API index
        wasapi_host_api_index = None
        for api_idx in range(p.get_host_api_count()):
            api_info = p.get_host_api_info_by_index(api_idx)
            if 'WASAPI' in api_info['name'].upper():
                wasapi_host_api_index = api_idx
                break
        
        if wasapi_host_api_index is None:
            _logger.warning("WASAPI Host API not found")
            return None
        
        # First, try to find VB Cable Output specifically (WASAPI only)
        device_count = p.get_device_count()
        for i in range(device_count):
            try:
                device_info = p.get_device_info_by_index(i)
                # Filter to WASAPI devices only
                if device_info['hostApi'] != wasapi_host_api_index:
                    continue
                    
                device_name = device_info['name']
                # Check if it's VB Cable Output (loopback device)
                if device_info['maxInputChannels'] > 0:
                    if 'CABLE Output' in device_name and 'VB-Audio' in device_name:
                        _logger.info(f"Found VB Cable loopback device: {device_name} (Index: {i})")
                        return i
                    elif 'CABLE Output' in device_name:
                        _logger.info(f"Found CABLE Output loopback device: {device_name} (Index: {i})")
                        return i
            except Exception:
                continue
        
        # Fallback to default WASAPI loopback
        loopback_device = p.get_default_wasapi_loopback()
        if loopback_device:
            _logger.info(f"Found WASAPI loopback device: {loopback_device['name']} (Index: {loopback_device['index']})")
            return loopback_device['index']
        else:
            _logger.warning("No default WASAPI loopback device found")
            return None
    finally:
        p.terminate()


def _find_loopback_devices_sounddevice() -> List[Tuple[int, Dict[str, Any]]]:
    """
    Find loopback devices using sounddevice.
    
    On Windows: Prioritizes VB Cable Output, searches WASAPI devices.
    On Linux: Searches for monitor sources (PulseAudio/PipeWire).
    
    Returns:
        List of tuples (device_id, device_info) for loopback devices
    """
    if not USE_SOUNDDEVICE:
        return []
    
    devices = sd.query_devices()
    priority_devices = []  # VB Cable on Windows, or preferred monitors on Linux
    loopback_devices = []
    
    for i, device in enumerate(devices):
        device_name = device['name']
        device_name_lower = device_name.lower()
        host_api = sd.query_hostapis(device['hostapi'])['name']
        
        # Platform-specific host API filtering
        if is_windows():
            # On Windows, only use WASAPI devices
            if 'wasapi' not in host_api.lower():
                continue
        elif is_linux():
            # On Linux, accept ALSA, PulseAudio, JACK, PipeWire
            if not is_acceptable_host_api(host_api):
                continue
        
        # Must be an input device to capture from
        if device['max_input_channels'] == 0:
            continue
        
        # Windows: VB Cable detection
        if is_windows():
            if 'cable output' in device_name_lower and 'vb-audio' in device_name_lower:
                priority_devices.append((i, device))
                continue
            elif 'cable output' in device_name_lower:
                priority_devices.append((i, device))
                continue
        
        # Linux: Monitor source detection (PulseAudio/PipeWire)
        if is_linux():
            if 'monitor of' in device_name_lower or '.monitor' in device_name_lower:
                # Prioritize built-in audio monitors
                if 'built-in' in device_name_lower or 'internal' in device_name_lower:
                    priority_devices.append((i, device))
                else:
                    loopback_devices.append((i, device))
                continue
        
        # Generic loopback detection (both platforms)
        if 'loopback' in device_name_lower or 'stereo mix' in device_name_lower:
            loopback_devices.append((i, device))
        elif any(kw in device_name_lower for kw in ['speakers', 'headphones', 'output', 'playback']):
            if 'microphone' not in device_name_lower and 'mic' not in device_name_lower:
                loopback_devices.append((i, device))
    
    # Return priority devices first, then other loopback devices
    return priority_devices + loopback_devices


def find_loopback_device(device_id: Optional[int] = None) -> Optional[int]:
    """
    Find loopback device for system audio capture.
    
    On Windows: Uses WASAPI loopback via PyAudioWPatch or VB Cable.
    On Linux: Uses pulsectl to find PulseAudio/PipeWire monitor sources,
              then maps to PortAudio device for streaming.
    
    Args:
        device_id: Optional specific device ID to use
        
    Returns:
        Device ID if found, None if not found (or device_id if provided and valid)
        
    Raises:
        RuntimeError: If required libraries are not available
        ValueError: If device_id is out of range
    """
    # On Linux, try hybrid pulsectl approach first
    if is_linux():
        try:
            from .backends.platform.linux import find_loopback_hybrid
            hybrid_result = find_loopback_hybrid(device_id)
            if hybrid_result is not None:
                return hybrid_result
            # If hybrid returns None but device_id was specified, continue to validation below
        except ImportError:
            _logger.debug("Linux platform module not available, using fallback")
    
    # Try PyAudioWPatch first (Windows preferred method)
    wasapi_device = _find_wasapi_loopback_pyaudio()
    if wasapi_device is not None:
        if device_id is not None and device_id != wasapi_device:
            # User specified a different device, validate it
            if USE_SOUNDDEVICE:
                devices = sd.query_devices()
                _validate_device_id(device_id, devices)
                return device_id
        return wasapi_device if device_id is None else device_id
    
    # Fallback to sounddevice
    if not USE_SOUNDDEVICE:
        raise RuntimeError("Loopback device detection requires sounddevice or pyaudiowpatch")
    
    devices = sd.query_devices()
    
    # If specific device ID provided, validate and return it
    if device_id is not None:
        _validate_device_id(device_id, devices)
        return device_id
    
    # Look for loopback devices (prioritizes VB Cable Output)
    loopback_devices = _find_loopback_devices_sounddevice()
    
    if loopback_devices:
        device_id, device = loopback_devices[0]
        device_name = device['name']

        if 'CABLE Output' in device_name:
            _logger.info(f"Found VB Cable loopback device: {device_name} (ID: {device_id})")
        else:
            _logger.info(f"Found loopback device: {device_name} (ID: {device_id})")
        return device_id
    
    _logger.warning("No loopback device found. Using default input device.")
    return sd.default.device[0]


def get_output_device_id(output_device: Optional[int], devices: List[Dict[str, Any]], 
                         input_host_api: Optional[str] = None) -> int:
    """
    Get output device ID.
    
    On Windows: Only searches WASAPI devices.
    On Linux: Searches ALSA, PulseAudio, JACK, PipeWire devices.
              Prioritizes matching the input device's host API to avoid crashes.
    
    Args:
        output_device: User-specified output device ID or None
        devices: List of available audio devices
        input_host_api: Host API name of the input device (to match for compatibility)
    
    Returns:
        Output device ID
    
    Raises:
        ValueError: If device is invalid or unavailable
    """
    if not USE_SOUNDDEVICE:
        raise RuntimeError("Output device selection requires sounddevice")
    
    if output_device is not None:
        if output_device >= len(devices):
            raise ValueError(f"Output device ID {output_device} is out of range. Available devices: 0-{len(devices)-1}")
        device_info = devices[output_device]
        
        # Platform-specific host API check
        host_api = sd.query_hostapis(device_info['hostapi'])['name']
        if not is_acceptable_host_api(host_api):
            if is_windows():
                raise ValueError(f"Device {output_device} ({device_info['name']}) is not a WASAPI device. Please select a WASAPI device.")
            else:
                raise ValueError(f"Device {output_device} ({device_info['name']}) uses unsupported host API: {host_api}")
        
        if device_info['max_output_channels'] == 0:
            raise ValueError(f"Device {output_device} ({device_info['name']}) does not support output")
        return output_device
    else:
        # Filter to acceptable devices for current platform
        acceptable_devices = []
        matching_api_devices = []  # Devices matching input host API
        
        for i, device in enumerate(devices):
            host_api = sd.query_hostapis(device['hostapi'])['name']
            if not is_acceptable_host_api(host_api):
                continue
            if device['max_output_channels'] > 0:
                # Skip monitor sources (they're for input)
                device_name_lower = device['name'].lower()
                if 'monitor' in device_name_lower:
                    continue
                acceptable_devices.append((i, device, host_api))
                
                # Track devices matching the input host API
                if input_host_api and input_host_api.lower() in host_api.lower():
                    matching_api_devices.append((i, device, host_api))
        
        if not acceptable_devices:
            platform_name = "WASAPI" if is_windows() else "ALSA/PulseAudio/JACK"
            raise ValueError(f"No {platform_name} output-capable audio device found")
        
        # On Linux with PulseAudio, prioritize real sinks over virtual "Default Sink"
        if is_linux() and input_host_api and matching_api_devices:
            # Sort by preference: prefer devices with normal channel counts (not 32-channel virtual)
            # and prefer actual named devices over "Default Sink"
            real_sinks = []
            virtual_sinks = []
            
            for i, device, host_api in matching_api_devices:
                if device['max_output_channels'] > 0:
                    device_name = device['name']
                    channels = device['max_output_channels']
                    
                    # Skip monitors
                    if 'monitor' in device_name.lower():
                        continue
                    
                    # Categorize: real sinks have 1-8 channels, virtual may have more
                    if 'default' in device_name.lower() or channels > 8:
                        virtual_sinks.append((i, device, host_api))
                    else:
                        real_sinks.append((i, device, host_api))
            
            # Prefer real sinks
            if real_sinks:
                i, device, host_api = real_sinks[0]
                _logger.info(f"Using real output sink: {device['name']} (ID: {i}, channels: {device['max_output_channels']})")
                return i
            
            # Fall back to virtual if needed
            if virtual_sinks:
                i, device, host_api = virtual_sinks[0]
                _logger.info(f"Using virtual output sink: {device['name']} (ID: {i})")
                return i
        
        # First priority: Look for device with "headphones" in the name
        for i, device, host_api in acceptable_devices:
            device_name_lower = device['name'].lower()
            if 'headphone' in device_name_lower:
                _logger.info(f"Auto-selected headphones device: {device['name']} (ID: {i})")
                return i
        
        # Second priority: Try default output device (if it has acceptable host API)
        default_output = sd.default.device[1]
        if default_output is not None:
            if default_output < len(devices):
                device_info = devices[default_output]
                host_api = sd.query_hostapis(device_info['hostapi'])['name']
                if is_acceptable_host_api(host_api) and device_info['max_output_channels'] > 0:
                    # On Linux, warn if mismatching host API
                    if is_linux() and input_host_api and input_host_api.lower() not in host_api.lower():
                        _logger.warning(f"Default output uses different host API ({host_api}) than input ({input_host_api})")
                        _logger.warning("This may cause audio issues. Consider specifying --output-device")
                    _logger.info(f"Using default output device: {device_info['name']} (ID: {default_output})")
                    return default_output
        
        # Last resort: return first acceptable output device
        device_id, device = acceptable_devices[0]
        _logger.info(f"Using first available output device: {device['name']} (ID: {device_id})")
        return device_id


def validate_output_device(device_id: int, sample_rate: int, devices: List[Dict[str, Any]]) -> bool:
    """
    Validate that output device supports the requested configuration.
    
    Args:
        device_id: Device ID to validate
        sample_rate: Required sample rate
        devices: List of available audio devices
    
    Returns:
        True if device is valid, False otherwise
    """
    if device_id >= len(devices):
        return False
    
    device_info = devices[device_id]
    
    # Check output channels
    if device_info['max_output_channels'] == 0:
        return False
    
    return True


def print_stats(stats: Dict[str, Any], elapsed: float, buffer_info: Optional[Tuple[int, int]] = None) -> None:
    """
    Print processing statistics.
    
    Args:
        stats: Statistics dictionary from processor.get_stats()
        elapsed: Elapsed time in seconds
        buffer_info: Optional tuple (input_buffer_available, output_buffer_available) for buffer stats
    """
    if buffer_info:
        input_avail, output_avail = buffer_info
        stats_str = f"\rBuf: {input_avail}->{output_avail} | RTF: {stats['rtf']:.3f} | Avg: {stats['avg_time_ms']:.2f}ms"
    else:
        stats_str = f"\rFrames: {stats['frame_count']} | RTF: {stats['rtf']:.3f} | Avg: {stats['avg_time_ms']:.2f}ms"
    
    if 'vad_bypass_ratio' in stats:
        stats_str += f" | VAD bypass: {stats['vad_bypass_ratio']*100:.0f}%"
    
    stats_str += f" | Running: {elapsed:.1f}s"
    print(stats_str, end='', flush=True)


def print_final_stats(stats: Dict[str, Any]) -> None:
    """
    Print final processing statistics.
    
    Args:
        stats: Statistics dictionary from processor.get_stats()
    """
    print(f"\n\nProcessing complete. Processed {stats['frame_count']} frames")
    if 'vad_bypass_ratio' in stats:
        bypass_ratio = stats['vad_bypass_ratio']
        if bypass_ratio >= 1.0:
            print(f"VAD bypassed {bypass_ratio*100:.1f}% of frames (all frames bypassed)")
        elif bypass_ratio > 0:
            performance_boost = 1 / (1 - bypass_ratio)
            print(f"VAD bypassed {bypass_ratio*100:.1f}% of frames (performance boost: ~{performance_boost:.1f}x)")
        else:
            print(f"VAD bypassed {bypass_ratio*100:.1f}% of frames (no bypass)")
