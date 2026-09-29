"""
Poise Voice Isolator TUI

Terminal User Interface for Linux using Textual.
"""
from .app import PoiseApp

__all__ = ['PoiseApp', 'main']


def main():
    """Entry point for the 'poise' command."""
    import argparse
    from ..constants import ALL_MODELS, DEFAULT_MODEL
    parser = argparse.ArgumentParser(description='Poise Voice Isolator TUI')
    parser.add_argument('--model', type=str, default=DEFAULT_MODEL,
                        choices=list(ALL_MODELS),
                        help=f'Denoising engine to use (default: {DEFAULT_MODEL})')
    args = parser.parse_args()
    app = PoiseApp(model=args.model)
    app.run()
