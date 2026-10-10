"""
Poise Voice Isolator - Audio Processing Worker

QThread-based worker for non-blocking audio processing with signal-based
communication to the GUI.
"""
import time
import traceback
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from ..processor import DenoiserAudioProcessor
from ..engines import create_engine, DEFAULT_DF3_ONNX
from ..vb_cable import VB_CableSwitcher
from ..constants import (
    DEFAULT_SAMPLE_RATE, DEFAULT_FRAME_SIZE, DEVICE_SWITCH_INIT_DELAY_SEC,
    DEVICE_SWITCH_SUCCESS_HOLD_SEC,
    MSG_NO_BACKEND, DEFAULT_MODEL, MSG_DEVICE_SWITCHING, MSG_DEVICE_SWITCHED
)
from ..backend_detection import USE_SOUNDDEVICE, sd
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
        self.model: str = DEFAULT_MODEL
        self.onnx_path: str = DEFAULT_DF3_ONNX
        self.input_device: Optional[int] = None
        self.output_device: Optional[int] = None
        self.aad_enabled: bool = True
        self.aad_threshold: float = -40.0
        self.atten_lim_db: float = -60.0
        self.vb_cable_enabled: bool = True
        self.vb_cable_name: Optional[str] = None
        
        # State
        self._running = False
        self._processor: Optional[DenoiserAudioProcessor] = None
        self._vb_cable_switcher: Optional[VB_CableSwitcher] = None
    
    def configure(self, 
                  model: str = DEFAULT_MODEL,
                  onnx_path: str = DEFAULT_DF3_ONNX,
                  input_device: Optional[int] = None,
                  output_device: Optional[int] = None,
                  aad_enabled: bool = True,
                  aad_threshold: float = -40.0,
                  atten_lim_db: float = -60.0,
                  vb_cable_enabled: bool = True,
                  vb_cable_name: Optional[str] = None) -> None:
        """
        Configure worker settings before starting.
        
        Args:
            model: Denoising engine name ("deepfilternet3" or "rnnoise")
            onnx_path: Path to ONNX model file (deepfilternet3 only)
            input_device: Input device ID (optional)
            output_device: Output device ID (optional)
            aad_enabled: Enable Audio Activity detection
            aad_threshold: AAD threshold in dB
            atten_lim_db: Attenuation limit in dB
            vb_cable_enabled: Enable VB Cable auto-switching
            vb_cable_name: Custom VB Cable device name
        """
        self.onnx_path = onnx_path
        self.model = model
        self.input_device = input_device
        self.output_device = output_device
        self.aad_enabled = aad_enabled
        self.aad_threshold = aad_threshold
        self.atten_lim_db = atten_lim_db
        self.vb_cable_enabled = vb_cable_enabled
        self.vb_cable_name = vb_cable_name
    
    def run(self):
        """Main processing loop - runs in separate thread."""
        self._running = True
        self.status_changed.emit("Initializing...")
        
        try:
            # Build denoising engine (validates model availability)
            self.status_changed.emit("Loading model...")
            try:
                engine = create_engine(self.model, onnx_path=self.onnx_path,
                                       atten_lim_db=self.atten_lim_db)
            except FileNotFoundError as e:
                self.error_occurred.emit(f"Model file not found: {e}")
                self.stopped_processing.emit()
                return
            except (RuntimeError, ValueError) as e:
                self.error_occurred.emit(f"Error: {e}")
                self.stopped_processing.emit()
                return
            
            # VB-Cable routing is mandatory: Poise captures from CABLE Output,
            # which only receives audio when default playback is CABLE Input.
            # If the automatic switch fails, do NOT start processing — the
            # GUI shows a modal with manual steps instead.
            if self.vb_cable_enabled:
                self.status_changed.emit(MSG_DEVICE_SWITCHING)
                cable_name = self.vb_cable_name or "CABLE Input (VB-Audio Virtual Cable)"
                self._vb_cable_switcher = VB_CableSwitcher(
                    vb_cable_name=cable_name,
                    auto_switch=True,
                    status_cb=self.status_changed.emit,
                )

                if not self._vb_cable_switcher._powershell_available:
                    self.error_occurred.emit(
                        "VB-CABLE: PowerShell unavailable, could not switch "
                        "default playback to CABLE Input."
                    )
                    self.stopped_processing.emit()
                    return

                time.sleep(DEVICE_SWITCH_INIT_DELAY_SEC)
                if not self._vb_cable_switcher.switch_to_vb_cable():
                    self.error_occurred.emit(
                        "VB-CABLE: automatic switch to CABLE Input failed. "
                        "Is VB-Cable installed?"
                    )
                    self.stopped_processing.emit()
                    return

                try:
                    current = self._vb_cable_switcher.get_current_default_device()
                except Exception:
                    current = None
                if not current or "CABLE" not in current.upper():
                    self.error_occurred.emit(
                        "VB-CABLE: default playback is still "
                        f"'{current or 'unknown'}', not CABLE Input."
                    )
                    self.stopped_processing.emit()
                    return
                self.status_changed.emit(MSG_DEVICE_SWITCHED)
                # Hold the confirmation so it stays readable before the
                # next phase ("Starting audio streams...") overwrites it.
                # Interruptible: abort early if the user hits stop.
                _hold_until = time.time() + DEVICE_SWITCH_SUCCESS_HOLD_SEC
                while time.time() < _hold_until:
                    if not self._running:
                        return
                    time.sleep(0.1)
            
            # Create processor (frame size follows the engine)
            self._processor = DenoiserAudioProcessor(
                engine,
                target_sr=DEFAULT_SAMPLE_RATE,
                frame_size=engine.required_frame_size or DEFAULT_FRAME_SIZE,
                enable_aad=self.aad_enabled,
                aad_threshold_db=self.aad_threshold,
                atten_lim_db=self.atten_lim_db
            )
            
            self.status_changed.emit("Starting audio streams...")
            self.started_processing.emit()
            
            # sounddevice-only backend (CABLE Output is a regular WASAPI
            # capture device; no PyAudioWPatch loopback extension)
            if USE_SOUNDDEVICE:
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
        Main processing loop using the sounddevice backend (blocking I/O).

        Captures CABLE Output as a regular WASAPI input device, processes
        through DenoiserAudioProcessor, and plays to the output device.
        Runs in this QThread; stops when self._running is cleared.
        """
        import numpy as np
        from ..device_utils import (
            find_loopback_device,
            get_output_device_id,
            validate_output_device,
        )

        if not USE_SOUNDDEVICE or sd is None:
            self.error_occurred.emit("sounddevice is required")
            return

        try:
            input_dev_id = find_loopback_device(self.input_device)
        except (RuntimeError, ValueError) as e:
            self.error_occurred.emit(f"Input device error: {e}")
            return

        try:
            devices = sd.query_devices()
            input_device_info = sd.query_devices(input_dev_id)
        except Exception as e:
            self.error_occurred.emit(f"Failed to query audio devices: {e}")
            return

        # VB-Cable is mandatory: refuse to capture a mic/default input.
        input_name = str(input_device_info.get('name', ''))
        if "CABLE OUTPUT" not in input_name.upper():
            self.error_occurred.emit(
                "VB-CABLE: CABLE Output not found "
                f"(found '{input_name or 'unknown'}' instead). "
                "Is VB-Cable installed?"
            )
            return

        input_sr = int(input_device_info.get('default_samplerate', 48000))
        self._processor.setup_resampler(input_sr)
        in_block_size = self._processor.input_block_size

        # Find output device (match input host API for compatibility)
        try:
            input_host_api = sd.query_hostapis(input_device_info['hostapi'])['name']
        except Exception:
            input_host_api = None
        try:
            output_dev_id = get_output_device_id(
                self.output_device, devices, input_host_api=input_host_api)
            if not validate_output_device(
                    output_dev_id, self._processor.target_sr, devices):
                raise ValueError(
                    f"Output device {output_dev_id} does not support "
                    "required configuration")
        except (ValueError, RuntimeError) as e:
            self.error_occurred.emit(str(e))
            return

        output_sr = self._processor.target_sr
        output_device_info = sd.query_devices(output_dev_id)

        # Open input stream at its native rate, stereo (see note below),
        # then downmix to mono in software like the old PyAudio path did.
        # NOTE: never open a stereo WASAPI endpoint (e.g. VB-Cable Output)
        # with channels=1: the capture comes back sample-doubled (every
        # sample repeated twice = effective half rate in a full-rate
        # container), which sounds dull/muffled/incomprehensible through
        # the engine. Stereo capture is bit-clean.
        try:
            try:
                input_stream = sd.InputStream(
                    device=input_dev_id,
                    samplerate=input_sr,
                    channels=2,
                    dtype='float32',
                    blocksize=in_block_size,
                )
                _input_channels = 2
            except Exception:
                # Genuinely mono device: fall back to a mono open.
                input_stream = sd.InputStream(
                    device=input_dev_id,
                    samplerate=input_sr,
                    channels=1,
                    dtype='float32',
                    blocksize=in_block_size,
                )
                _input_channels = 1
        except Exception as e:
            self.error_occurred.emit(
                f"Failed to open input '{input_name}': {e}")
            return

        # Open output stream, falling back to the device default rate.
        try:
            self._processor.setup_output_resampler(output_sr)
            out_block_size = self._processor.output_resample_size
            output_stream = sd.OutputStream(
                device=output_dev_id,
                channels=2,
                samplerate=output_sr,
                dtype='float32',
                blocksize=out_block_size,
            )
        except Exception:
            try:
                device_default_sr = int(
                    output_device_info.get('default_samplerate', 44100))
                self.status_changed.emit(
                    f"Switching to {device_default_sr}Hz output...")
                self._processor.setup_output_resampler(device_default_sr)
                out_block_size = self._processor.output_resample_size
                output_stream = sd.OutputStream(
                    device=output_dev_id,
                    channels=2,
                    samplerate=device_default_sr,
                    dtype='float32',
                    blocksize=out_block_size,
                )
            except Exception as e:
                try:
                    input_stream.close()
                except Exception:
                    pass
                self.error_occurred.emit(f"Failed to open output: {e}")
                return

        self.status_changed.emit("Processing")
        last_stats_time = time.time()
        # Reused stereo buffer with one sample of headroom: output takes
        # dither around out_block_size (mirrors sounddevice_backend).
        stereo_output = np.empty((out_block_size + 1, 2), dtype=np.float32)

        try:
            with input_stream, output_stream:
                while self._running:
                    try:
                        audio_chunk, overflowed = input_stream.read(
                            self._processor.next_input_block_size())
                    except Exception as e:
                        self.error_occurred.emit(f"Input read failed: {e}")
                        return
                    if overflowed:
                        _logger.warning("Input buffer overflow")
                    if audio_chunk is None or len(audio_chunk) == 0:
                        continue
                    # Downmix to mono in software (mean of L/R), matching
                    # the old PyAudio path. Never rely on a mono device
                    # open (see note at stream open).
                    if _input_channels > 1:
                        audio_chunk = audio_chunk.mean(axis=1).astype(np.float32)
                    else:
                        audio_chunk = audio_chunk.flatten()
                    try:
                        audio_output = self._processor.process_chunk(audio_chunk)
                    except Exception as e:
                        self.error_occurred.emit(f"Processing failed: {e}")
                        return
                    if audio_output is not None:
                        # Write exactly what the pipeline produced: padding
                        # with zeros would insert silence and shift A/V sync.
                        n = min(len(audio_output), len(stereo_output))
                        stereo_output[:n, 0] = audio_output[:n]
                        stereo_output[:n, 1] = audio_output[:n]
                        try:
                            output_stream.write(stereo_output[:n])
                        except Exception as e:
                            self.error_occurred.emit(f"Output write failed: {e}")
                            return

                    current_time = time.time()
                    if current_time - last_stats_time >= 0.1:  # Every 100ms
                        stats = self._processor.get_stats()
                        self.stats_updated.emit(stats)
                        last_stats_time = current_time
        finally:
            try:
                input_stream.close()
            except Exception:
                pass
    
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

        if self._processor is not None:
            try:
                self._processor.close()
            except Exception:
                pass
        self._processor = None
        self.status_changed.emit("Stopped")
    
    @property
    def is_running(self) -> bool:
        """Check if worker is currently running."""
        return self._running and self.isRunning()
