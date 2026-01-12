<img src="stream_denoiser/gui/assets/calligraphy_bismillah.png" alt="Bismillah" width="200"/>


# Poise Voice Isolator

A high-performance real-time system audio denoiser and voice isolator that captures system audio, processes it through an ONNX neural network model, and outputs enhanced audio with minimal latency.

![Poise Voice Isolator GUI](stream_denoiser/gui/assets/screenshot.png)

## Features

- **Real-time Processing**: Direct time-domain processing with ~10ms frame latency
- **Voice Activity Detection (VAD)**: performance boost by skipping silence
- **Low Latency**: Lock-free ring buffers for reduced latency
- **WASAPI Loopback Support**: Captures system audio on Windows using PyAudioWPatch
- **VB Cable Integration on windows**: Automatic Windows audio device switching for seamless capture
- **Automatic Resampling**: Handles different input/output device sample rates seamlessly


## Installation

Supported on **Windows** and **Linux**.


### Windows

1. Download the Poise Installer: [Poise_Setup.exe](https://github.com/chabandou/poise-voice-isolator/releases/download/launch/Poise_Setup.exe).
2. Run the installer and follow the on-screen instructions.
3. Launch **Poise Voice Isolator** from your Desktop or Start Menu.

> **Note**: Make sure to download and install [VB Cable](https://vb-audio.com/Cable/index.htm) for loopback audio capture on Windows.

### Linux Binary

Download the prebuilt binary for the TUI directly from GitHub:

```bash
# Download the latest release
curl -L -o poise https://github.com/chabandou/Poise-Voice-Isolator/releases/download/v1.0.0/poise

# Make it executable
chmod +x poise

# Move to your PATH (optional)
sudo mv poise /usr/local/bin/

# Run the TUI
poise
```

or, on **Arch Linux (btw):**

```bash
yay -S poise-bin

# Run the TUI 
poise
```

### Installation from Source (Developers)

Recommended to be done in a seperate conda environment.

```bash
conda create -n poise python=3.10
conda activate poise
```

1. Clone the repository:
```bash
git clone https://github.com/chabandou/poise-voice-isolator.git
cd poise-voice-isolator
```

2. Install required dependencies:
```bash
pip install onnxruntime numpy sounddevice scipy PyQt6

# For Windows system audio capture (recommended):
pip install pyaudiowpatch

# For better resampling performance (optional):
pip install samplerate
```

#### Usage

**CLI Mode:**
Process system audio with default settings (VAD enabled, automatic VB Cable switching):
```bash
# Using the modular package (recommended)
python -m stream_denoiser

# Or using the entry point script
python -m stream_denoiser.cli
```

### Available Options

- `--onnx`: Path to ONNX model file (default: `denoiser_model.onnx`)
- `--input-device`: Input device ID for system audio capture
- `--output-device`: Output device ID for audio playback
- `--no-vad`: Disable Voice Activity Detection
- `--vad-threshold`: VAD threshold in dB (default: -40.0, lower = more sensitive)
- `--atten-lim-db`: Attenuation limit in dB (default: -60.0)
- `--list-devices`: List all available audio devices and exit
- `--no-vb-cable`: Disable automatic VB Cable switching (use current default device)
- `--vb-cable-name`: Custom name for VB Cable device (auto-detected if not specified)


**GUI Mode (windows only):**
```bash
# Run the Poise Voice Isolator GUI
python -m stream_denoiser.gui
```


## Package Structure

```
stream_denoiser/
├── tui/                     # Terminal UI (Linux)
│   ├── __init__.py
│   ├── __main__.py          # TUI entry point
│   ├── app.py               # Main Textual app
│   ├── styles.tcss          # TUI stylesheet
│   └── widgets/             # TUI components
│       ├── device_list.py   # Device selection widget
│       ├── stats_panel.py   # Statistics display
│       └── status_line.py   # Status bar widget
├── gui/                     # Desktop GUI (Windows, PyQt6)
│   ├── __init__.py
│   ├── __main__.py
│   ├── assets/              # Icons and images
│   ├── widgets/             # Custom UI components
│   ├── main_window.py
│   ├── settings.py
│   ├── styles.py
│   ├── system_tray.py
│   └── worker.py            # Audio processing thread
├── backends/                # Audio interface backends
│   ├── pyaudio_backend.py   # Windows/WASAPI support
│   ├── sounddevice_backend.py # Cross-platform support
│   └── platform/            # Platform-specific code
│       ├── linux.py         # PulseAudio integration
│       └── windows.py       # WASAPI support
├── processor.py             # Core ONNX model wrapper
├── vad.py                   # Voice Activity Detection
├── resampler.py             # Audio resampling
├── ring_buffer.py           # Thread-safe audio buffering
├── vb_cable.py              # Virtual cable management (Windows)
├── device_utils.py          # Audio device utilities
├── platform_utils.py        # Platform detection
├── constants.py             # Global configurations
├── cli.py                   # Command-line interface
├── logging_config.py        # Logging configuration
├── backend_detection.py     # Backend availability checks
├── __init__.py
└── __main__.py
```

## Processing Flow

```
┌─────────────────┐
│  System Audio   │
│    (Input)      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Input Buffer    │
│ (Ring Buffer)   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Resampler       │◄─── Convert to 48kHz if needed
│ (if needed)     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Frame Splitter  │◄─── 480 samples (10ms @ 48kHz)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ VAD Check       │◄─── Skip processing if silence
│ (optional)      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ ONNX Inference  │◄─── Denoiser model processing
│ (with state)    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Post-processing │◄─── Normalize, clip, remove DC
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Output Buffer   │
│ (Ring Buffer)   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Audio Output   │
│   (Speakers)    │
└─────────────────┘
```

## Model Requirements

The ONNX model should have the following interface:

**Inputs:**
- `input_frame`: Float32 array of shape `[480]` (480 samples @ 48kHz)
- `states`: Float32 array of shape `[45304]` (model internal state)
- `atten_lim_db`: Float32 scalar (attenuation limit in dB)

**Outputs:**
- `enhanced_audio`: Float32 array (variable length, normalized to 480 samples)
- `new_states`: Float32 array of shape `[45304]` (updated state for next frame)
- `lsnr`: Float32 scalar (optional, signal-to-noise ratio estimate)

## Statistics

During processing, the script/GUI displays real-time statistics:
- **RTF**: Real-time factor (processing time / frame duration, <1.0 means real-time capable)
- **Avg**: Average processing time per frame in milliseconds
- **VAD bypass**: Percentage of frames skipped due to silence
- **Buffer status**: Input/output buffer fill levels

## Troubleshooting

### No audio devices found
- Run `python -m stream_denoiser --list-devices` to see available devices
- On Windows, ensure `pyaudiowpatch` is installed for WASAPI loopback support

### High latency
- Reduce `BUFFER_CAPACITY_RATIO` in the code (currently 0.1 = 100ms)
- Ensure VAD is enabled to reduce processing load
- Check that your system can process frames faster than real-time (RTF < 1.0)

### Audio dropouts
- Reduce processing load (enable VAD, reduce model complexity)
- Check system CPU usage and close unnecessary applications, the model can be resource hungry.

### Linux Troubleshooting

**Error: `cannot enable executable stack as shared object requires: Invalid argument`**

This error occurs on newer Linux kernels (e.g., Arch Linux) where security policies prevent shared libraries from having an executable stack. It typically affects `onnxruntime`.

**Fix:**
Clear the executable stack flag on the ONNX Runtime library using `execstack` or `patchelf`.

1. Install `patchelf`:
   ```bash
   sudo pacman -S patchelf    # Arch Linux
   sudo apt install patchelf  # Ubuntu/Debian
   ```

2. Locate the `onnxruntime` shared object file and clear the flag:
   ```bash
   # Find the path (example path for conda environment 'poise')
   find ~/miniforge3/envs/poise/lib/ -name "onnxruntime_pybind11_state.so"
   
   # Apply the fix
   patchelf --clear-execstack /path/to/onnxruntime_pybind11_state.so
   ```

---

**Error: `malloc(): invalid size (unsorted)` or crash on startup**

This crash occurs when PortAudio uses the JACK backend, which has memory corruption issues. The solution is to rebuild PortAudio with PulseAudio support.

**Fix - Rebuild PortAudio:**

1. Install build dependencies:
   ```bash
   sudo pacman -S base-devel cmake libpulse alsa-lib   # Arch
   sudo apt install build-essential cmake libpulse-dev libasound2-dev  # Ubuntu
   ```

2. Clone and build PortAudio with PulseAudio:
   ```bash
   git clone https://github.com/PortAudio/portaudio.git /tmp/portaudio
   cd /tmp/portaudio && mkdir build && cd build
   cmake .. -DCMAKE_BUILD_TYPE=Release -DPA_USE_ALSA=ON -DPA_USE_JACK=OFF -DPA_USE_PULSEAUDIO=ON -DCMAKE_INSTALL_PREFIX=/usr/local
   make -j$(nproc)
   sudo make install && sudo ldconfig
   ```

3. Reinstall sounddevice:
   ```bash
   pip uninstall sounddevice && pip install sounddevice --no-cache-dir
   ```

4. **Important:** Set `LD_LIBRARY_PATH` before running:
   ```bash
   export LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH
   python -m stream_denoiser
   ```

   To make permanent:
   ```bash
   echo 'export LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH' >> ~/.bashrc
   ```

---

**No audio output or echo/duplicate audio**

The denoiser automatically creates a null sink to capture system audio without echo. If audio isn't working:

1. **Check current default sink:**
   ```bash
   pactl get-default-sink
   ```
   
2. **If stuck on `Denoiser_Capture` after a crash:**
   ```bash
   pactl set-default-sink alsa_output.pci-0000_00_1f.3.analog-stereo
   ```
   (Replace with your actual sink name from `pactl list sinks short`)

3. **Remove leftover null sink:**
   ```bash
   pactl unload-module module-null-sink
   ```

---

**Audio routing (how it works)**

On Linux, the denoiser:
1. Creates a null sink (`Denoiser_Capture`)
2. Sets it as the default (apps send audio there)
3. Captures from the null sink's monitor
4. Outputs processed audio to your real speakers
5. Restores original routing on exit

This eliminates echo because original audio goes to a silent null sink.

## Special thanks to
GTCRN implementation [here](https://github.com/Xiaobin-Rong/gtcrn#).

yuyun2000 for the speech enhancement [model](https://github.com/yuyun2000/SpeechDenoiser).


## License

MIT License

## Contributing

I have no specific method of contribution, but I'm open to ideas, and all contributions are welcome.


