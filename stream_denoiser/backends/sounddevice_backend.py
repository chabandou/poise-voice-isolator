"""
Sounddevice Backend

Audio processing using sounddevice for both input and output.
"""
import time
import numpy as np
from typing import Optional

try:
    import sounddevice as sd
    USE_SOUNDDEVICE = True
except ImportError:
    USE_SOUNDDEVICE = False

from ..constants import STATS_PRINT_INTERVAL_SEC
from ..processor import DenoiserAudioProcessor
from ..device_utils import (
    find_loopback_device, 
    get_output_device_id, 
    validate_output_device, 
    print_stats, 
    print_final_stats
)


def process_with_sounddevice(processor: DenoiserAudioProcessor, 
                             input_device: Optional[int] = None, 
                             output_device: Optional[int] = None) -> None:
    """
    Process system audio using sounddevice for both input and output.
    
    Args:
        processor: DenoiserAudioProcessor instance
        input_device: Input device ID (optional)
        output_device: Output device ID (optional)
    """
    if not USE_SOUNDDEVICE:
        raise RuntimeError("This mode requires sounddevice library")
    
    block_size = processor.frame_size
    
    # Find devices
    try:
        input_dev_id = find_loopback_device(input_device)
    except (RuntimeError, ValueError) as e:
        print(f"Warning: {e}")
        input_dev_id = sd.default.device[0]
    
    devices = sd.query_devices()
    
    # Get input device's host API to ensure output uses the same backend
    input_device_info = sd.query_devices(input_dev_id)
    input_host_api = sd.query_hostapis(input_device_info['hostapi'])['name']
    
    try:
        output_dev_id = get_output_device_id(output_device, devices, input_host_api=input_host_api)
        if not validate_output_device(output_dev_id, processor.target_sr, devices):
            raise ValueError(f"Output device {output_dev_id} does not support required configuration")
    except ValueError as e:
        print(f"Error selecting output device: {e}")
        print("\nAvailable output devices:")
        for i, device in enumerate(devices):
            if device['max_output_channels'] > 0:
                host_api = sd.query_hostapis(device['hostapi'])['name']
                match_marker = " [MATCHES INPUT]" if input_host_api.lower() in host_api.lower() else ""
                print(f"  ID {i}: {device['name']} (API: {host_api}){match_marker}")
        raise
    
    input_device_info = sd.query_devices(input_dev_id)
    output_device_info = sd.query_devices(output_dev_id)
    
    input_sr = int(input_device_info['default_samplerate'])
    
    # Setup processor resampler
    processor.setup_resampler(input_sr)
    
    print(f"\nStarting real-time system audio processing...")
    print(f"Input device: {input_device_info['name']} (ID: {input_dev_id})")
    print(f"Output device: {output_device_info['name']} (ID: {output_dev_id})")
    print(f"Output sample rate: {processor.target_sr}Hz")
    print("Press Ctrl+C to stop...\n")
    
    start_time = time.time()
    last_stats_time = start_time
    
    try:
        # Try to open streams
        try:
            input_stream = sd.InputStream(
                device=input_dev_id,
                samplerate=input_sr,
                channels=1,
                dtype='float32',
                blocksize=block_size
            )
        except sd.PortAudioError as e:
            print(f"\nError opening input stream: {e}")
            print(f"Device ID: {input_dev_id}")
            print(f"Device name: {input_device_info['name']}")
            raise
        
        try:
            output_stream = sd.OutputStream(
                device=output_dev_id,
                samplerate=processor.target_sr,
                channels=1,
                dtype='float32',
                blocksize=block_size
            )
            processor.setup_output_resampler(processor.target_sr)
            
        except sd.PortAudioError as e:
            # Fallback to device default sample rate
            try:
                device_default_sr = int(output_device_info.get('default_samplerate', 44100))
                print(f"Warning: Failed to open output at {processor.target_sr}Hz. Retrying with device default {device_default_sr}Hz...")
                
                output_stream = sd.OutputStream(
                    device=output_dev_id,
                    samplerate=device_default_sr,
                    channels=1,
                    dtype='float32',
                    blocksize=block_size
                )
                
                processor.setup_output_resampler(device_default_sr)
                print(f"Output opened with {device_default_sr}Hz (Resampling enabled)")
                
            except sd.PortAudioError:
                input_stream.close()
                print(f"\nError opening output stream: {e}")
                print(f"Device ID: {output_dev_id}")
                print(f"Device name: {output_device_info['name']}")
                print(f"Requested sample rate: {processor.target_sr}Hz")
                print(f"Requested channels: 1")
                print("\nTroubleshooting:")
                print("1. Make sure the device is not being used by another application")
                print("2. Try specifying a different output device with --output-device")
                print("3. Run with --list-devices to see available devices")
                raise
        
        with input_stream, output_stream:
            
            while True:
                # Read audio chunk
                audio_chunk, overflowed = input_stream.read(block_size)
                
                if overflowed:
                    print("\nWarning: Input buffer overflow")
                
                if audio_chunk is None or len(audio_chunk) == 0:
                    continue
                
                # Flatten to mono
                audio_chunk = audio_chunk.flatten()
                
                # Process through unified processor
                audio_output = processor.process_chunk(audio_chunk)
                
                if audio_output is not None:
                    # Write to output
                    output_stream.write(audio_output.astype(np.float32))
                
                # Print stats
                current_time = time.time()
                if current_time - last_stats_time >= STATS_PRINT_INTERVAL_SEC:
                    stats = processor.get_stats()
                    elapsed = current_time - start_time
                    print_stats(stats, elapsed)
                    last_stats_time = current_time
    
    except KeyboardInterrupt:
        print("\n\nStopping...")
    
    stats = processor.get_stats()
    print_final_stats(stats)
