"""
Poise Voice Isolator - GUI Package

Exports the main entry point function.
"""
import sys

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QSharedMemory, QByteArray
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

from .main_window import MainWindow
from ..logging_config import get_logger

_logger = get_logger(__name__)

# Global reference to main window for single-instance handling
_main_window = None
_shared_memory = None
_local_server = None

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

def run_gui():
    """Start the Poise Voice Isolator GUI."""
    global _main_window
    
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
    
    _logger.info("Starting Qt application event loop...")
    sys.exit(app.exec())

