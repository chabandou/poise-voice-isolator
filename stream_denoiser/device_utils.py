"""
Audio Device Utilities

Functions for discovering and managing audio devices,
including WASAPI loopback detection for system audio capture.
"""
from typing import Optional, List, Dict, Any, Tuple

from .backend_detection import (
    USE_SOUNDDEVICE, USE_PYAUDIO, USE_PYAUDIOWPATCH,
    sd, pyaudio
)
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
    Prioritizes VB Cable Output device.
    Only searches WASAPI devices.
    
    Returns:
        List of tuples (device_id, device_info) for loopback devices
    """
    if not USE_SOUNDDEVICE:
        return []
    
    devices = sd.query_devices()
    vb_cable_devices = []
    loopback_devices = []
    
    for i, device in enumerate(devices):
        device_name = device['name']
        device_name_lower = device_name.lower()
        host_api = sd.query_hostapis(device['hostapi'])['name']
        
        # Filter to WASAPI devices only
        if 'wasapi' not in host_api.lower():
            continue
        
        # First priority: VB Cable Output (loopback device)
        if device['max_input_channels'] > 0:
            if 'cable output' in device_name_lower and 'vb-audio' in device_name_lower:
                vb_cable_devices.append((i, device))
            elif 'cable output' in device_name_lower:
                vb_cable_devices.append((i, device))
        
        # Second priority: Other loopback devices
        if 'loopback' in device_name_lower or 'stereo mix' in device_name_lower:
            loopback_devices.append((i, device))
        elif device['max_input_channels'] > 0:
            if any(kw in device_name_lower for kw in ['speakers', 'headphones', 'output', 'playback']):
                if 'microphone' not in device_name_lower and 'mic' not in device_name_lower:
                    loopback_devices.append((i, device))
    
    # Return VB Cable devices first, then other loopback devices
    return vb_cable_devices + loopback_devices


def find_loopback_device(device_id: Optional[int] = None) -> Optional[int]:
    """
    Find WASAPI loopback device for system audio capture on Windows.
    Uses the system default playback device's loopback if available.
    
    Args:
        device_id: Optional specific device ID to use
        
    Returns:
        Device ID if found, None if not found (or device_id if provided and valid)
        
    Raises:
        RuntimeError: If required libraries are not available
        ValueError: If device_id is out of range
    """
    # Try PyAudioWPatch first (preferred method)
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


def get_output_device_id(output_device: Optional[int], devices: List[Dict[str, Any]]) -> int:
    """
    Get output device ID.
    Only searches WASAPI devices.
    
    Args:
        output_device: User-specified output device ID or None
        devices: List of available audio devices
    
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
        # Check if it's WASAPI
        host_api = sd.query_hostapis(device_info['hostapi'])['name']
        if 'wasapi' not in host_api.lower():
            raise ValueError(f"Device {output_device} ({device_info['name']}) is not a WASAPI device. Please select a WASAPI device.")
        if device_info['max_output_channels'] == 0:
            raise ValueError(f"Device {output_device} ({device_info['name']}) does not support output")
        return output_device
    else:
        # Filter to WASAPI devices only
        wasapi_devices = []
        for i, device in enumerate(devices):
            host_api = sd.query_hostapis(device['hostapi'])['name']
            if 'wasapi' not in host_api.lower():
                continue
            if device['max_output_channels'] > 0:
                wasapi_devices.append((i, device))
        
        if not wasapi_devices:
            raise ValueError("No WASAPI output-capable audio device found")
        
        # First priority: Look for device with "headphones" in the name
        for i, device in wasapi_devices:
            device_name_lower = device['name'].lower()
            if 'headphone' in device_name_lower:
                _logger.info(f"Auto-selected headphones device: {device['name']} (ID: {i})")
                return i
        
        # Second priority: Try default output device (if it's WASAPI)
        default_output = sd.default.device[1]
        if default_output is not None:
            if default_output < len(devices):
                device_info = devices[default_output]
                host_api = sd.query_hostapis(device_info['hostapi'])['name']
                if 'wasapi' in host_api.lower() and device_info['max_output_channels'] > 0:
                    return default_output
        
        # Last resort: return first WASAPI output device
        return wasapi_devices[0][0]


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
