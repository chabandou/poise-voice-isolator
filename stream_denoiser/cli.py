"""
Command-Line Interface for Stream Denoiser

Main entry point and argument parsing for the real-time audio denoiser.
"""
import os
import sys
import time
import argparse
from typing import Optional

import onnxruntime

from .constants import (
    DEFAULT_SAMPLE_RATE,
    DEFAULT_FRAME_SIZE,
    DEFAULT_VAD_THRESHOLD_DB,
    DEFAULT_VAD_THRESHOLD_DB,
    DEVICE_SWITCH_INIT_DELAY_SEC,
    MSG_ONNX_NOT_FOUND,
    MSG_POWERSHELL_UNAVAILABLE,
)
from .processor import DenoiserAudioProcessor, load_onnx_model
from .vb_cable import VB_CableSwitcher
from .device_utils import list_audio_devices, find_loopback_device
from .backend_detection import USE_PYAUDIOWPATCH, USE_SOUNDDEVICE
from .logging_config import get_logger

_logger = get_logger(__name__)


def process_system_audio_realtime(onnx_session: onnxruntime.InferenceSession, 
                                   input_device: Optional[int] = None, 
                                   output_device: Optional[int] = None, 
                                   enable_vad: bool = True, 
                                   vad_threshold_db: float = DEFAULT_VAD_THRESHOLD_DB, 
                                   atten_lim_db: float = -60.0,
                                   use_vb_cable: bool = True,
                                   vb_cable_name: Optional[str] = None) -> None:
    """
    Main entry point for real-time audio processing.
    Selects appropriate backend and uses unified DenoiserAudioProcessor.
    
    Args:
        onnx_session: ONNX inference session
        input_device: Input device ID (optional)
        output_device: Output device ID (optional)
        enable_vad: Enable Voice Activity Detection
        vad_threshold_db: VAD threshold in dB
        atten_lim_db: Attenuation limit in dB
        use_vb_cable: Whether to automatically switch to VB Cable as default playback device
        vb_cable_name: Custom name for VB Cable device (auto-detected if None)
    """
    # Create VB Cable switcher if enabled
    vb_cable_switcher = None
    if use_vb_cable:
        cable_name = vb_cable_name or "CABLE Input (VB-Audio Virtual Cable)"
        vb_cable_switcher = VB_CableSwitcher(vb_cable_name=cable_name, auto_switch=True)
        if vb_cable_switcher._powershell_available:
            _logger.info("VB Cable switching enabled - default playback device will be switched automatically")
            _logger.info("Waiting for device switch to take effect...")
            time.sleep(DEVICE_SWITCH_INIT_DELAY_SEC)
        else:
            _logger.warning(MSG_POWERSHELL_UNAVAILABLE)
            vb_cable_switcher = None
    
    try:
        # Create unified audio processor
        processor = DenoiserAudioProcessor(
            onnx_session, 
            target_sr=DEFAULT_SAMPLE_RATE, 
            frame_size=DEFAULT_FRAME_SIZE,
            enable_vad=enable_vad,
            vad_threshold_db=vad_threshold_db,
            atten_lim_db=atten_lim_db
        )
        
        # Get the actual VB Cable name that was switched to
        actual_vb_cable_name = None
        if vb_cable_switcher is not None:
            actual_vb_cable_name = vb_cable_switcher.vb_cable_name
        
        # Select backend
        if USE_PYAUDIOWPATCH:
            _logger.info("Using PyAudioWPatch + sounddevice backend")
            from .backends.pyaudio_backend import process_with_pyaudiowpatch
            process_with_pyaudiowpatch(processor, input_device, output_device, vb_cable_name=actual_vb_cable_name)
        elif USE_SOUNDDEVICE:
            _logger.info("Using sounddevice backend")
            from .backends.sounddevice_backend import process_with_sounddevice
            process_with_sounddevice(processor, input_device, output_device)
        else:
            raise RuntimeError("No suitable audio backend available")
    finally:
        # Restore original audio device
        if vb_cable_switcher is not None:
            vb_cable_switcher.restore_original_device()


def main():
    """Main function to run real-time system audio processing."""
    parser = argparse.ArgumentParser(
        description='Denoiser Real-Time System Audio Processing',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process system audio (default with VAD and VB Cable switching):
  python -m stream_denoiser
  
  
  # Disable VAD:
  python -m stream_denoiser --no-vad
  
  # Adjust VAD sensitivity (lower = more sensitive):
  python -m stream_denoiser --vad-threshold -50
  
  # Adjust attenuation limit:
  python -m stream_denoiser --atten-lim-db -80
  
  # List available audio devices:
  python -m stream_denoiser --list-devices
  
  # Use specific devices:
  python -m stream_denoiser --input-device 2 --output-device 1
  
  # Use VB Cable (automatically switches default playback device):
  python -m stream_denoiser (VB Cable switching enabled by default)
  
  # Disable VB Cable switching:
  python -m stream_denoiser --no-vb-cable
  
  # Custom VB Cable device name:
  python -m stream_denoiser --vb-cable-name "CABLE Input"
        """
    )
    
    parser.add_argument('--onnx', type=str, default='denoiser_model.onnx',
                        help='Path to ONNX model (default: denoiser_model.onnx)')
    parser.add_argument('--input-device', type=int, default=None,
                        help='Input device ID for system audio capture')
    parser.add_argument('--output-device', type=int, default=None,
                        help='Output device ID for audio playback')
    parser.add_argument('--no-vad', action='store_true',
                        help='Disable Voice Activity Detection')
    parser.add_argument('--vad-threshold', type=float, default=DEFAULT_VAD_THRESHOLD_DB,
                        help=f'VAD threshold in dB (default: {DEFAULT_VAD_THRESHOLD_DB}, lower = more sensitive)')
    parser.add_argument('--atten-lim-db', type=float, default=-60.0,
                        help='Attenuation limit in dB (default: -60.0)')
    parser.add_argument('--list-devices', action='store_true',
                        help='List all available audio devices and exit')
    parser.add_argument('--no-vb-cable', action='store_true',
                        help='Disable automatic VB Cable switching (use current default device)')
    parser.add_argument('--vb-cable-name', type=str, default=None,
                        help='Custom name for VB Cable device (auto-detected if not specified)')
    
    args = parser.parse_args()
    
    if args.list_devices:
        if not USE_SOUNDDEVICE:
            _logger.error("Device listing requires sounddevice library.")
            sys.exit(1)
        
        import sounddevice as sd
        
        print("Available audio devices:")
        print("=" * 80)
        devices = list_audio_devices()
        for i, device in enumerate(devices):
            host_api = sd.query_hostapis(device['hostapi'])['name']
            is_loopback = 'loopback' in device['name'].lower() or 'stereo mix' in device['name'].lower()
            loopback_marker = " [LOOPBACK]" if is_loopback else ""
            
            print(f"ID {i}: {device['name']}{loopback_marker}")
            print(f"    Host API: {host_api}")
            print(f"    Input channels: {device['max_input_channels']}, Output channels: {device['max_output_channels']}")
            print(f"    Default sample rate: {device['default_samplerate']}")
            print()
        
        try:
            loopback_id = find_loopback_device()
            print(f"Auto-detected loopback device ID: {loopback_id}")
        except Exception as e:
            print(f"Could not auto-detect loopback device: {e}")
        
        sys.exit(0)
    
    if not os.path.exists(args.onnx):
        _logger.error(MSG_ONNX_NOT_FOUND.format(args.onnx))
        sys.exit(1)
    
    try:
        # Load ONNX model
        onnx_session = load_onnx_model(args.onnx)
        
        # Process system audio
        process_system_audio_realtime(
            onnx_session,
            input_device=args.input_device,
            output_device=args.output_device,
            enable_vad=not args.no_vad,
            vad_threshold_db=args.vad_threshold,
            atten_lim_db=args.atten_lim_db,
            use_vb_cable=not args.no_vb_cable,
            vb_cable_name=args.vb_cable_name
        )
        
    except KeyboardInterrupt:
        print("\n\nProcessing interrupted by user")
    except Exception as e:
        _logger.error(f"Error: {e}")
        _logger.debug(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
