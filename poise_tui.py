#!/usr/bin/env python3
"""
Poise Voice Isolator - TUI Entry Point

This is the top-level entry script for Nuitka builds.
"""
import sys


def _parse_args(argv=None):
    import argparse
    from stream_denoiser.constants import ALL_MODELS, DEFAULT_MODEL
    from stream_denoiser.logging_config import add_log_args

    parser = argparse.ArgumentParser(description='Poise Voice Isolator TUI')
    parser.add_argument('--model', type=str, default=DEFAULT_MODEL,
                        choices=list(ALL_MODELS),
                        help=f'Denoising engine to use (default: {DEFAULT_MODEL})')
    add_log_args(parser)
    args, _ = parser.parse_known_args(argv)
    return args


def main(argv=None):
    from stream_denoiser.tui.app import PoiseApp
    from stream_denoiser.logging_config import (
        ensure_from_log_args,
        announce_log_path,
        get_log_file_path,
    )

    # File logging must be set up BEFORE the fullscreen TUI takes over
    # stdout, and its path announced while the console is still visible.
    # Never let logging setup break startup (e.g. read-only home).
    try:
        args = _parse_args(argv if argv is not None else sys.argv[1:])
    except Exception:
        args = None
    try:
        path = ensure_from_log_args(args) if args is not None else None
        if path is None:
            path = get_log_file_path()
        announce_log_path(path)
    except Exception:
        args = None
        pass

    model = getattr(args, 'model', None)
    app = PoiseApp(model=model) if model else PoiseApp()
    app.run()

if __name__ == "__main__":
    main()
