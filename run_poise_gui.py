#!/usr/bin/env python3
"""
Run Poise Voice Isolator (GUI Mode)

Entry point script for the graphical interface.
"""
from stream_denoiser.gui import run_gui

if __name__ == "__main__":
    import ctypes
    import sys
    
    # Set App User Model ID for Windows to show correct icon
    if sys.platform == 'win32':
        try:
            myappid = 'poise.voiceisolator.gui.1.0' # arbitrary string
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass
            
    run_gui()
