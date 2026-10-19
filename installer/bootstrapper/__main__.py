"""Entry point: python -m installer.bootstrapper [options]."""
from __future__ import annotations

import argparse
import os
import sys


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="Poise Setup",
        description="Poise's setup window (fronts the hidden Inno core).")
    parser.add_argument(
        "--mock", action="store_true",
        help="rehearse an install instead of running the core")
    parser.add_argument(
        "--mock-outcome", default="ok",
        choices=["ok", "reboot", "failed", "cancelled"],
        help="how the rehearsal ends (default: ok)")
    parser.add_argument(
        "--core", default="",
        help="path to PoiseCore.exe (default: discover it)")
    parser.add_argument(
        "--dir", default="",
        help="initial install location")
    parser.add_argument(
        "--screenshot", metavar="DIR", default="",
        help="render every screen to PNG in DIR and exit")
    parser.add_argument(
        "--autoplay", action="store_true",
        help="start the rehearsal automatically (with --mock)")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    # A windowed PyInstaller build has no console streams; anything that
    # prints (the preview list, an argparse error) would otherwise crash.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

    args = parse_args(sys.argv[1:] if argv is None else argv)

    if args.screenshot:
        # Deterministic, display-free rendering (also used by the tests).
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QApplication

    from . import brand
    from .engine import Installer, MockInstaller
    from .window import SetupWindow

    app = QApplication([sys.argv[0]])
    app.setApplicationName("Poise Setup")
    app.setOrganizationName("Poise")
    app.setStyle("Fusion")
    brand.load_fonts()
    app.setStyleSheet(brand.stylesheet())
    app.setWindowIcon(QIcon(brand.asset("icon.ico")))

    if args.screenshot:
        window = SetupWindow()
        for path in window.render_pages(args.screenshot):
            print(path)
        return 0

    installer = (MockInstaller(args.mock_outcome) if args.mock
                 else Installer())
    window = SetupWindow(installer, target_dir=args.dir, core_path=args.core)
    window.show()
    if args.mock and args.autoplay:
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(500, window.start_install)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
