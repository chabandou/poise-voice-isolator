#!/usr/bin/env python3
"""
Stream Denoiser - Entry Point Script

This is the main entry point for running the real-time audio denoiser.
It replaces the original stream_denoiser_RT.py with the modular package.

Usage:
    python run_denoiser.py [options]
    
    Or as a module:
    python -m stream_denoiser [options]

For help:
    python run_denoiser.py --help
"""
from stream_denoiser import main

if __name__ == "__main__":
    main()
