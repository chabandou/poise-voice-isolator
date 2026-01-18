"""
Poise Voice Isolator - Audio Processing Worker

QThread-based worker for non-blocking audio processing with signal-based
communication to the GUI.
"""
import os
import time
import traceback
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from ..processor import DenoiserAudioProcessor, load_onnx_model
from ..vb_cable import VB_CableSwitcher
from ..constants import (
    DEFAULT_SAMPLE_RATE, DEFAULT_FRAME_SIZE, DEVICE_SWITCH_INIT_DELAY_SEC,
    MSG_ONNX_NOT_FOUND, MSG_NO_BACKEND
)
from ..backend_detection import USE_PYAUDIOWPATCH, USE_SOUNDDEVICE, pyaudio, sd
from ..logging_config import get_logger

_logger = get_logger(__name__)


class AudioWorker(QThread):
    """
    Background thread for audio processing.
    
    Signals:
        stats_updated(dict): Emitted periodically with processing statistics
        status_changed(str): Emitted when processing status changes
        error_occurred(str): Emitted when an error occurs
        started_processing(): Emitted when processing starts successfully
        stopped_processing(): Emitted when processing stops
    """
    
    stats_updated = pyqtSignal(dict)
    status_changed = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    started_processing = pyqtSignal()
    stopped_processing = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Configuration
        self.onnx_path: str = "denoiser_model.onnx"
        self.input_device: Optional[int] = None
        self.output_device: Optional[int] = None
        self.vad_enabled: bool = True
        self.vad_threshold: float = -40.0
        self.atten_lim_db: float = -60.0
        self.vb_cable_enabled: bool = True
        self.vb_cable_name: Optional[str] = None
        
        # State
        self._running = False
        self._processor: Optional[DenoiserAudioProcessor] = None
        self._vb_cable_switcher: Optional[VB_CableSwitcher] = None
    
    def configure(self, 
                  onnx_path: str = "denoiser_model.onnx",
                  input_device: Optional[int] = None,
                  output_device: Optional[int] = None,
                  vad_enabled: bool = True,
                  vad_threshold: float = -40.0,
                  atten_lim_db: float = -60.0,
                  vb_cable_enabled: bool = True,
                  vb_cable_name: Optional[str] = None) -> None:
        """
        Configure worker settings before starting.
        
        Args:
            onnx_path: Path to ONNX model file
            input_device: Input device ID (optional)
            output_device: Output device ID (optional)
            vad_enabled: Enable Voice Activity Detection
            vad_threshold: VAD threshold in dB
            atten_lim_db: Attenuation limit in dB
            vb_cable_enabled: Enable VB Cable auto-switching
            vb_cable_name: Custom VB Cable device name
        """
        self.onnx_path = onnx_path
        self.input_device = input_device
        self.output_device = output_device
        self.vad_enabled = vad_enabled
        self.vad_threshold = vad_threshold
        self.atten_lim_db = atten_lim_db
        self.vb_cable_enabled = vb_cable_enabled
        self.vb_cable_name = vb_cable_name
    
    def run(self):
        """Main processing loop - runs in separate thread."""
        self._running = True
        self.status_changed.emit("Initializing...")
        
        try:
            # Validate ONNX model exists
            if not os.path.exists(self.onnx_path):
                self.error_occurred.emit(MSG_ONNX_NOT_FOUND.format(self.onnx_path))
                self.stopped_processing.emit()
                return
            
            # Load ONNX model
            self.status_changed.emit("Loading model...")
            onnx_session = load_onnx_model(self.onnx_path)
            
            # Setup VB Cable switcher if enabled
            actual_vb_cable_name = None
            if self.vb_cable_enabled:
                self.status_changed.emit("Switching audio device...")
                cable_name = self.vb_cable_name or "CABLE Input (VB-Audio Virtual Cable)"
                self._vb_cable_switcher = VB_CableSwitcher(vb_cable_name=cable_name, auto_switch=True)
                
                if self._vb_cable_switcher._powershell_available:
                    time.sleep(DEVICE_SWITCH_INIT_DELAY_SEC)
                    actual_vb_cable_name = self._vb_cable_switcher.vb_cable_name
                else:
                    self._vb_cable_switcher = None
            
            # Create processor
            self._processor = DenoiserAudioProcessor(
                onnx_session,
                target_sr=DEFAULT_SAMPLE_RATE,
                frame_size=DEFAULT_FRAME_SIZE,
                enable_vad=self.vad_enabled,
                vad_threshold_db=self.vad_threshold,
                atten_lim_db=self.atten_lim_db
            )
            
            self.status_changed.emit("Starting audio streams...")
            self.started_processing.emit()
            
            # Run the appropriate backend
            # Run the appropriate backend
            if USE_PYAUDIOWPATCH and USE_SOUNDDEVICE:
                self._run_processing_loop()
            elif USE_SOUNDDEVICE:
                self._run_processing_loop()
            else:
                self.error_occurred.emit(MSG_NO_BACKEND)
            
        except Exception as e:
            self.error_occurred.emit(f"Error: {str(e)}\n{traceback.format_exc()}")
        finally:
            self._cleanup()
            self.stopped_processing.emit()
    
    def _run_processing_loop(self) -> None:
        """
        Main processing loop using the existing backend infrastructure.
        
        This is a simplified loop that periodically emits stats.
        The actual audio processing is handled by the backend.
        """
        import numpy as np
        from ..ring_buffer import RingBuffer
        from ..constants import BUFFER_CAPACITY_RATIO, WORKER_SLEEP_TIME_SEC
        from ..device_utils import get_output_device_id, validate_output_device
        
        if not USE_SOUNDDEVICE:
            self.error_occurred.emit("sounddevice is required")
            return
        
        block_size = self._processor.frame_size
        
        # Initialize PyAudio
        if pyaudio is None:
            self.error_occurred.emit("PyAudio is not available")
            return
        
        p = pyaudio.PyAudio()
        loopback_stream = None
        
        try:
            # Find loopback device
            loopback_device = None
            wasapi_host_api_index = None
            
            for api_idx in range(p.get_host_api_count()):
                api_info = p.get_host_api_info_by_index(api_idx)
                if 'WASAPI' in api_info['name'].upper():
                    wasapi_host_api_index = api_idx
                    break
            
            # Search for VB Cable Output
            device_count = p.get_device_count()
            for i in range(device_count):
                try:
                    device_info = p.get_device_info_by_index(i)
                    if wasapi_host_api_index is not None and device_info['hostApi'] != wasapi_host_api_index:
                        continue
                    
                    device_name = device_info['name']
                    if device_info['maxInputChannels'] > 0:
                        if 'CABLE Output' in device_name:
                            loopback_device = {'index': i, 'name': device_name, 'info': device_info}
                            break
                except Exception:
                    continue
            
            if not loopback_device:
                loopback_device = p.get_default_wasapi_loopback()
                if not loopback_device:
                    self.error_occurred.emit("No loopback device found")
                    return
            
            device_info = p.get_device_info_by_index(loopback_device['index'])
            input_sr = int(device_info['defaultSampleRate'])
            input_channels = device_info.get('maxInputChannels', 2) or 2
            
            self._processor.setup_resampler(input_sr)
            
            # Find output device
            devices = sd.query_devices()
            try:
                output_dev_id = get_output_device_id(self.output_device, devices)
            except ValueError as e:
                self.error_occurred.emit(str(e))
                return
            
            output_sr = self._processor.target_sr
            
            # Ring buffers
            buffer_capacity = int(self._processor.target_sr * BUFFER_CAPACITY_RATIO)
            input_buffer = RingBuffer(buffer_capacity)
            output_buffer = RingBuffer(buffer_capacity)
            
            # Callbacks
            def loopback_callback(in_data, frame_count, time_info, status):
                try:
                    audio_data = np.frombuffer(in_data, dtype=np.float32)
                    if input_channels > 1:
                        audio_data = audio_data.reshape(-1, input_channels)
                        audio_data = np.mean(audio_data, axis=1)
                    else:
                        audio_data = audio_data.flatten()
                    input_buffer.write(audio_data)
                    return (None, pyaudio.paContinue)
                except Exception:
                    return (None, pyaudio.paAbort)
            
            def output_callback(outdata, frames, time_arg, status):
                try:
                    processed_chunk = output_buffer.read(frames)
                    if processed_chunk is not None and len(processed_chunk) > 0:
                        if len(processed_chunk) < frames:
                            padded = np.zeros(frames, dtype=np.float32)
                            padded[:len(processed_chunk)] = processed_chunk
                            processed_chunk = padded
                        # Duplicate mono to stereo for proper playback on both channels
                        outdata[:, 0] = processed_chunk[:frames].astype(np.float32)
                        outdata[:, 1] = processed_chunk[:frames].astype(np.float32)
                    else:
                        outdata.fill(0)
                except Exception:
                    outdata.fill(0)
            
            # Open streams
            loopback_stream = p.open(
                format=pyaudio.paFloat32,
                channels=input_channels,
                rate=input_sr,
                input=True,
                input_device_index=loopback_device['index'],
                frames_per_buffer=block_size,
                stream_callback=loopback_callback
            )
            loopback_stream.start_stream()
            
            # Try to open output stream with retry and fallback logic
            try:
                output_stream = sd.OutputStream(
                    device=output_dev_id,
                    channels=2,
                    samplerate=output_sr,
                    blocksize=block_size,
                    callback=output_callback,
                    dtype=np.float32
                )
                self._processor.setup_output_resampler(output_sr)
                
            except sd.PortAudioError:
                # Fallback to device default sample rate
                try:
                    output_device_info = sd.query_devices(output_dev_id)
                    device_default_sr = int(output_device_info.get('default_samplerate', 44100))
                    self.status_changed.emit(f"Switching to {device_default_sr}Hz output...")
                    
                    output_stream = sd.OutputStream(
                        device=output_dev_id,
                        channels=2,
                        samplerate=device_default_sr,
                        blocksize=block_size,
                        callback=output_callback,
                        dtype=np.float32
                    )
                    
                    self._processor.setup_output_resampler(device_default_sr)
                    
                except Exception as e:
                    if loopback_stream:
                        loopback_stream.stop_stream()
                        loopback_stream.close()
                    p.terminate()
                    self.error_occurred.emit(f"Failed to open output: {str(e)}")
                    return
            
            self.status_changed.emit("Processing")
            
            last_stats_time = time.time()
            
            with output_stream:
                while self._running:
                    # Process audio
                    audio_chunk = input_buffer.read(block_size)
                    
                    if audio_chunk is not None:
                        audio_output = self._processor.process_chunk(audio_chunk)
                        if audio_output is not None:
                            output_buffer.write(audio_output)
                    else:
                        time.sleep(WORKER_SLEEP_TIME_SEC)
                    
                    # Emit stats periodically
                    current_time = time.time()
                    if current_time - last_stats_time >= 0.1:  # Every 100ms
                        stats = self._processor.get_stats()
                        stats['input_buffer'] = input_buffer.available()
                        stats['output_buffer'] = output_buffer.available()
                        self.stats_updated.emit(stats)
                        last_stats_time = current_time
        
        finally:
            if loopback_stream:
                try:
                    loopback_stream.stop_stream()
                    loopback_stream.close()
                except Exception:
                    pass
            p.terminate()
    
    def stop(self) -> None:
        """Stop processing gracefully."""
        self._running = False
        self.status_changed.emit("Stopping...")
    
    def _cleanup(self) -> None:
        """Clean up resources."""
        if self._vb_cable_switcher is not None:
            try:
                self._vb_cable_switcher.restore_original_device()
            except Exception:
                pass
            self._vb_cable_switcher = None
        
        self._processor = None
        self.status_changed.emit("Stopped")
    
    @property
    def is_running(self) -> bool:
        """Check if worker is currently running."""
        return self._running and self.isRunning()
