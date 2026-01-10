"""
PyAudioWPatch Backend

Audio processing using PyAudioWPatch for WASAPI loopback input
and sounddevice for output.
"""
import time
import threading
import numpy as np
from typing import Optional

from ..backend_detection import (
    USE_PYAUDIOWPATCH, USE_SOUNDDEVICE, pyaudio, sd
)

from ..constants import (
    BUFFER_CAPACITY_RATIO,
    WORKER_SLEEP_TIME_SEC,
    STATS_UPDATE_INTERVAL_SEC,
    STATS_PRINT_INTERVAL_SEC,
    DEVICE_SWITCH_STREAM_DELAY_SEC,
    OUTPUT_STREAM_RETRY_COUNT,
    OUTPUT_STREAM_RETRY_DELAY_SEC,
)
from ..ring_buffer import RingBuffer
from ..processor import DenoiserAudioProcessor
from ..device_utils import get_output_device_id, validate_output_device, print_stats, print_final_stats
from ..logging_config import get_logger

_logger = get_logger(__name__)


def _find_vb_cable_loopback(p, vb_cable_name: Optional[str]) -> Optional[dict]:
    """Find VB Cable loopback device matching the switched device."""
    vb_cable_loopback = None
    device_count = p.get_device_count()
    
    # Extract matching terms from VB Cable device name
    search_terms = []
    full_identifier = None
    if vb_cable_name:
        _logger.info(f"Playback device set to: {vb_cable_name}")
        _logger.info("Searching for corresponding loopback capture device (CABLE Output)...")
        
        # Extract the full identifier from the name
        if '(' in vb_cable_name and ')' in vb_cable_name:
            start = vb_cable_name.find('(')
            end = vb_cable_name.find(')')
            if start < end:
                identifier = vb_cable_name[start+1:end]
                full_identifier = identifier
                exact_match_pattern = f"CABLE Output ({identifier})"
                search_terms.insert(0, exact_match_pattern)
                _logger.debug(f"  Target loopback device: {exact_match_pattern}")
                search_terms.append(identifier)
                search_terms.append('CABLE Output')
        else:
            if 'CABLE Input' in vb_cable_name:
                search_name = vb_cable_name.replace('CABLE Input', 'CABLE Output')
                search_terms.append(search_name)
                search_terms.append('CABLE Output')
    
    # Get WASAPI Host API index
    wasapi_host_api_index = None
    for api_idx in range(p.get_host_api_count()):
        api_info = p.get_host_api_info_by_index(api_idx)
        if 'WASAPI' in api_info['name'].upper():
            wasapi_host_api_index = api_idx
            break
    
    _logger.info(f"Searching {device_count} devices for VB Cable loopback (WASAPI only)...")
    
    for i in range(device_count):
        try:
            device_info = p.get_device_info_by_index(i)
            
            if wasapi_host_api_index is not None and device_info['hostApi'] != wasapi_host_api_index:
                continue
            
            device_name = device_info['name']
            if device_info['maxInputChannels'] > 0:
                if search_terms:
                    exact_match_pattern = search_terms[0] if search_terms else None
                    if exact_match_pattern:
                        pattern_identifier = full_identifier
                        if not pattern_identifier and '(' in exact_match_pattern and ')' in exact_match_pattern:
                            id_start = exact_match_pattern.find('(') + 1
                            id_end = exact_match_pattern.find(')')
                            pattern_identifier = exact_match_pattern[id_start:id_end]
                        
                        if device_name == exact_match_pattern:
                            vb_cable_loopback = {'index': i, 'name': device_name, 'info': device_info}
                            _logger.info(f"✓ Found loopback capture device: {device_name} (Index: {i})")
                            break
                        
                        if pattern_identifier and device_name.startswith('CABLE Output'):
                            if '(' in device_name and ')' in device_name:
                                dev_id_start = device_name.find('(') + 1
                                dev_id_end = device_name.find(')')
                                if dev_id_end > dev_id_start:
                                    dev_identifier = device_name[dev_id_start:dev_id_end]
                                    if dev_identifier == pattern_identifier:
                                        vb_cable_loopback = {'index': i, 'name': device_name, 'info': device_info}
                                        _logger.info(f"✓ Found loopback capture device: {device_name} (Index: {i})")
                                        break
                    
                    if not full_identifier:
                        for term in search_terms[1:]:
                            if term in device_name:
                                if 'CABLE Output' in device_name:
                                    vb_cable_loopback = {'index': i, 'name': device_name, 'info': device_info}
                                    _logger.info(f"✓ Found matching VB Cable loopback: {device_name} (Index: {i})")
                                    break
                                elif vb_cable_loopback is None:
                                    vb_cable_loopback = {'index': i, 'name': device_name, 'info': device_info}
                        if vb_cable_loopback and 'CABLE Output' in vb_cable_loopback['name']:
                            break
                else:
                    if 'CABLE Output' in device_name and 'VB-Audio' in device_name:
                        vb_cable_loopback = {'index': i, 'name': device_name, 'info': device_info}
                        _logger.info(f"Found VB Cable Output: {device_name} (Index: {i})")
                        break
                    elif 'CABLE Output' in device_name and vb_cable_loopback is None:
                        vb_cable_loopback = {'index': i, 'name': device_name, 'info': device_info}
        except Exception:
            continue
            
    return vb_cable_loopback


def _open_output_stream_with_retries(output_dev_id: int, 
                                     output_sr: int, 
                                     device_default_sr: int, 
                                     block_size: int, 
                                     callback,
                                     max_retries: int = OUTPUT_STREAM_RETRY_COUNT,
                                     retry_delay: float = OUTPUT_STREAM_RETRY_DELAY_SEC):
    """Open output stream with retry logic."""
    output_stream = None
    final_sr = output_sr
    
    for attempt in range(max_retries):
        try:
            output_stream = sd.OutputStream(
                device=output_dev_id,
                channels=1,
                samplerate=output_sr,
                blocksize=block_size,
                callback=callback,
                dtype=np.float32
            )
            break
        except sd.PortAudioError as e:
            if attempt < max_retries - 1:
                _logger.warning(f"Attempt {attempt + 1} failed, retrying in {retry_delay}s...")
                time.sleep(retry_delay)
                retry_delay *= 1.5
            else:
                if output_sr != device_default_sr:
                    _logger.warning(f"Failed with {output_sr}Hz, trying device default {device_default_sr}Hz...")
                    try:
                        final_sr = device_default_sr
                        output_stream = sd.OutputStream(
                            device=output_dev_id,
                            channels=1,
                            samplerate=final_sr,
                            blocksize=block_size,
                            callback=callback,
                            dtype=np.float32
                        )
                        _logger.info(f"Successfully opened with {final_sr}Hz")
                        break
                    except sd.PortAudioError:
                        pass
                
                _logger.error(f"Error opening output stream after {max_retries} attempts: {e}")
                raise
    
    if output_stream is None:
        raise RuntimeError("Failed to open output stream after all retries")
        
    return output_stream, final_sr


def process_with_pyaudiowpatch(processor: DenoiserAudioProcessor, 
                                input_device: Optional[int] = None, 
                                output_device: Optional[int] = None,
                                vb_cable_name: Optional[str] = None) -> None:
    """
    Process system audio using PyAudioWPatch for WASAPI loopback input
    and sounddevice for output, with ring buffers for reduced latency.
    
    Args:
        processor: DenoiserAudioProcessor instance
        input_device: Input device ID (optional)
        output_device: Output device ID (optional)
        vb_cable_name: Name of VB Cable device that was switched to (used to find matching loopback)
    """
    if not USE_SOUNDDEVICE:
        raise RuntimeError("Hybrid mode requires sounddevice for output")
    
    if pyaudio is None:
        raise RuntimeError("PyAudio is not available")
    
    block_size = processor.frame_size
    p = pyaudio.PyAudio()
    loopback_stream = None
    
    try:
        # Try to find VB Cable loopback device matching the switched device
        vb_cable_loopback = _find_vb_cable_loopback(p, vb_cable_name)
        
        if vb_cable_loopback:
            loopback_device = vb_cable_loopback
            _logger.info(f"✓ Loopback capture device: {loopback_device['name']}")
            _logger.debug(f"  Device index: {loopback_device['index']}, Input channels: {loopback_device['info']['maxInputChannels']}")
        else:
            _logger.info("VB Cable Output not found, trying default WASAPI loopback...")
            loopback_device = p.get_default_wasapi_loopback()
            if not loopback_device:
                raise RuntimeError("No WASAPI loopback device found. Make sure VB Cable is installed.")
            _logger.warning(f"Using default WASAPI loopback device: {loopback_device['name']}")
            _logger.warning(f"WARNING: This may not capture from VB Cable!")
        
        device_info = p.get_device_info_by_index(loopback_device['index'])
        input_sr = int(device_info['defaultSampleRate'])
        input_channels = device_info.get('maxInputChannels', 2) or 2
        
        processor.setup_resampler(input_sr)
        
        # Find output device
        devices = sd.query_devices()
        try:
            output_dev_id = get_output_device_id(output_device, devices)
            if not validate_output_device(output_dev_id, processor.target_sr, devices):
                raise ValueError(f"Output device {output_dev_id} does not support required configuration")
        except ValueError as e:
            _logger.error(f"Error selecting output device: {e}")
            _logger.info("Available output devices:")
            for i, device in enumerate(devices):
                if device['max_output_channels'] > 0:
                    _logger.info(f"  ID {i}: {device['name']} (channels: {device['max_output_channels']}, sr: {device.get('default_samplerate', 'N/A')})")
            raise
        
        output_device_info = sd.query_devices(output_dev_id)
        _logger.info(f"Output device: {output_device_info['name']} (ID: {output_dev_id})")
        
        device_default_sr = int(output_device_info.get('default_samplerate', 44100))
        output_sr = processor.target_sr
        
        if device_default_sr != output_sr:
            _logger.info(f"Device default sample rate: {device_default_sr}Hz, requested: {output_sr}Hz")
        
        _logger.info(f"Output sample rate: {output_sr}Hz")
        
        time.sleep(DEVICE_SWITCH_STREAM_DELAY_SEC)
        
        buffer_capacity = int(processor.target_sr * BUFFER_CAPACITY_RATIO)
        input_buffer = RingBuffer(buffer_capacity)
        output_buffer = RingBuffer(buffer_capacity)
        
        _logger.info(f"Using ring buffers with {buffer_capacity} samples (~{buffer_capacity/processor.target_sr*1000:.0f}ms) capacity")
        
        def loopback_callback(in_data, frame_count, time_info, status):
            try:
                if status:
                    _logger.debug(f"Loopback status: {status}")
                
                audio_data = np.frombuffer(in_data, dtype=np.float32)
                
                if input_channels > 1:
                    audio_data = audio_data.reshape(-1, input_channels)
                    audio_data = np.mean(audio_data, axis=1)
                else:
                    audio_data = audio_data.flatten()
                
                input_buffer.write(audio_data)
                
                return (None, pyaudio.paContinue)
            except (ValueError, RuntimeError, OSError) as e:
                _logger.error(f"Error in loopback callback: {e}")
                return (None, pyaudio.paAbort)
        
        def process_audio_worker():
            frames_processed = 0
            last_debug_time = time.time()
            consecutive_empty_reads = 0
            while True:
                try:
                    audio_chunk = input_buffer.read(block_size)
                    
                    if audio_chunk is None:
                        consecutive_empty_reads += 1
                        time.sleep(WORKER_SLEEP_TIME_SEC)
                        current_time = time.time()
                        if current_time - last_debug_time > 2.0:
                            input_avail = input_buffer.available()
                            output_avail = output_buffer.available()
                            if input_avail == 0 and consecutive_empty_reads > 100:
                                _logger.warning(f"No input audio detected after {consecutive_empty_reads} attempts.")
                                _logger.debug(f"Input buffer: {input_avail}, Output buffer: {output_avail}")
                                _logger.debug(f"Loopback device: {loopback_device['name']}")
                                _logger.info("Make sure:")
                                _logger.info("1. Audio is playing through VB Cable")
                                _logger.info("2. Applications are using VB Cable as output device")
                            last_debug_time = current_time
                        continue
                    
                    consecutive_empty_reads = 0
                    
                    audio_output = processor.process_chunk(audio_chunk)
                    
                    if audio_output is not None:
                        output_buffer.write(audio_output)
                        frames_processed += 1
                
                except (ValueError, RuntimeError, OSError) as e:
                    _logger.error(f"Error in processing worker: {e}")
                    import traceback
                    _logger.debug(traceback.format_exc())
        
        output_callback_count = [0]
        def output_callback(outdata, frames, time_arg, status):
            try:
                output_callback_count[0] += 1
                
                if status:
                    _logger.debug(f"Output stream status: {status}")
                
                processed_chunk = output_buffer.read(frames)
                
                if processed_chunk is not None and len(processed_chunk) > 0:
                    if len(processed_chunk) != frames:
                        if len(processed_chunk) < frames:
                            padded = np.zeros(frames, dtype=np.float32)
                            padded[:len(processed_chunk)] = processed_chunk
                            processed_chunk = padded
                        else:
                            processed_chunk = processed_chunk[:frames]
                    
                    if len(processed_chunk.shape) == 1:
                        outdata[:, 0] = processed_chunk.astype(np.float32)
                    else:
                        outdata[:, 0] = processed_chunk.flatten()[:frames].astype(np.float32)
                    
                    if output_callback_count[0] % 1000 == 0:
                        rms = np.sqrt(np.mean(processed_chunk ** 2))
                        _logger.debug(f"[Output] Callback #{output_callback_count[0]}: {len(processed_chunk)} samples, RMS: {rms:.4f}")
                else:
                    outdata.fill(0)
                    if output_callback_count[0] % 500 == 0:
                        _logger.debug(f"[Output] Callback #{output_callback_count[0]}: No data (buffer: {output_buffer.available()})")
            
            except (ValueError, RuntimeError, OSError) as e:
                _logger.error(f"Error in output callback: {e}")
                outdata.fill(0)
        
        _logger.info("Starting real-time system audio processing...")
        _logger.info("Press Ctrl+C to stop...")
        
        loopback_stream = p.open(
            format=pyaudio.paFloat32,
            channels=input_channels,
            rate=input_sr,
            input=True,
            input_device_index=loopback_device['index'],
            frames_per_buffer=block_size,
            stream_callback=loopback_callback
        )
        
        processing_thread = threading.Thread(target=process_audio_worker, daemon=True)
        processing_thread.start()
        
        loopback_stream.start_stream()
        
        start_time = time.time()
        last_stats_time = start_time
        
        try:

            output_stream, output_sr = _open_output_stream_with_retries(
                output_dev_id, 
                output_sr, 
                device_default_sr, 
                block_size, 
                output_callback,
                OUTPUT_STREAM_RETRY_COUNT,
                OUTPUT_STREAM_RETRY_DELAY_SEC
            )
            
            # Setup output resampler based on actual output rate
            processor.setup_output_resampler(output_sr)
            
            _logger.info(f"Input sample rate: {input_sr}Hz, Output sample rate: {output_sr}Hz")
            if input_sr != processor.target_sr:
                _logger.info(f"Input Resampling enabled: {input_sr}Hz -> {processor.target_sr}Hz")
            
            with output_stream:
                _logger.info("Output stream active - audio should be playing now")
                
                while True:
                    time.sleep(STATS_UPDATE_INTERVAL_SEC)
                    
                    current_time = time.time()
                    if current_time - last_stats_time >= STATS_PRINT_INTERVAL_SEC:
                        stats = processor.get_stats()
                        elapsed = current_time - start_time
                        print_stats(stats, elapsed, (input_buffer.available(), output_buffer.available()))
                        last_stats_time = current_time
        
        except KeyboardInterrupt:
            _logger.info("Stopping...")
    finally:
        if loopback_stream:
            try:
                loopback_stream.stop_stream()
                loopback_stream.close()
            except Exception:
                pass
        p.terminate()
        stats = processor.get_stats()
        print_final_stats(stats)
