"""
Poise Voice Isolator - Toggle Button Widget

Animated start/stop toggle button with state indication.
"""
from PyQt6.QtWidgets import QPushButton
from PyQt6.QtCore import pyqtSignal, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QColor


class ToggleButton(QPushButton):
    """
    Custom toggle button for start/stop control.
    
    Changes appearance based on state (start vs stop).
    """
    
    toggled_state = pyqtSignal(bool)  # True = started, False = stopped
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._is_active = False
        self._is_transitioning = False
        
        # Initial state
        self.setText("Start Isolation")
        self.setObjectName("start-button")
        self.setMinimumWidth(200)
        
        # Connect click
        self.clicked.connect(self._on_clicked)
    
    def _on_clicked(self):
        """Handle button click."""
        if self._is_transitioning:
            return
        
        # Toggle state
        self._is_active = not self._is_active
        self._update_appearance()
        self.toggled_state.emit(self._is_active)
    
    def _update_appearance(self):
        """Update button appearance based on state."""
        if self._is_active:
            self.setText("Stop Isolation")
            self.setObjectName("stop-button")
        else:
            self.setText("Start Isolation")
            self.setObjectName("start-button")
        
        # Force style update
        self.style().unpolish(self)
        self.style().polish(self)
    
    def set_active(self, active: bool):
        """
        Set the button state programmatically.
        
        Args:
            active: Whether denoising is active
        """
        self._is_active = active
        self._update_appearance()
    
    def set_transitioning(self, transitioning: bool):
        """
        Set transitioning state (disables button during transitions).
        
        Args:
            transitioning: Whether currently transitioning
        """
        self._is_transitioning = transitioning
        self.setEnabled(not transitioning)
        
        if transitioning:
            self.setText("Processing...")
    
    @property
    def is_active(self) -> bool:
        """Check if button is in active (stop) state."""
        return self._is_active
