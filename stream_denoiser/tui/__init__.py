"""
Poise Voice Isolator TUI

Terminal User Interface for Linux using Textual.
"""
from .app import PoiseApp

__all__ = ['PoiseApp', 'main']


def main():
    """Entry point for the 'poise' command."""
    app = PoiseApp()
    app.run()
