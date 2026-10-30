"""
Stream Denoiser Constants

Central location for all configuration constants used across the package.
"""
import os
import sys

# Audio processing constants
DEFAULT_SAMPLE_RATE = 48000
PULSE_TARGET_SR = 48000  # Linux pulse-simple path is fixed 48 kHz float32

# Linux PipeWire node (backends/pipewire_backend.py): Poise as a virtual
# sink inside the PipeWire graph, with a fixed delay to the sound card.
PW_NODE_NAME = "Poise_Isolator"
PW_NODE_DESCRIPTION = "Poise Voice Isolator"
# Largest graph cycle (samples at 48 kHz) the delay is sized for; asked of
# PipeWire as node.latency, so the cycle stays at or below it.
PW_QUANTUM = 512
# Time the inference thread gets per frame beyond the cycle itself
# (samples, 1024 = 21 ms); a frame later than this plays unprocessed.
# Override with POISE_PW_MARGIN_MS.
PW_MARGIN_SAMPLES = 1024
# Crossfade between processed and unprocessed audio (samples).
PW_FADE_SAMPLES = 64
# Linux backend: "auto" (PipeWire node when available, else pulse-simple),
# "pipewire" or "pulse". Override with POISE_BACKEND or --backend.
LINUX_BACKENDS = ("auto", "pipewire", "pulse")

# Windows native audio path (backends/wasapi_backend.py): CABLE Output to
# the speakers through poise_wasapi.dll, the same fixed-delay core.
# Time the inference thread gets per frame (samples); a frame later than
# this plays unprocessed; it adds to the fixed delay. Override with
# POISE_WIN_MARGIN_MS. In the UI's process inference waits for the GIL
# behind the UI: 21 ms (an 11 ms margin let 69 frames in 2 minutes play
# unprocessed with a busy UI under load). In the audio process
# (audio_host) nothing else holds it, and inference under MMCSS takes
# p99 4 ms even with every core busy: 5 ms played every frame processed
# under full load and cut the A/V offset by 19 ms. The CLI keeps 21 ms:
# it prints its stats and log on the inference thread, and with every
# core busy a console write takes up to 30 ms (5 ms let frames play
# unprocessed there; measurements/windows-latency.md, section 13).
WIN_MARGIN_SAMPLES = 1024
WIN_PROCESS_MARGIN_SAMPLES = 256
WIN_FADE_SAMPLES = PW_FADE_SAMPLES
# Clock-bridge headroom for capture packets that arrive late (samples).
WIN_FIFO_SAFETY_SAMPLES = 240
# Audio kept queued for the speakers (samples); 0 = the whole WASAPI
# buffer.
WIN_RENDER_FILL_SAMPLES = 0
# Windows backend: "auto" (native path when available, else PortAudio),
# "wasapi" or "portaudio". Override with POISE_BACKEND or --backend.
WINDOWS_BACKENDS = ("auto", "wasapi", "portaudio")
BACKEND_ENV = "POISE_BACKEND"     # picks the backend on Linux and Windows
DEFAULT_FRAME_SIZE = 480

# Model / engine selection
MODEL_DEEPFILTERNET3 = "deepfilternet3"
MODEL_GTCRN = "gtcrn"
MODEL_RNNOISE = "rnnoise"
ALL_MODELS = (MODEL_DEEPFILTERNET3, MODEL_GTCRN, MODEL_RNNOISE)
DEFAULT_MODEL = MODEL_DEEPFILTERNET3
# The vendored model files (here, not in engines/, so the UI can name
# them without loading the engines and numpy).
DEFAULT_DF3_ONNX = 'denoiser_model_df3.onnx'
GTCRN_ONNX = 'gtcrn.onnx'

# Display info per model (single source for TUI picker, GUI tooltips, ...).
# Future engines only need an entry here to show up everywhere.
MODEL_INFO = {
    MODEL_DEEPFILTERNET3: {
        "label": "DeepFilterNet3",
        # Picker modal: quality/CPU tradeoff.
        "picker_blurb": "Best isolation · medium CPU load",
        # GUI model card: plain-language summary.
        "card_blurb": "Best isolation · medium CPU load.",
        # Performance panel: processing pipeline (independent).
        "blurb": "Frequency domain (STFT) · ONNX Runtime",
        # The engine's required_frame_size at 48 kHz, for the UI to show
        # without loading the engine (test_engines keeps them equal).
        "frame_size": 512,
    },
    MODEL_GTCRN: {
        "label": "GTCRN",
        "picker_blurb": "Lower quality isolation · Lightest CPU load",
        "card_blurb": "Lower quality isolation · Lightest CPU load.",
        "blurb": "Frequency domain (STFT, 16 kHz) · ONNX Runtime",
        "frame_size": 768,
    },
    MODEL_RNNOISE: {
        "label": "RNNoise",
        "picker_blurb": "Lowest quality isolation · Lighter CPU load",
        "card_blurb": "Lowest quality isolation · Lighter CPU load.",
        "blurb": "Frequency domain (Bark bands) · native librnnoise",
        "frame_size": 480,
    },
}

# RNNoise constants (RNNoise expects float samples in 16-bit range, not [-1, 1])
RNNOISE_SCALE = 32768.0

# AAD constants
DEFAULT_AAD_THRESHOLD_DB = -40.0
DEFAULT_AAD_HANG_TIME_MS = 300.0

# Audio processing constants
SOFT_LIMITER_THRESHOLD = 0.98
AUDIO_CLIP_MIN = -1.0
AUDIO_CLIP_MAX = 1.0

# Fixed makeup gain applied to all output (voiced + AAD-bypassed frames)
# before the soft limiter. Denoisers strip noise energy, so processed
# speech measures quieter than the raw mix at the same sink volume.
# 6 dB ~= x2 amplitude; the limiter + clip stage after it guarantees
# the boosted signal still can't exceed [-1, 1].
OUTPUT_GAIN_DB = 6.0

# ONNX threading constants. On Windows the thread running inference (the
# native path's inference thread, the PortAudio loop) runs under MMCSS,
# but ONNX Runtime's pool threads run at normal priority: with every core
# busy they made DF3 frames take up to 37 ms (p99 23 ms) instead of ~2 ms.
# One thread does all the work on the MMCSS thread itself (p99 4 ms under
# the same load) and is no slower when idle: the model is small.
# POISE_ONNX_THREADS overrides it (measurements).
ONNX_INTRA_OP_THREADS = int(os.environ.get(
    "POISE_ONNX_THREADS", 1 if sys.platform == "win32" else 2))
ONNX_INTER_OP_THREADS = 1

# Stats timing constants
STATS_UPDATE_INTERVAL_SEC = 0.1  # 100ms
STATS_PRINT_INTERVAL_SEC = 1.0  # 1 second

# PowerShell execution constants
POWERSHELL_CHECK_TIMEOUT_SEC = 2
POWERSHELL_DEFAULT_TIMEOUT_SEC = 5
POWERSHELL_MODULE_CHECK_TIMEOUT_SEC = 10
POWERSHELL_MODULE_INSTALL_TIMEOUT_SEC = 120
POWERSHELL_PROVIDER_INSTALL_TIMEOUT_SEC = 60

# Device switching constants
DEVICE_SWITCH_SETTLE_TIME_SEC = 0.2
DEVICE_SWITCH_INIT_DELAY_SEC = 0.8
DEVICE_SWITCH_STREAM_DELAY_SEC = 0.3
DEVICE_SWITCH_SUCCESS_HOLD_SEC = 3.0
OUTPUT_STREAM_RETRY_DELAY_SEC = 0.5

# Shared Messages
MSG_RNNOISE_NOT_FOUND = (
    "RNNoise library (librnnoise) not found: {}\n"
    "Install it with your package manager, e.g. 'sudo pacman -S rnnoise' on Arch."
)
MSG_RNNOISE_WINDOWS_NOT_FOUND = (
    "RNNoise library (rnnoise.dll) not found: {}\n"
    "Reinstall Poise — rnnoise.dll should sit next to Poise.exe."
)
MSG_RNNOISE_LINUX_ONLY = "The RNNoise engine is only supported on Linux and Windows."
# Shown once on first launch (GUI and TUI) and in the GUI's About.
MSG_MUSIC_DISCLAIMER = (
    "Poise can't always completely remove music. Some can pass through, "
    "especially loud music that's close to speech. The output isn't "
    "guaranteed to be permissible, so use your own judgement."
)
MSG_NO_BACKEND = "No audio backend available"
MSG_POWERSHELL_UNAVAILABLE = "PowerShell not available - VB Cable switching disabled"
MSG_DEVICE_SWITCH_ERROR = "Error switching device: {}"
MSG_DEVICE_SWITCHING = "Switching audio device..."
MSG_DEVICE_SWITCHING_FIRST_TIME = (
    "Switching audio device... First time may take a few seconds "
    "(installing AudioDeviceCmdlets)..."
)
MSG_AUDIO_TOOLS_DOWNLOADING = (
    "Downloading audio tools... First time may take a few seconds..."
)
MSG_AUDIO_MODULE_INSTALLING = (
    "Installing AudioDeviceCmdlets... First time may take a few seconds..."
)
MSG_DEVICE_SWITCHED = "Switched to VB-Cable (CABLE Input)"
MSG_PROCESSING_STARTED = "Processing started"
MSG_PROCESSING_STOPPED = "Processing stopped"
