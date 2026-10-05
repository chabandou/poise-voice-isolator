"""
Command-Line Interface for Stream Denoiser

Main entry point and argument parsing for the real-time audio denoiser.
Supports both Windows (VB Cable) and Linux (PulseAudio/ALSA).
"""
import os
import sys
import time
import argparse
import traceback
from typing import Optional

from .engines import create_engine, available_models, DEFAULT_DF3_ONNX
from .engines.base import DenoiseEngine

from .constants import (
    DEFAULT_SAMPLE_RATE,
    DEFAULT_FRAME_SIZE,
    DEFAULT_VAD_THRESHOLD_DB,
    DEVICE_SWITCH_INIT_DELAY_SEC,
    MSG_POWERSHELL_UNAVAILABLE,
    ALL_MODELS,
    DEFAULT_MODEL,
    MODEL_DEEPFILTERNET3,
)
from .processor import DenoiserAudioProcessor
from .platform_utils import is_windows, is_linux, get_vb_cable_switcher
from .device_utils import list_audio_devices, find_loopback_device
from .backend_detection import (
    USE_PYAUDIOWPATCH,
    USE_SOUNDDEVICE,
    sd,
    SOUNDDEVICE_ERROR,
    SOUNDDEVICE_INSTALL_HINT,
)
from .logging_config import get_logger

_logger = get_logger(__name__)


def process_system_audio_realtime(engine: DenoiseEngine,
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
        engine: Denoising engine (created via create_engine(); a raw ONNX
            InferenceSession is also accepted for backward compatibility)
        input_device: Input device ID (optional)
        output_device: Output device ID (optional)
        enable_vad: Enable Voice Activity Detection
        vad_threshold_db: VAD threshold in dB
        atten_lim_db: Attenuation limit in dB
        use_vb_cable: Whether to automatically switch devices (VB Cable on Windows, null sink on Linux)
        vb_cable_name: Custom name for VB Cable device (auto-detected if None)
    """
    # Platform-specific audio routing
    vb_cable_switcher = None
    linux_router = None
    
    if use_vb_cable:
        if is_windows():
            # Windows: Use VB Cable
            VBCableSwitcher = get_vb_cable_switcher()
            if VBCableSwitcher is not None:
                cable_name = vb_cable_name or "CABLE Input (VB-Audio Virtual Cable)"
                vb_cable_switcher = VBCableSwitcher(vb_cable_name=cable_name, auto_switch=True)
                if vb_cable_switcher._powershell_available:
                    _logger.info("VB Cable switching enabled - default playback device will be switched automatically")
                    _logger.info("Waiting for device switch to take effect...")
                    time.sleep(DEVICE_SWITCH_INIT_DELAY_SEC)
                else:
                    _logger.warning(MSG_POWERSHELL_UNAVAILABLE)
                    vb_cable_switcher = None
        elif is_linux():
            # Linux: Use null sink routing
            try:
                from .backends.platform.linux import LinuxAudioRouter
                explicit_input = input_device is not None
                linux_router = LinuxAudioRouter(auto_switch=True)
                if linux_router.get_monitor_source_name():
                    _logger.info("Linux audio routing enabled - using null sink for capture")
                    # Override input device to use null sink monitor.
                    # Fail fast when the monitor is not visible to PortAudio:
                    # falling back to the default input would capture silence
                    # while the default sink points at the null sink.
                    null_sink_device_id = linux_router.get_monitor_device_id()
                    if null_sink_device_id is not None:
                        if not explicit_input:
                            input_device = null_sink_device_id
                        _logger.info(f"Using null sink monitor as input device: {null_sink_device_id}")
                    elif explicit_input:
                        _logger.warning(
                            "Null sink monitor not visible to PortAudio - "
                            f"keeping explicit --input-device {input_device}"
                        )
                    else:
                        monitor = linux_router.get_monitor_source_name()
                        linux_router.restore_original_sink()
                        linux_router = None
                        raise RuntimeError(
                            f"Null sink monitor '{monitor}' not visible to PortAudio. "
                            "Not starting: capturing the default input instead would "
                            "record silence. Fixes: run with --list-devices and pass "
                            "--input-device explicitly, check pavucontrol/PipeWire "
                            "Pulse backend, or use --no-vb-cable to keep default capture."
                        )
                else:
                    _logger.warning("Could not set up automatic routing - using default capture")
                    linux_router = None
            except ImportError:
                _logger.info("Linux routing not available - using default capture")
    
    try:
        # Create unified audio processor (frame size follows the engine:
        # e.g. deepfilternet3=512, rnnoise=480)
        processor = DenoiserAudioProcessor(
            engine,
            target_sr=DEFAULT_SAMPLE_RATE,
            frame_size=engine.required_frame_size or DEFAULT_FRAME_SIZE,
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
        if linux_router is not None:
            linux_router.restore_original_sink()


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

  # Use the RNNoise engine (same model as EasyEffects, light on CPU):
  python -m stream_denoiser --model rnnoise

  # Use DeepFilterNet3 (faster, ~2x less CPU):
  python -m stream_denoiser --model deepfilternet3
  
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
    
    parser.add_argument('--model', type=str, default=DEFAULT_MODEL,
                        choices=list(ALL_MODELS),
                        help=f'Denoising engine to use (default: {DEFAULT_MODEL}). '
                             f'rnnoise uses the system librnnoise (same as EasyEffects).')
    parser.add_argument('--onnx', type=str, default=DEFAULT_DF3_ONNX,
                        help='Path to ONNX model file (deepfilternet3 only, '
                             'default: denoiser_model_df3.onnx; a '
                             '<stem>_states.npz sibling is loaded too)')
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
    parser.add_argument('--tui', action='store_true',
                        help='Launch terminal UI (Linux only)')
    parser.add_argument('--doctor', action='store_true',
                        help='Run startup health checks (Linux issues) and exit')
    parser.add_argument('--fix-execstack', action='store_true',
                        help='Clear the ONNX Runtime executable-stack flag with patchelf and exit')
    parser.add_argument('--reset-audio', action='store_true',
                        help='Restore the real default sink and unload leftover Poise null sinks (Linux only)')
    parser.add_argument('--no-health-check', action='store_true',
                        help='Skip the startup health pre-flight (or set POISE_SKIP_HEALTH=1)')
    from .logging_config import add_log_args
    add_log_args(parser)

    args = parser.parse_args()

    # File logging first (Linux only inside ensure_file_logging) so health
    # checks, engine creation, and routing decisions are all captured.
    # The path is announced so users (and remote support) can find it even
    # when the TUI takes over the console or a fallback dir was used.
    from .logging_config import ensure_from_log_args, get_log_file_path
    _path = ensure_from_log_args(args) or get_log_file_path()
    if _path:
        _level = 'DEBUG' if args.verbose else args.log_level
        _logger.info("file log: %s (level=%s)", _path, _level)
        # TUI suppresses console; point the user at the file. In CLI mode
        # the line is harmless and helps locate fallback paths.
        print(f"Logging to {_path}", flush=True)
    elif is_linux() and not args.no_file_log:
        print("Warning: file logging unavailable (no writable log dir found)",
              flush=True)

    # One-shot maintenance commands (no audio needed)
    if args.doctor:
        from .health import run_doctor, format_doctor
        ok, results = run_doctor()
        print(format_doctor(results))
        sys.exit(0 if ok else 1)
    if args.fix_execstack:
        from .health import apply_execstack_fix
        ok, message = apply_execstack_fix()
        print(message)
        sys.exit(0 if ok else 1)
    if args.reset_audio:
        from .health import reset_audio
        ok, message = reset_audio()
        print(message)
        sys.exit(0 if ok else 1)

    # Startup pre-flight: fail fast with fixes instead of cryptic loader
    # errors or native crashes. Bypass with --no-health-check.
    if not args.no_health_check and not os.environ.get("POISE_SKIP_HEALTH"):
        from .health import check_execstack, check_portaudio
        if args.model == MODEL_DEEPFILTERNET3:
            exec_check = check_execstack()
            if not exec_check.ok:
                _logger.error(exec_check.detail)
                if exec_check.fix:
                    _logger.error(exec_check.fix)
                sys.exit(1)
        port_check = check_portaudio()
        if not port_check.ok:
            _logger.error(port_check.detail)
            if port_check.fix:
                _logger.error(port_check.fix)
            sys.exit(1)
    
    # Launch TUI if requested (Linux only)
    if args.tui:
        if not is_linux():
            _logger.error("TUI is only available on Linux. Use the GUI on Windows.")
            sys.exit(1)
        try:
            from .tui import PoiseApp
            app = PoiseApp(model=args.model)
            app.run()
            sys.exit(0)
        except ImportError as e:
            _logger.error(f"Failed to import TUI: {e}")
            _logger.error("Make sure textual is installed: pip install textual")
            sys.exit(1)
    
    if args.list_devices:
        if not USE_SOUNDDEVICE:
            msg = "Device listing requires sounddevice (PortAudio)."
            if SOUNDDEVICE_ERROR:
                msg = f"{msg} Import error: {SOUNDDEVICE_ERROR}"
            if SOUNDDEVICE_INSTALL_HINT:
                msg = f"{msg} {SOUNDDEVICE_INSTALL_HINT}"
            _logger.error(msg)
            sys.exit(1)
        if sd is None:
            msg = "Device listing requires sounddevice (PortAudio)."
            if SOUNDDEVICE_ERROR:
                msg = f"{msg} Import error: {SOUNDDEVICE_ERROR}"
            if SOUNDDEVICE_INSTALL_HINT:
                msg = f"{msg} {SOUNDDEVICE_INSTALL_HINT}"
            _logger.error(msg)
            sys.exit(1)
        
        # On Linux, show PulseAudio sources first if available
        if is_linux():
            try:
                from .backends.platform.linux import list_pulseaudio_sources_formatted, USE_PULSECTL
                if USE_PULSECTL:
                    pulse_sources = list_pulseaudio_sources_formatted()
                    if pulse_sources:
                        print("PulseAudio/PipeWire Sources:")
                        print("=" * 80)
                        print(pulse_sources)
                        print("-" * 80)
                        print()
            except ImportError:
                pass
        
        print("PortAudio Devices:")
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
    
    try:
        # Create denoising engine
        try:
            engine = create_engine(args.model, onnx_path=args.onnx,
                                   atten_lim_db=args.atten_lim_db)
        except (FileNotFoundError, RuntimeError, ValueError) as e:
            _logger.error(f"Error: {e}")
            if args.model != DEFAULT_MODEL:
                _logger.info(f"Available models on this machine: {', '.join(available_models())}")
            sys.exit(1)
        
        # Process system audio
        process_system_audio_realtime(
            engine,
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
