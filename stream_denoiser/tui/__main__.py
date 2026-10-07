"""
TUI Entry Point

Run with: python -m stream_denoiser.tui
"""
import sys
import os

# Ensure the package is importable (for Nuitka onefile builds)
if __package__ is None or __package__ == '':
    # Running as script, fix import path
    script_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(os.path.dirname(script_dir))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    from stream_denoiser.tui.app import PoiseApp
else:
    # Running as module  
    from .app import PoiseApp

def main(argv=None):
    import argparse
    try:
        from ..constants import ALL_MODELS, DEFAULT_MODEL
        from ..logging_config import (
            add_log_args,
            announce_log_path,
            ensure_from_log_args,
            get_log_file_path,
            enable_crash_traceback,
        )
        parser = argparse.ArgumentParser(description='Poise Voice Isolator TUI')
        parser.add_argument('--model', type=str, default=DEFAULT_MODEL,
                            choices=list(ALL_MODELS))
        add_log_args(parser)
        args, _ = parser.parse_known_args(argv)
        # Set up file logging before the fullscreen TUI takes over stdout.
        try:
            path = ensure_from_log_args(args) or get_log_file_path()
            announce_log_path(path)
            enable_crash_traceback()
        except Exception:
            pass
        app = PoiseApp(model=args.model)
    except Exception:
        app = PoiseApp()
    app.run()

if __name__ == "__main__":
    main()
