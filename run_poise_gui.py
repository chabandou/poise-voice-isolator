#!/usr/bin/env python3
"""
Run Poise Voice Isolator (GUI Mode)

Entry point script for the graphical interface.
"""
import os

# Before anything loads numpy: OpenBLAS otherwise commits a buffer per
# core (~160 MB of private memory in each of this process and the audio
# process, which inherits the setting) that Poise never uses; its numpy
# work is per-frame and tiny, and onnxruntime threads on its own. A value
# set by the user still wins.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

if __name__ == "__main__":
    import ctypes
    import multiprocessing
    import sys

    # The audio process (stream_denoiser.audio_host) is this executable
    # started again: in a frozen build this hands it over before the GUI
    # (or Qt) loads.
    multiprocessing.freeze_support()

    from stream_denoiser.gui import run_gui

    # Set App User Model ID for Windows to show correct icon
    if sys.platform == 'win32':
        try:
            myappid = 'poise.voiceisolator.gui.1.1' # arbitrary string
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass
            
    run_gui()
