"""
Stream Denoiser Package

Real-time audio denoising using ONNX model inference with support for
WASAPI loopback capture, Voice Activity Detection, and VB Cable switching.

Features:
- Direct time-domain processing (no STFT/ISTFT)
- 480-sample frames at 48kHz (10ms)
- Voice Activity Detection (VAD) for 2-3x performance boost
- Lock-free ring buffers for reduced latency
- Streaming state management for continuous processing
"""

from .constants import (
    DEFAULT_SAMPLE_RATE,
    DEFAULT_FRAME_SIZE,
    DEFAULT_VAD_THRESHOLD_DB,
)
from .ring_buffer import RingBuffer
from .vad import VoiceActivityDetector
from .resampler import StreamingResampler
from .processor import DenoiserAudioProcessor, load_onnx_model
from .vb_cable import VB_CableSwitcher
from .device_utils import (
    list_audio_devices,
    find_loopback_device,
    get_output_device_id,
    validate_output_device,
)
from .cli import main, process_system_audio_realtime
from .gui import run_gui

__version__ = "1.0.0"

__all__ = [
    # Constants
    "DEFAULT_SAMPLE_RATE",
    "DEFAULT_FRAME_SIZE",
    "DEFAULT_VAD_THRESHOLD_DB",
    # Classes
    "RingBuffer",
    "VoiceActivityDetector",
    "StreamingResampler",
    "DenoiserAudioProcessor",
    "VB_CableSwitcher",
    # Functions
    "load_onnx_model",
    "list_audio_devices",
    "find_loopback_device",
    "get_output_device_id",
    "validate_output_device",
    "process_system_audio_realtime",
    "main",
    "run_gui",
]
