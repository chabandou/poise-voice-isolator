"""
Stream Denoiser Constants

Central location for all configuration constants used across the package.
"""

# Audio processing constants
DEFAULT_SAMPLE_RATE = 48000
DEFAULT_FRAME_SIZE = 480
FRAME_DURATION_MS = (DEFAULT_FRAME_SIZE / DEFAULT_SAMPLE_RATE) * 1000  # 10ms

# ONNX model constants
ONNX_STATE_SIZE = 45304

# VAD constants
DEFAULT_VAD_THRESHOLD_DB = -40.0
DEFAULT_VAD_HANG_TIME_MS = 300.0

# Audio processing constants
SOFT_LIMITER_THRESHOLD = 0.98
AUDIO_CLIP_MIN = -1.0
AUDIO_CLIP_MAX = 1.0

# ONNX threading constants
ONNX_INTRA_OP_THREADS = 2
ONNX_INTER_OP_THREADS = 1

# Buffer and timing constants
BUFFER_CAPACITY_RATIO = 0.1  # 100ms of audio
WORKER_SLEEP_TIME_SEC = 0.001  # 1ms
STATS_UPDATE_INTERVAL_SEC = 0.1  # 100ms
STATS_PRINT_INTERVAL_SEC = 1.0  # 1 second

# PowerShell execution constants
POWERSHELL_CHECK_TIMEOUT_SEC = 2
POWERSHELL_DEFAULT_TIMEOUT_SEC = 5
POWERSHELL_MODULE_CHECK_TIMEOUT_SEC = 10
POWERSHELL_MODULE_INSTALL_TIMEOUT_SEC = 30

# Device switching constants
DEVICE_SWITCH_SETTLE_TIME_SEC = 0.2
DEVICE_SWITCH_INIT_DELAY_SEC = 0.8
DEVICE_SWITCH_STREAM_DELAY_SEC = 0.3
OUTPUT_STREAM_RETRY_COUNT = 3
OUTPUT_STREAM_RETRY_DELAY_SEC = 0.5

# Shared Messages
MSG_ONNX_NOT_FOUND = "ONNX model not found: {}"
MSG_NO_BACKEND = "No audio backend available"
MSG_POWERSHELL_UNAVAILABLE = "PowerShell not available - VB Cable switching disabled"
MSG_DEVICE_SWITCH_ERROR = "Error switching device: {}"
MSG_PROCESSING_STARTED = "Processing started"
MSG_PROCESSING_STOPPED = "Processing stopped"
