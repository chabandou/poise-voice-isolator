"""
Poise Voice Isolator - Audio Processing Worker

QThread-based worker for non-blocking audio processing with signal-based
communication to the GUI.

The audio itself runs in the audio process (audio_host): its own GIL and
garbage collector, so the GUI redrawing cannot hold up inference. This
thread switches the default playback to VB-Cable and mirrors its volume
control onto the output device (both undone here, even if the audio
process dies), checks the devices, runs the session and relays its
status, errors and stats as signals.
"""
import time
import traceback
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from ..audio_host import AudioHost
from ..engines import DEFAULT_DF3_ONNX
from ..backends.platform.windows import VBCableSwitcher
from ..constants import (
    DEFAULT_SAMPLE_RATE, DEVICE_SWITCH_INIT_DELAY_SEC,
    DEVICE_SWITCH_SUCCESS_HOLD_SEC, STATS_UPDATE_INTERVAL_SEC,
    MSG_NO_BACKEND, DEFAULT_MODEL, MSG_DEVICE_SWITCHING, MSG_DEVICE_SWITCHED
)
from ..backend_detection import USE_SOUNDDEVICE, sd
from ..logging_config import get_logger

_logger = get_logger(__name__)

# How long stop() lets the audio process clean up before killing it.
AUDIO_STOP_TIMEOUT_SEC = 5.0


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
        self._vb_cable_switcher: Optional[VBCableSwitcher] = None
        # The audio process: started on the first run, kept between runs
        # (its imports take about a second), ended by shutdown().
        self._host: Optional[AudioHost] = None
    
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
            model: Denoising engine name ("deepfilternet3", "gtcrn" or
                "rnnoise")
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
            # VB-Cable routing is mandatory: Poise captures from CABLE Output,
            # which only receives audio when default playback is CABLE Input.
            # If the automatic switch fails, do NOT start processing — the
            # GUI shows a modal with manual steps instead.
            if self.vb_cable_enabled:
                self.status_changed.emit(MSG_DEVICE_SWITCHING)
                cable_name = self.vb_cable_name or "CABLE Input (VB-Audio Virtual Cable)"
                self._vb_cable_switcher = VBCableSwitcher(
                    vb_cable_name=cable_name,
                    auto_switch=True,
                    status_cb=self.status_changed.emit,
                )

                if not self._vb_cable_switcher._powershell_available:
                    self.error_occurred.emit(
                        "VB-CABLE: PowerShell unavailable, could not switch "
                        "default playback to CABLE Input."
                    )
                    return

                time.sleep(DEVICE_SWITCH_INIT_DELAY_SEC)
                if not self._vb_cable_switcher.switch_to_vb_cable():
                    self.error_occurred.emit(
                        "VB-CABLE: automatic switch to CABLE Input failed. "
                        "Is VB-Cable installed?"
                    )
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
            
            devices = self._pick_devices()
            if devices is None or not self._running:
                return
            if self._vb_cable_switcher is not None:
                # The volume keys now move CABLE Input's slider, which
                # VB-Cable ignores: pass it on to where Poise plays.
                self._vb_cable_switcher.mirror_volume(
                    str(sd.query_devices(devices[1])['name']))
            self._run_session(*devices)

        except Exception as e:
            self.error_occurred.emit(f"Error: {str(e)}\n{traceback.format_exc()}")
        finally:
            self._cleanup()
            self.stopped_processing.emit()

    def _pick_devices(self):
        """(input, output) PortAudio device IDs: CABLE Output and the
        output device. None (with the error emitted) when either is
        missing: VB-Cable is mandatory, a microphone is never captured."""
        from ..device_utils import (
            find_loopback_device,
            get_output_device_id,
            validate_output_device,
        )

        if not USE_SOUNDDEVICE or sd is None:
            self.error_occurred.emit(MSG_NO_BACKEND)
            return None

        try:
            input_dev_id = find_loopback_device(self.input_device)
        except (RuntimeError, ValueError) as e:
            self.error_occurred.emit(f"Input device error: {e}")
            return None

        try:
            devices = sd.query_devices()
            input_device_info = sd.query_devices(input_dev_id)
        except Exception as e:
            self.error_occurred.emit(f"Failed to query audio devices: {e}")
            return None

        input_name = str(input_device_info.get('name', ''))
        if "CABLE OUTPUT" not in input_name.upper():
            self.error_occurred.emit(
                "VB-CABLE: CABLE Output not found "
                f"(found '{input_name or 'unknown'}' instead). "
                "Is VB-Cable installed?"
            )
            return None

        # Output on the same host API as the input.
        try:
            input_host_api = sd.query_hostapis(input_device_info['hostapi'])['name']
        except Exception:
            input_host_api = None
        try:
            output_dev_id = get_output_device_id(
                self.output_device, devices, input_host_api=input_host_api)
            if not validate_output_device(
                    output_dev_id, DEFAULT_SAMPLE_RATE, devices):
                raise ValueError(
                    f"Output device {output_dev_id} does not support "
                    "required configuration")
        except (ValueError, RuntimeError) as e:
            self.error_occurred.emit(str(e))
            return None
        return input_dev_id, output_dev_id

    def _run_session(self, input_dev_id: int, output_dev_id: int) -> None:
        """One session in the audio process, until it ends or stop()."""
        from ..backends.wasapi_backend import windows_backend_preference

        try:
            backend = windows_backend_preference()
        except ValueError as e:
            self.error_occurred.emit(f"Audio backend: {e}")
            return
        config = {
            "backend": backend,
            "model": self.model,
            "aad_enabled": self.aad_enabled,
            "aad_threshold_db": self.aad_threshold,
            "atten_lim_db": self.atten_lim_db,
            "input_device": input_dev_id,
            "output_device": output_dev_id,
        }
        if self.onnx_path and self.onnx_path != DEFAULT_DF3_ONNX:
            config["onnx_path"] = self.onnx_path

        if self._host is None:
            self._host = AudioHost(self._on_host_event)
        self.status_changed.emit("Loading model...")
        try:
            self._host.start(config)
        except RuntimeError as e:
            self.error_occurred.emit(f"Audio process: {e}")
            return
        self.started_processing.emit()

        last_stats = None
        while self._host.running:
            if not self._running:
                self._host.stop(timeout=AUDIO_STOP_TIMEOUT_SEC)
                break
            stats = self._host.stats
            if stats and stats is not last_stats:
                self.stats_updated.emit(dict(stats))
                last_stats = stats
            self.msleep(int(STATS_UPDATE_INTERVAL_SEC * 1000))

    def _on_host_event(self, msg: dict) -> None:
        """AudioHost events (its reader thread; signals are thread-safe)."""
        kind = msg.get("event")
        if kind == "running":
            _logger.info("audio running (backend %s)", msg.get("backend"))
            self.status_changed.emit("Processing")
        elif kind == "error":
            message = msg.get("message") or msg.get("notice") or "unknown"
            self.error_occurred.emit(f"Audio device error: {message}")

    def set_atten_lim_db(self, atten_lim_db: float) -> None:
        """Change the reduction strength; applies live while processing.

        Called from the GUI thread; the audio process applies it on the
        engine's next frame.
        """
        self.atten_lim_db = atten_lim_db
        host = self._host
        if host is not None:
            host.set(atten_lim_db=float(atten_lim_db))

    def set_aad_threshold(self, threshold_db: float) -> None:
        """Change the silence-skipping threshold; applies live while processing.

        Before a session starts, the stored value is what it is built
        with. A run started with silence skipping off has no detector.
        """
        self.aad_threshold = threshold_db
        host = self._host
        if host is not None:
            host.set(aad_threshold_db=float(threshold_db))

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

        self.status_changed.emit("Stopped")

    def shutdown(self) -> None:
        """End the audio process (the app is quitting)."""
        host, self._host = self._host, None
        if host is not None:
            try:
                host.shutdown()
            except Exception as e:
                _logger.debug(f"audio process shutdown failed: {e!r}")
    
    @property
    def is_running(self) -> bool:
        """Check if worker is currently running."""
        return self._running and self.isRunning()
