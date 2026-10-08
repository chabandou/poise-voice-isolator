"""
Poise Voice Isolator TUI

Terminal User Interface for Linux using Textual.
"""
from .app import PoiseApp

__all__ = ['PoiseApp', 'main']


def main(argv=None):
    """Entry point for the 'poise' command."""
    import argparse
    import sys
    from ..constants import ALL_MODELS, DEFAULT_MODEL
    from ..logging_config import (
        add_log_args,
        announce_log_path,
        ensure_from_log_args,
        get_log_file_path,
    )
    parser = argparse.ArgumentParser(description='Poise Voice Isolator TUI')
    parser.add_argument('--model', type=str, default=DEFAULT_MODEL,
                        choices=list(ALL_MODELS),
                        help=f'Denoising engine to use (default: {DEFAULT_MODEL})')
    parser.add_argument('--doctor', action='store_true',
                        help='Run startup health checks (Linux issues) and exit')
    parser.add_argument('--fix-execstack', action='store_true',
                        help='Clear the ONNX Runtime executable-stack flag with patchelf and exit')
    parser.add_argument('--reset-audio', action='store_true',
                        help='Restore the real default sink and unload leftover Poise null sinks')
    add_log_args(parser)
    args, _ = parser.parse_known_args(argv)
    # Set up file logging before the fullscreen TUI takes over stdout.
    try:
        path = ensure_from_log_args(args) or get_log_file_path()
        announce_log_path(path)
    except Exception:
        pass
    # One-shot maintenance commands (no TUI needed). The binary IS the TUI,
    # so these must work here and not fall through to app.run().
    if args.doctor:
        from ..health import run_doctor, format_doctor
        ok, results = run_doctor()
        print(format_doctor(results))
        sys.exit(0 if ok else 1)
    if args.fix_execstack:
        from ..health import apply_execstack_fix
        ok, message = apply_execstack_fix()
        print(message)
        sys.exit(0 if ok else 1)
    if args.reset_audio:
        from ..health import reset_audio
        ok, message = reset_audio()
        print(message)
        sys.exit(0 if ok else 1)
    app = PoiseApp(model=args.model)
    app.run()
