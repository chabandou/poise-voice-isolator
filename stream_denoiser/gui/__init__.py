"""
Poise Voice Isolator - GUI Package

Exports the main entry point function.
"""
import os
import sys

from PyQt6 import sip
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QByteArray, QProcess, QSharedMemory
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

from .main_window import MainWindow
from ..logging_config import get_logger

_logger = get_logger(__name__)

# Global reference to main window for single-instance handling
_main_window = None
_shared_memory = None

# Flags a restarted Poise starts with (see request_restart).
FLAG_RESTART_SETTINGS = "--restarted-on-settings"
FLAG_RESTART_RESUME = "--restarted-isolating"
_restart_args = None   # set: start Poise again once this one has quit


def request_restart(resume: bool) -> None:
    """Start Poise again once this one has quit (the caller quits it):
    back on the Settings page, and isolating again if `resume`."""
    global _restart_args
    args = [a for a in sys.argv[1:]
            if a not in (FLAG_RESTART_SETTINGS, FLAG_RESTART_RESUME)]
    args.append(FLAG_RESTART_SETTINGS)
    if resume:
        args.append(FLAG_RESTART_RESUME)
    _restart_args = args


def _restart_command(args):
    """(program, arguments) that start this Poise again."""
    if getattr(sys, "frozen", False):
        return sys.executable, list(args)
    script = os.path.abspath(sys.argv[0])
    if os.path.basename(script) == "__main__.py":   # python -m ...gui
        return sys.executable, ["-m", __name__] + list(args)
    return sys.executable, [script] + list(args)


def _restart() -> None:
    """Hand over to a new Poise: the single-instance lock goes first, or
    the new one would find this one and only bring it to the front."""
    if _local_server is not None:
        _local_server.close()
    if _shared_memory is not None and _shared_memory.isAttached():
        _shared_memory.detach()
    program, args = _restart_command(_restart_args)
    ok, _ = QProcess.startDetached(program, args, os.getcwd())
    if ok:
        _logger.info("Restarting Poise")
    else:
        _logger.error(f"Could not restart Poise ({program} {args})")
_local_server = None


def delete_window(window) -> None:
    """Delete the window now, while Python is whole. Left alive, it goes
    in PyQt's exit sweep, which walks sip's map of wrappers: tearing the
    window down there runs our hideEvents and event filters, and the
    wrappers they make can grow the map under the walk (an access
    violation as Poise exits, now and then)."""
    if window is not None and not sip.isdeleted(window):
        sip.delete(window)

def _send_activate_message():
    """Send message to existing instance to activate its window."""
    socket = QLocalSocket()
    socket.connectToServer("poise.voiceisolator.singleinstance")
    if socket.waitForConnected(1000):
        socket.write(QByteArray(b"activate"))
        socket.flush()
        socket.waitForBytesWritten(1000)
        socket.disconnectFromServer()
        return True
    return False

def _is_already_running() -> bool:
    """Check if another instance is already running."""
    global _shared_memory
    
    # Use a unique key for the shared memory
    key = "poise.voiceisolator.singleinstance"
    
    # Try to create shared memory - if it already exists, another instance is running
    _shared_memory = QSharedMemory(key)
    
    if _shared_memory.attach():
        # Another instance exists
        _logger.info("Detected existing instance via shared memory attachment.")
        _shared_memory.detach()
        return True
    
    # Create the shared memory to mark this instance as running
    if not _shared_memory.create(1):
        # Failed to create, might mean another instance exists
        _logger.info("Failed to create shared memory segment - another instance likely exists.")
        return True
    
    return False

def _setup_local_server(window: MainWindow):
    """Setup local server to receive messages from other instances."""
    global _local_server
    
    # Remove any existing server with the same name
    QLocalServer.removeServer("poise.voiceisolator.singleinstance")
    
    _local_server = QLocalServer()
    
    def handle_new_connection():
        """Handle connection from another instance."""
        socket = _local_server.nextPendingConnection()
        if socket:
            def handle_read():
                _handle_client_message(socket, window)
            socket.readyRead.connect(handle_read)
    
    _local_server.newConnection.connect(handle_new_connection)
    _local_server.listen("poise.voiceisolator.singleinstance")

def _handle_client_message(socket: QLocalSocket, window: MainWindow):
    """Handle message from another instance."""
    data = socket.readAll()
    if data == b"activate":
        window.bring_to_front()
    socket.disconnectFromServer()

# Harmless Qt noise dropped from the log. setPointSize(-1): Qt style code
# copies the point size of a font that our stylesheet sizes in px (which
# is -1 by definition) and Qt rejects the value, leaving the font as is.
_QT_NOISE = ("QFont::setPointSize: Point size <= 0",)
_qt_handler = None  # keep the installed callable alive


def install_qt_message_handler():
    """Route Qt's own messages into the app log (Logs page, log file).

    Qt otherwise writes straight to stderr, which bypasses the log and
    is invisible in the windowed Windows build.
    """
    global _qt_handler
    import logging
    from PyQt6.QtCore import QtMsgType, qInstallMessageHandler

    qt_logger = get_logger("qt")
    levels = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }

    def handler(mode, context, message):
        if message.startswith(_QT_NOISE):
            return
        qt_logger.log(levels.get(mode, logging.WARNING), message)

    _qt_handler = handler
    qInstallMessageHandler(handler)

def _start_logging():
    """Feed the Logs page: this session in memory (every platform) plus the
    usual file log (Linux default; --log-file / POISE_LOG_FILE anywhere)."""
    try:
        import argparse
        import platform
        from .. import __version__
        from ..logging_config import (
            add_log_args, enable_crash_traceback, enable_memory_log,
            ensure_from_log_args,
        )
        enable_memory_log()
        install_qt_message_handler()
        parser = add_log_args(argparse.ArgumentParser(add_help=False))
        args, _ = parser.parse_known_args(sys.argv[1:])
        path = ensure_from_log_args(args)
        enable_crash_traceback()
        _logger.info(f"Poise Voice Isolator {__version__} starting "
                     f"(Python {platform.python_version()}, {platform.platform()})")
        if path:
            _logger.info(f"Logging to {path}")
    except (Exception, SystemExit) as e:  # argparse exits on bad flags
        _logger.warning(f"Log setup incomplete: {e}")

def run_gui():
    """Start the Poise Voice Isolator GUI."""
    global _main_window

    _start_logging()

    # Set AppUserModelID for Windows taskbar icon
    # Set to human-readable name because Windows uses this as the notification header
    # when no start menu shortcut is installed.
    if sys.platform == 'win32':
        try:
            import ctypes
            app_id = 'Poise Voice Isolator'
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
        except Exception as e:
            _logger.warning(f"Failed to set AppUserModelID: {e}")
    
    # Check for existing instance
    if _is_already_running():
        # Try to send activate message to existing instance
        if _send_activate_message():
            # Message sent successfully, exit this instance
            _logger.info("Sent activation message to existing instance. Exiting.")
            sys.exit(0)
        else:
            # Couldn't connect, but shared memory says another instance exists
            # This might be a stale lock, so we'll continue anyway
            _logger.warning("Could not connect to existing instance, but shared memory indicates one may be running.")
    
    # Tell an installer (in-app update or a manual run) Poise is open.
    from ..updates import hold_running_mutex
    hold_running_mutex()

    # Point Qt at the OS cursor theme before it resolves link/hand
    # cursors (XCURSOR_THEME unset == ugly built-in fallback glyphs).
    try:
        from .cursors import ensure_cursor_env
        for _k, _v in ensure_cursor_env().items():
            _logger.info(f"Cursor env default applied: {_k}={_v}")
    except Exception as _e:
        _logger.warning(f"Cursor theme bootstrap skipped: {_e}")

    app = QApplication(sys.argv)
    app.setApplicationName("Poise Voice Isolator")
    app.setOrganizationName("Poise")

    # Apply the persisted theme before creating anything themed
    # (window/taskbar icons included).
    from .settings import get_settings as _get_settings
    from . import themes as _themes
    _themes.set_current(_get_settings().theme)
    
    # Qt6 specific: Set desktop file name to match AppUserModelID
    # This often fixes taskbar icon issues on Windows 11
    if hasattr(app, 'setDesktopFileName'):
        app.setDesktopFileName('Poise Voice Isolator')
    
    # Enable high DPI scaling
    try:
        from PyQt6.QtGui import QHighDpiScaling, QIcon
        from .utils import get_icon_path
        # PyQt6 handles this automatically mostly, but just in case
    except ImportError:
        from PyQt6.QtGui import QIcon
        from .utils import get_icon_path

    # Set icon for the application immediately
    icon_path = get_icon_path()
    if icon_path:
        app_icon = QIcon(icon_path)
        if app_icon.isNull():
            _logger.error(f"Failed to load icon from {icon_path}. File exists but image is invalid.")
        else:
            app.setWindowIcon(app_icon)
            _logger.info(f"App icon set successfully from: {icon_path}")
    else:
        _logger.warning("App icon not found")

    _main_window = MainWindow()
    _main_window.show()

    # Animated, themed tooltips for every widget tip in the window.
    try:
        from .tooltip import install_tooltips
        install_tooltips(app, _main_window)
    except Exception as _e:
        _logger.warning(f"Animated tooltips unavailable: {_e}")
    
    # Setup local server to receive messages from other instances
    _setup_local_server(_main_window)

    # Started again by Poise itself (Reduce motion): pick up where it was.
    _main_window.resume_after_restart(
        settings_page=FLAG_RESTART_SETTINGS in sys.argv,
        isolate=FLAG_RESTART_RESUME in sys.argv)

    _logger.info("Starting Qt application event loop...")
    code = app.exec()
    delete_window(_main_window)
    _main_window = None
    if _restart_args is not None:
        _restart()
    sys.exit(code)

