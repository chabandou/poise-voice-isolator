#!/usr/bin/env python3
"""
Poise Voice Isolator - TUI Entry Point

This is the top-level entry script for Nuitka builds.
"""
from stream_denoiser.tui.app import PoiseApp

def main():
    app = PoiseApp()
    app.run()

if __name__ == "__main__":
    main()
