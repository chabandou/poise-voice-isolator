"""
Poise Voice Isolator - System Tray

System tray icon integration with context menu.
"""
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu, QApplication
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtCore import pyqtSignal
from typing import Optional
import os
from .utils import get_icon_path



class SystemTray(QSystemTrayIcon):
    """
    System tray icon and menu for background operation.
    """
    
    restore_requested = pyqtSignal()
    start_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    quit_requested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Determine icon path
        icon_path = get_icon_path()
        if icon_path:
            self.setIcon(QIcon(icon_path))
        else:
            # Fallback
            self.setIcon(QIcon.fromTheme("audio-input-microphone"))
            
        self.setToolTip("Poise Voice Isolator")
        
        self._setup_menu()
        self.activated.connect(self._on_activated)
    
    def _setup_menu(self):
        """create context menu."""
        menu = QMenu()
        
        # Start/Stop action
        self._start_stop_action = QAction("Start Isolation", menu)
        self._start_stop_action.triggered.connect(self._on_start_stop)
        menu.addAction(self._start_stop_action)
        
        menu.addSeparator()
        
        # Show Window
        show_action = QAction("Show Window", menu)
        show_action.triggered.connect(self.restore_requested.emit)
        menu.addAction(show_action)
        
        menu.addSeparator()
        
        # Quit
        quit_action = QAction("Quit Poise", menu)
        quit_action.triggered.connect(self.quit_requested.emit)
        menu.addAction(quit_action)
        
        self.setContextMenu(menu)
    
    def set_processing_state(self, is_processing: bool):
        """Update menu state based on processing status."""
        if is_processing:
            self._start_stop_action.setText("Stop Denoising")
            self.setToolTip("Poise Voice Isolator (Running)")
        else:
            self._start_stop_action.setText("Start Isolation")
            self.setToolTip("Poise Voice Isolator (Idle)")
    
    def _on_start_stop(self):
        """Handle start/stop action."""
        if self._start_stop_action.text().startswith("Start"):
            self.start_requested.emit()
        else:
            self.stop_requested.emit()
    
    def _on_activated(self, reason):
        """Handle tray icon activation (click)."""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.restore_requested.emit()
            
    def notify(self, title: str, message: str, is_error: bool = False):
        """Show a system notification."""
        icon = QSystemTrayIcon.MessageIcon.Critical if is_error else QSystemTrayIcon.MessageIcon.Information
        self.showMessage(title, message, icon, 3000)
