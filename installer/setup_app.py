"""PyInstaller entry point for Poise_Setup.exe.

A frozen script cannot use `python -m package` semantics, so the spec
points at this file and it imports the package by its absolute name.
"""
import sys

from installer.bootstrapper.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
