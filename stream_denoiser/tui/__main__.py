"""
TUI Entry Point

Run with: python -m stream_denoiser.tui
"""
import sys
import os

# Ensure the package is importable (for Nuitka onefile builds)
if __package__ is None or __package__ == '':
    # Running as script, fix import path
    script_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(os.path.dirname(script_dir))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    from stream_denoiser.tui.app import PoiseApp
else:
    # Running as module  
    from .app import PoiseApp

def main():
    import argparse
    try:
        from ..constants import ALL_MODELS, DEFAULT_MODEL
        parser = argparse.ArgumentParser(description='Poise Voice Isolator TUI')
        parser.add_argument('--model', type=str, default=DEFAULT_MODEL,
                            choices=list(ALL_MODELS))
        args, _ = parser.parse_known_args()
        app = PoiseApp(model=args.model)
    except Exception:
        app = PoiseApp()
    app.run()

if __name__ == "__main__":
    main()
