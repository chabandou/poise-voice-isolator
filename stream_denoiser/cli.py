"""
Command-Line Interface for Stream Denoiser

Main entry point and argument parsing for the real-time audio denoiser.
Supports both Windows (VB Cable) and Linux (PulseAudio via pulse-simple).
"""
import os
import sys
import time
import signal
import argparse
import traceback
from typing import Optional

from .engines import create_engine, available_models, DEFAULT_DF3_ONNX
from .engines.base import DenoiseEngine

from .constants import (
    DEFAULT_AAD_THRESHOLD_DB,
    DEVICE_SWITCH_INIT_DELAY_SEC,
    MSG_POWERSHELL_UNAVAILABLE,
    ALL_MODELS,
    DEFAULT_MODEL,
    MODEL_DEEPFILTERNET3,
    MODEL_GTCRN,
    LINUX_BACKENDS,
    PW_NODE_DESCRIPTION,
    PW_NODE_NAME,
    WINDOWS_BACKENDS,
)
from .platform_utils import is_windows, is_linux, get_vb_cable_switcher
from .device_utils import list_audio_devices, find_loopback_device
from .backend_detection import (
    USE_SOUNDDEVICE,
    sd,
)
from .logging_config import get_logger

_logger = get_logger(__name__)


def _interrupt_on_termination_signals() -> None:
    """Treat SIGTERM/SIGHUP like Ctrl+C so audio routing gets restored.

    Python's default for these signals kills the process on the spot and
    no ``finally`` runs: on Linux the Poise_Capture null sink stays loaded
    and stays the default sink (system audio goes silent). Raised as
    KeyboardInterrupt they take the Ctrl+C path instead: the audio loop
    stops and ``process_system_audio_realtime`` restores the routing.
    Repeats are ignored so a second signal can't cut that cleanup short.
    """
    sigs = [getattr(signal, n) for n in ("SIGTERM", "SIGHUP")
            if hasattr(signal, n)]

    def _handler(signum, frame):
        for sig in sigs:
            signal.signal(sig, signal.SIG_IGN)
        raise KeyboardInterrupt

    for sig in sigs:
        try:
            signal.signal(sig, _handler)
        except (OSError, ValueError):
            pass


def process_system_audio_realtime(engine: DenoiseEngine,
                                 input_device: Optional[int] = None,
                                 output_device: Optional[int] = None,
                                 enable_aad: bool = True,
                                 aad_threshold_db: float = DEFAULT_AAD_THRESHOLD_DB,
                                 atten_lim_db: float = -60.0,
                                 use_vb_cable: bool = True,
                                 vb_cable_name: Optional[str] = None,
                                 source: Optional[str] = None,
                                 sink: Optional[str] = None,
                                 backend: Optional[str] = None) -> None:
    """
    Main entry point for real-time audio processing: sets up the audio
    routing, then runs one session (stream_denoiser.session) until Ctrl+C.

    Args:
        engine: Denoising engine (a DenoiseEngine, from create_engine())
        input_device: Input device ID (Windows only; errors on Linux)
        output_device: Output device ID (Windows only; errors on Linux)
        enable_aad: Enable Audio Activity detection
        aad_threshold_db: AAD threshold in dB
        atten_lim_db: Attenuation limit in dB
        use_vb_cable: Whether to automatically switch devices (VB Cable on Windows, null sink on Linux)
        vb_cable_name: Custom name for VB Cable device (auto-detected if None)
        source: Pulse source name for capture (Linux only)
        sink: Pulse sink name for playback (Linux only)
        backend: Linux backend: "auto" (default; PipeWire node when
            available), "pipewire" or "pulse"; Windows: "auto" (native
            WASAPI path when available), "wasapi" or "portaudio". None
            reads POISE_BACKEND.
    """
    config = {"aad_enabled": enable_aad, "aad_threshold_db": aad_threshold_db,
              "atten_lim_db": atten_lim_db}

    if is_linux():
        # Linux: pulse-simple path (names, never indices).
        if input_device is not None:
            raise ValueError(
                f"Numeric --input-device {input_device} is not supported on "
                "Linux (pulse-simple uses names). Use --source <name> "
                "instead (see --list-devices).")
        if output_device is not None:
            raise ValueError(
                f"Numeric --output-device {output_device} is not supported "
                "on Linux (pulse-simple uses names). Use --sink <name> "
                "instead (see --list-devices).")

        # PipeWire node: Poise becomes a sink inside the PipeWire graph
        # with a fixed delay to the output, and routes itself.
        from .backends.pipewire_backend import (
            linux_backend_preference, select_linux_backend)
        chosen, reason = select_linux_backend(
            linux_backend_preference(backend), source=source)
        _logger.info("Linux backend: %s (%s)", chosen, reason)
        config.update(backend=chosen, input_device=source, output_device=sink)
        if chosen == "pipewire":
            config["route_default"] = use_vb_cable
            _run_session(engine, config)
            return

        linux_router = None
        if use_vb_cable:
            # Linux: Use null sink routing
            try:
                from .backends.platform.linux import LinuxAudioRouter
                linux_router = LinuxAudioRouter(auto_switch=True)
                if linux_router.get_monitor_source_name():
                    _logger.info("Linux audio routing enabled - using null sink for capture")
                else:
                    _logger.warning("Could not set up automatic routing - using default capture")
                    linux_router = None
            except ImportError:
                _logger.info("Linux routing not available - using default capture")

        try:
            if linux_router is not None:
                config.update(
                    routed=True,
                    monitor_source=linux_router.get_monitor_source_name(),
                    fallback_sink=linux_router.original_sink_name)
            _run_session(engine, config)
        finally:
            if linux_router is not None:
                linux_router.restore_original_sink()
        return

    vb_cable_switcher = None
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

    try:
        # CABLE Output is a regular WASAPI capture device; devices are
        # found through sounddevice on both paths.
        if not USE_SOUNDDEVICE:
            raise RuntimeError("No suitable audio backend available")
        from .backends.wasapi_backend import windows_backend_preference
        config["backend"] = windows_backend_preference(backend)
        _run_session(engine, config, devices=(input_device, output_device),
                     vb_cable=vb_cable_switcher)
    finally:
        # Restore original audio device (and stop the volume mirror)
        if vb_cable_switcher is not None:
            vb_cable_switcher.restore_original_device()


def _run_session(engine: DenoiseEngine, config: dict,
                 devices: Optional[tuple] = None, vb_cable=None) -> None:
    """One session until Ctrl+C, its stats printed as it runs.

    ``devices``: the (input, output) PortAudio IDs asked for (Windows),
    resolved the way the PortAudio loop resolves them: CABLE Output and
    an output on its host API. ``vb_cable``: the VBCableSwitcher that
    made CABLE Input the default, whose volume control then drives the
    output device.
    """
    from .device_utils import print_stats, print_final_stats
    from .session import build_processor, run_session

    # Frame size follows the engine: deepfilternet3=512, gtcrn=768,
    # rnnoise=480.
    processor = build_processor(config, engine)
    try:
        if devices is not None:
            from .backends.sounddevice_backend import select_devices
            config["input_device"], config["output_device"] = \
                select_devices(processor, *devices)
            if vb_cable is not None:
                vb_cable.mirror_volume(
                    str(sd.query_devices(config["output_device"])['name']))
        run_session(processor, config, on_stats=print_stats,
                    on_started=_print_started(config, processor))
    except KeyboardInterrupt:
        print("\n\nStopping...")
    except ValueError as e:
        if devices is None:
            raise
        print(f"Error selecting output device: {e}")
        print("\nAvailable output devices:")
        for i, device in enumerate(sd.query_devices()):
            if device['max_output_channels'] > 0:
                host_api = sd.query_hostapis(device['hostapi'])['name']
                print(f"  ID {i}: {device['name']} (API: {host_api})")
        raise
    print_final_stats(processor.get_stats())


def _print_started(config: dict, processor):
    """The session's on_started: what runs where, and how to stop it."""
    paths = {"pipewire": " (PipeWire node)", "wasapi": " (native WASAPI)"}

    def started(backend: str, source, sink) -> None:
        _logger.info("Using %s backend", backend)
        print("\nStarting real-time system audio processing"
              f"{paths.get(backend, '')}...")
        if backend == "pipewire":
            from .backends.pipewire_backend import pick_output_sink
            print(f"Sink: {PW_NODE_DESCRIPTION} ({PW_NODE_NAME})"
                  + ("" if config.get("route_default", True)
                     else " - route apps to it manually"))
            print(f"Output: {pick_output_sink(sink) or 'default'}")
        elif backend == "pulse":
            print(f"Source: {source}")
            print(f"Sink: {sink}")
        elif backend == "wasapi":
            print(f"Input device: {source or 'default'}")
            print(f"Output device: {sink or 'default'}")
        else:
            for kind, device in (("Input", source), ("Output", sink)):
                print(f"{kind} device: {sd.query_devices(device)['name']} "
                      f"(ID: {device})")
            print(f"Output sample rate: {processor.target_sr}Hz")
        print("Press Ctrl+C to stop...\n")

    return started


def main():
    """Main function to run real-time system audio processing."""
    parser = argparse.ArgumentParser(
        description='Denoiser Real-Time System Audio Processing',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process system audio (default with AAD and VB Cable switching):
  python -m stream_denoiser


  # Disable AAD:
  python -m stream_denoiser --no-aad

  # Use the RNNoise engine (same model as EasyEffects, light on CPU):
  python -m stream_denoiser --model rnnoise

  # Use DeepFilterNet3 (faster, ~2x less CPU):
  python -m stream_denoiser --model deepfilternet3

  # Use GTCRN (tiny speech-denoising model, light on CPU; leaves music in):
  python -m stream_denoiser --model gtcrn

  # Adjust AAD sensitivity (lower = more sensitive):
  python -m stream_denoiser --aad-threshold -50

  # Adjust attenuation limit:
  python -m stream_denoiser --atten-lim-db -80

  # List available audio devices:
  python -m stream_denoiser --list-devices

  # Use specific devices (Windows: IDs; Linux: names):
  python -m stream_denoiser --input-device 2 --output-device 1
  python -m stream_denoiser --source Poise_Capture.monitor --sink alsa_output.pci-0000_00_1f.3.analog-stereo

  # Use VB Cable (automatically switches default playback device):
  python -m stream_denoiser (VB Cable switching enabled by default)

  # Disable VB Cable switching:
  python -m stream_denoiser --no-vb-cable

  # Custom VB Cable device name:
  python -m stream_denoiser --vb-cable-name "CABLE Input"
        """
    )

    parser.add_argument('--model', type=str, default=None,
                        choices=list(ALL_MODELS),
                        help=f'Denoising engine to use (default: {DEFAULT_MODEL}; '
                             f'with --tui, the last one picked there). '
                             f'rnnoise uses the system librnnoise on Linux '
                             f'(same as EasyEffects) or the bundled rnnoise.dll '
                             f'on Windows.')
    parser.add_argument('--onnx', type=str, default=DEFAULT_DF3_ONNX,
                        help='Path to ONNX model file (deepfilternet3 only, '
                             'default: denoiser_model_df3.onnx; a '
                             '<stem>_states.npz sibling is loaded too)')
    parser.add_argument('--input-device', type=int, default=None,
                        help='Input device ID (Windows only; Linux uses --source)')
    parser.add_argument('--output-device', type=int, default=None,
                        help='Output device ID (Windows only; Linux uses --sink)')
    parser.add_argument('--source', type=str, default=None,
                        help='Pulse source name for capture (Linux only, '
                             'default: Poise_Capture.monitor)')
    parser.add_argument('--sink', type=str, default=None,
                        help='Pulse sink name for playback (Linux only, '
                             'default: original hardware sink)')
    parser.add_argument('--backend', type=str, default=None,
                        choices=list(dict.fromkeys(LINUX_BACKENDS
                                                   + WINDOWS_BACKENDS)),
                        help='Audio backend: auto (default) runs Poise as a '
                             'PipeWire node (Linux) or on the native WASAPI '
                             'path (Windows) when available, else '
                             'pulse-simple / PortAudio; also POISE_BACKEND')
    parser.add_argument('--no-aad', action='store_true',
                        help='Disable Audio Activity detection')
    parser.add_argument('--aad-threshold', type=float, default=DEFAULT_AAD_THRESHOLD_DB,
                        help=f'AAD threshold in dB (default: {DEFAULT_AAD_THRESHOLD_DB}, lower = more sensitive)')
    # Deprecated aliases: old scripts keep working, hidden from --help.
    parser.add_argument('--no-vad', action='store_true',
                        dest='no_aad', help=argparse.SUPPRESS)
    parser.add_argument('--vad-threshold', type=float,
                        default=DEFAULT_AAD_THRESHOLD_DB,
                        dest='aad_threshold', help=argparse.SUPPRESS)
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
    # The TUI falls back to its saved model, not DEFAULT_MODEL.
    tui_model = args.model
    args.model = args.model or DEFAULT_MODEL

    # File logging first (Linux only inside ensure_file_logging) so health
    # checks, engine creation, and routing decisions are all captured.
    # The path is announced so users (and remote support) can find it even
    # when the TUI takes over the console or a fallback dir was used.
    from .logging_config import (
        ensure_from_log_args,
        get_log_file_path,
        enable_crash_traceback,
    )
    _path = ensure_from_log_args(args) or get_log_file_path()
    if _path:
        enable_crash_traceback()
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
        from .health import check_execstack, check_pulse_backend
        if args.model in (MODEL_DEEPFILTERNET3, MODEL_GTCRN):  # ONNX models
            exec_check = check_execstack()
            if not exec_check.ok:
                _logger.error(exec_check.detail)
                if exec_check.fix:
                    _logger.error(exec_check.fix)
                sys.exit(1)
        if is_linux():
            pulse_check = check_pulse_backend()
            if not pulse_check.ok:
                _logger.error(pulse_check.detail)
                if pulse_check.fix:
                    _logger.error(pulse_check.fix)
                sys.exit(1)

    # Launch TUI if requested (Linux only)
    if args.tui:
        if not is_linux():
            _logger.error("TUI is only available on Linux. Use the GUI on Windows.")
            sys.exit(1)
        try:
            from .tui import PoiseApp
            app = PoiseApp(model=tui_model)
            app.run()
            sys.exit(0)
        except ImportError as e:
            _logger.error(f"Failed to import TUI: {e}")
            _logger.error("Make sure textual is installed: pip install textual")
            sys.exit(1)

    if args.list_devices:
        if is_linux():
            from .backends.platform.linux import (
                list_pulseaudio_sources_formatted,
                list_pulseaudio_sinks_formatted,
                USE_PULSECTL,
            )
            if USE_PULSECTL:
                sinks_txt = list_pulseaudio_sinks_formatted()
                if sinks_txt:
                    print("PulseAudio/PipeWire Sinks (--sink):")
                    print("=" * 80)
                    print(sinks_txt)
                    print("-" * 80)
                    print()
                sources_txt = list_pulseaudio_sources_formatted()
                if sources_txt:
                    print("PulseAudio/PipeWire Sources (--source):")
                    print("=" * 80)
                    print(sources_txt)
                    print("-" * 80)
                    print()
                if not sinks_txt and not sources_txt:
                    print("No PulseAudio sources/sinks found.")
            else:
                _logger.error("Device listing requires pulsectl on Linux.")
                sys.exit(1)
            sys.exit(0)
        if not USE_SOUNDDEVICE:
            _logger.error("Device listing requires sounddevice (Windows).")
            sys.exit(1)
        if sd is None:
            _logger.error("Device listing requires sounddevice (Windows).")
            sys.exit(1)

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

    _interrupt_on_termination_signals()

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
            enable_aad=not args.no_aad,
            aad_threshold_db=args.aad_threshold,
            atten_lim_db=args.atten_lim_db,
            use_vb_cable=not args.no_vb_cable,
            vb_cable_name=args.vb_cable_name,
            source=args.source,
            sink=args.sink,
            backend=args.backend,
        )

    except KeyboardInterrupt:
        print("\n\nProcessing interrupted by user")
    except Exception as e:
        _logger.error(f"Error: {e}")
        _logger.debug(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
