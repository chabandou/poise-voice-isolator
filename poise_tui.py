#!/usr/bin/env python3
"""
Poise Voice Isolator - TUI Entry Point

This is the top-level entry script for Nuitka builds.
"""


def main(argv=None):
    # Single entry logic lives in stream_denoiser.tui:main (TUI plus
    # one-shot --doctor/--reset-audio/--fix-execstack). Do NOT duplicate
    # flag handling here: this script once swallowed those flags with
    # parse_known_args and launched the TUI instead (e.g. `poise --doctor`
    # opened the app rather than printing checks).
    from stream_denoiser.tui import main as tui_main
    tui_main(argv)

if __name__ == "__main__":
    main()
