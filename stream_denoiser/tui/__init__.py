"""
Poise Voice Isolator TUI

Terminal User Interface for Linux using Textual.
"""
from .app import PoiseApp

__all__ = ['PoiseApp', 'main']


def main(argv=None):
    """Entry point for the 'poise' command."""
    import argparse
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
    add_log_args(parser)
    args, _ = parser.parse_known_args(argv)
    # Set up file logging before the fullscreen TUI takes over stdout.
    try:
        path = ensure_from_log_args(args) or get_log_file_path()
        announce_log_path(path)
    except Exception:
        pass
    app = PoiseApp(model=args.model)
    app.run()
