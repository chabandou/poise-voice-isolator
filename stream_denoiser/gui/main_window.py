"""
Poise Voice Isolator - Main Window

Main GUI application window assembling all widgets and logic.
"""
import sys
import os
from typing import Optional

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QGroupBox, QSlider, QCheckBox, 
    QMessageBox, QSystemTrayIcon, QApplication,
    QScrollArea, QFrame, QSizePolicy, QGraphicsDropShadowEffect
)
from PyQt6.QtCore import Qt, QTimer, QEvent
from PyQt6.QtGui import QIcon, QCloseEvent, QColor

from .styles import POISE_STYLESHEET, COLORS
from .settings import get_settings
from ..constants import MSG_PROCESSING_STARTED, MSG_PROCESSING_STOPPED
from .worker import AudioWorker
from .system_tray import SystemTray
from .widgets.toggle_button import ToggleButton
from .widgets.device_selector import DeviceSelector
from .widgets.stats_panel import StatsPanel
from ..logging_config import get_logger
from .utils import get_icon_path

_logger = get_logger(__name__)


class MainWindow(QMainWindow):
    """
    Main application window for Poise Voice Isolator.
    """
    
    def __init__(self):
        super().__init__()
        
        self.settings = get_settings()
        self.worker: Optional[AudioWorker] = None
        self.tray: Optional[SystemTray] = None
        self._forcing_quit = False
        
        # Setup UI

        self.setWindowTitle("Poise Voice Isolator")
        
        # Set App Icon
        icon_path = get_icon_path()
        if icon_path:
            app_icon = QIcon(icon_path)
            self.setWindowIcon(app_icon)
            # Also set for the application instance to ensure it propagates
            QApplication.instance().setWindowIcon(app_icon)
            
        self.resize(500, 300) # Increased width for horizontal layout
        self.setMinimumSize(500, 300)
        self.setStyleSheet(POISE_STYLESHEET)
        
        self.setup_ui()

        self.setup_worker()
        self.setup_tray()
        
        # Load persistent state
        self.restore_state()
        
        # Status update timer
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.reset_status)
        self.status_timer.setSingleShot(True)
    
    def setup_ui(self):
        """Initialize all UI components."""
        # Main wrapper to hold scroll area and fixed footer
        main_wrapper = QWidget()
        main_layout = QVBoxLayout(main_wrapper)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        self.setCentralWidget(main_wrapper)

        # Scroll Area for Content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Transparent background for scroll area
        scroll.setStyleSheet("QScrollArea { background: transparent; } QWidget#content_widget { background: transparent; }")
        
        main_layout.addWidget(scroll)
        
        content_widget = QWidget()
        content_widget.setObjectName("content_widget")
        scroll.setWidget(content_widget)
        
        layout = QVBoxLayout(content_widget)
        layout.setSpacing(15) 
        layout.setContentsMargins(20, 20, 20, 20)
        
        # --- Header (Centered) ---
        header_layout = QHBoxLayout()
        header_layout.setSpacing(4) # Mimic single space
        header_layout.addStretch()
        title_label = QLabel("Poise Voice Isolator")
        title_label.setObjectName("title")
        # Removed text bottom alignment so they align centrally by default
        
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        
        # --- Main Toggle Button ---
        btn_layout = QHBoxLayout()
        self.toggle_btn = ToggleButton()
        
        # Add glow effect to button
        self.btn_shadow = QGraphicsDropShadowEffect(self)
        self.btn_shadow.setBlurRadius(40)
        self.btn_shadow.setColor(QColor(165, 243, 252, 80)) # Lighter Cyan glow
        self.btn_shadow.setOffset(0, 5)
        self.toggle_btn.setGraphicsEffect(self.btn_shadow)
        
        self.toggle_btn.toggled_state.connect(self.toggle_processing)
        btn_layout.addStretch()
        btn_layout.addWidget(self.toggle_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        layout.addSpacing(15) # Formatting: Extra space below button
        
        # --- Device Selection Group ---
        self.device_group = QGroupBox()
        device_main_layout = QVBoxLayout(self.device_group)
        device_main_layout.setSpacing(10)
        
        # Horizontal row for input/output dropdowns
        devices_row = QHBoxLayout()
        devices_row.setSpacing(20)
        
        self.input_selector = DeviceSelector("Input Device", "input")
        self.input_selector.device_changed.connect(lambda id: setattr(self.settings, 'input_device', id))
        devices_row.addWidget(self.input_selector)
        
        self.output_selector = DeviceSelector("Output Device", "output")
        self.output_selector.device_changed.connect(lambda id: setattr(self.settings, 'output_device', id))
        devices_row.addWidget(self.output_selector)
    
        device_main_layout.addLayout(devices_row)
        
        # VB Cable Auto-switch
        self.vb_cable_check = QCheckBox("Auto-switch Default Playback Device (VB Cable)")
        self.vb_cable_check.setChecked(self.settings.vb_cable_enabled)
        self.vb_cable_check.toggled.connect(self._on_vb_cable_toggled)
        self.vb_cable_check.setToolTip("Automatically switches Windows default playback device to VB Cable input when running")
        device_main_layout.addWidget(self.vb_cable_check)
        
        # Initial state
        self.input_selector.setEnabled(not self.settings.vb_cable_enabled)
        
        layout.addWidget(self.device_group)
        
        # --- Controls & Stats Row ---
        # Combined row for VAD controls and Stats
        
        controls_group = QGroupBox()
        controls_layout = QHBoxLayout(controls_group)
        controls_layout.setSpacing(20)
        
        # Left Side: VAD Controls
        self.vad_panel = QFrame()
        self.vad_panel.setObjectName("vad-panel")
        vad_layout = QVBoxLayout(self.vad_panel)
        vad_layout.setSpacing(10)
        vad_layout.setContentsMargins(12, 12, 12, 12)
        
        # VAD Enable
        self.vad_check = QCheckBox("Enable VAD (Save CPU)")
        self.vad_check.setChecked(self.settings.vad_enabled)
        vad_layout.addWidget(self.vad_check)
        
        # Threshold Slider
        thresh_container = QWidget()
        thresh_layout = QHBoxLayout(thresh_container)
        thresh_layout.setContentsMargins(0,0,0,0)
        
        thresh_label = QLabel("Threshold:")
        self.thresh_val_label = QLabel(f"{self.settings.vad_threshold:.0f} dB")
        self.thresh_val_label.setFixedWidth(50)
        self.thresh_val_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        
        self.thresh_slider = QSlider(Qt.Orientation.Horizontal)
        self.thresh_slider.setRange(-80, -10)
        self.thresh_slider.setValue(int(self.settings.vad_threshold))
        self.thresh_slider.valueChanged.connect(self._on_threshold_changed)
        # Set initial enabled state matching the checkbox
        self.thresh_slider.setEnabled(self.settings.vad_enabled)
        
        thresh_layout.addWidget(thresh_label)
        thresh_layout.addWidget(self.thresh_slider)
        thresh_layout.addWidget(self.thresh_val_label)
        
        # Connect VAD toggle now that slider exists
        self.vad_check.toggled.connect(self._on_vad_toggled)
        vad_layout.addWidget(thresh_container)
        
        vad_layout.addStretch() # Push configs to top
        
        controls_layout.addWidget(self.vad_panel, stretch=3)
        
        # Right Side: Stats Panel (Vertical)
        self.stats_panel = StatsPanel()
        controls_layout.addWidget(self.stats_panel, stretch=2)
        
        layout.addWidget(controls_group)
        layout.addStretch() # Push everything up
        
        # --- Fixed Footer (Outside Scroll) ---
        footer_widget = QWidget()
        footer_layout = QHBoxLayout(footer_widget)
        footer_layout.setContentsMargins(20, 5, 20, 10) # Match side margins of content
        footer_layout.setSpacing(6)
        
        # Status Light
        self.status_light = QLabel()
        self.status_light.setObjectName("status-light")
        self.status_light.setProperty("state", "ready")
        self.status_light.setFixedSize(10, 10)
        
        # Glow for status light
        light_shadow = QGraphicsDropShadowEffect(self)
        light_shadow.setBlurRadius(10)
        light_shadow.setColor(QColor(74, 222, 128, 150))
        light_shadow.setOffset(0, 0)
        self.status_light.setGraphicsEffect(light_shadow)
        
        # Status Text
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("status-text")
        self.status_label.setProperty("state", "ready")
        
        footer_layout.addWidget(self.status_light)
        footer_layout.addWidget(self.status_label)
        footer_layout.addStretch()
        
        main_layout.addWidget(footer_widget)
    
    def setup_worker(self):
        """Initialize audio worker thread."""
        self.worker = AudioWorker()
        
        # Connect signals
        self.worker.started_processing.connect(self._on_worker_started)
        self.worker.stopped_processing.connect(self._on_worker_stopped)
        self.worker.stats_updated.connect(self.stats_panel.update_stats)
        self.worker.status_changed.connect(self.update_status)
        self.worker.error_occurred.connect(self.handle_error)
        
        # Initial config
        self._configure_worker()
    
    def setup_tray(self):
        """Initialize system tray."""
        if self.settings.get(self.settings.KEY_SHOW_TRAY_ICON, True):
            self.tray = SystemTray(self)
            self.tray.restore_requested.connect(self.bring_to_front)
            self.tray.start_requested.connect(self._start_processing)
            self.tray.stop_requested.connect(self._stop_processing)
            self.tray.quit_requested.connect(self._quit_app)
            self.tray.show()
    
    def restore_state(self):
        """Restore previous window state and selections."""
        # Restore window geometry
        geometry = self.settings.load_window_geometry()
        if geometry:
            self.restoreGeometry(geometry)
        
        # Restore devices
        self.input_selector.selected_device_id = self.settings.input_device
        self.output_selector.selected_device_id = self.settings.output_device
    
    def _on_vb_cable_toggled(self, checked):
        """Handle VB Cable auto-switch toggle."""
        self.settings.vb_cable_enabled = checked
        # Disable input selector when VB Cable switch is enabled
        # (Implies we are capturing from VB Cable)
        self.input_selector.setEnabled(not checked)

    def toggle_processing(self, start: bool):
        """Handle toggle button click."""
        if start:
            self._start_processing()
        else:
            self._stop_processing()
    
    def _start_processing(self):
        """Start the audio processing worker."""
        if self.worker.is_running:
            return
            
        self.toggle_btn.set_transitioning(True)
        # Switch glow to Red immediately (sync with button state)
        self.btn_shadow.setColor(QColor(239, 68, 68, 150)) # Red glow
        
        self._configure_worker()
        self.worker.start()
    
    def _stop_processing(self):
        """Stop the audio processing worker."""
        if not self.worker.is_running:
            return
            
        self.toggle_btn.set_transitioning(True)
        # Switch glow back to Cyan immediately
        self.btn_shadow.setColor(QColor(165, 243, 252, 100)) # Lighter Cyan glow
        
        self.worker.stop()
    
    def _configure_worker(self):
        """Pass current UI settings to worker."""
        self.worker.configure(
            onnx_path=self.settings.onnx_model_path,
            input_device=self.input_selector.selected_device_id,
            output_device=self.output_selector.selected_device_id,
            vad_enabled=self.vad_check.isChecked(),
            vad_threshold=self.thresh_slider.value(),
            atten_lim_db=self.settings.atten_lim_db,
            vb_cable_enabled=self.vb_cable_check.isChecked()
        )
    
    def _on_worker_started(self):
        """Called when worker successfully starts."""
        self.toggle_btn.set_transitioning(False)
        self.toggle_btn.set_active(True)
        
        # Disable controls while running
        self.device_group.setEnabled(False)
        
        # Update tray
        if self.tray:
            self.tray.set_processing_state(True)
            self.tray.notify(
                "Poise Started", 
                "Noise cancellation is active."
            )

        _logger.info(MSG_PROCESSING_STARTED)
    
    def _on_worker_stopped(self):
        """Called when worker stops."""
        self.toggle_btn.set_transitioning(False)
        self.toggle_btn.set_active(False)
        
        # Re-enable controls
        self.device_group.setEnabled(True)
        self.stats_panel.reset()
        
        # Update tray
        if self.tray:
            self.tray.set_processing_state(False)

        _logger.info(MSG_PROCESSING_STOPPED)
    
    def _on_threshold_changed(self, value):
        """Handle VAD threshold slider change."""
        self.thresh_val_label.setText(f"{value} dB")
        if not self.worker.is_running:
            self.settings.vad_threshold = float(value)
        # TODO: Support live updates to worker
    
    def _on_vad_toggled(self, checked):
        """Handle VAD checkbox toggle."""
        self.thresh_slider.setEnabled(checked)
        self.settings.vad_enabled = checked
    
    def update_status(self, message: str):
        """Update status bar message."""
        self.status_label.setText(message)
        
        # Update light state
        state = "ready"
        if "Error" in message:
            state = "error"
        elif "Processing" in message or "Started" in message:
            state = "processing"
            
        self.status_light.setProperty("state", state)
        self.status_light.style().unpolish(self.status_light)
        self.status_light.style().polish(self.status_light)

        self.status_label.setProperty("state", state)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        
        self.status_label.style().polish(self.status_label)
        
        _logger.info(f"Status update: {message}")
    
    def reset_status(self):
        """Reset status to ready."""
        if not self.worker.is_running:
            self.update_status("Ready")
    
    def handle_error(self, message: str):
        """Handle error from worker."""
        self.update_status(f"Error: {message}")
        if self.tray:
            self.tray.notify("Poise Error", message, is_error=True)
        else:
            QMessageBox.critical(self, "Error", message)

        _logger.error(f"Error: {message}")
    
    def closeEvent(self, event: QCloseEvent):
        """Handle window close event (minimize to tray logic)."""
        # If minimize to tray is enabled
        if self.settings.minimize_to_tray and self.tray is not None and not self._forcing_quit:
            # Check if we should ask first
            if not self.settings.minimize_to_tray_asked:
                reply = QMessageBox.question(
                    self, 
                    "Minimize to Tray",
                    "Poise will keep running in the system tray.\n\n"
                    "Do you want to minimize to tray instead of exiting?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes
                )
                
                minimize = (reply == QMessageBox.StandardButton.Yes)
                self.settings.minimize_to_tray = minimize
                self.settings.minimize_to_tray_asked = True
            
            if self.settings.minimize_to_tray:
                event.ignore()
                self.hide()
                # Notification removed as requested
                return
        
        # Actually closing
        self._quit_app()
        event.accept()
    
    def bring_to_front(self):
        """Bring window to front and restore if minimized."""
        if sys.platform == 'win32':
            try:
                import ctypes
                hwnd = int(self.winId())
                SW_RESTORE = 9
                ctypes.windll.user32.ShowWindow(hwnd, SW_RESTORE)
                ctypes.windll.user32.SetForegroundWindow(hwnd)
                ctypes.windll.user32.BringWindowToTop(hwnd)
            except Exception:
                pass
        
        self.show()
        self.raise_()
        self.activateWindow()
    
    def _quit_app(self):
        """Clean shutdown."""
        self._forcing_quit = True
        # Save state
        self.settings.save_window_geometry(self.saveGeometry())
        self.settings.sync()
        
        # Stop worker
        if self.worker.is_running:
            self.worker.stop()
            self.worker.wait(2000)
        
        # Clean up shared memory and local server
        try:
            from PyQt6.QtCore import QSharedMemory
            from PyQt6.QtNetwork import QLocalServer
            shared_memory = QSharedMemory("poise.voiceisolator.singleinstance")
            if shared_memory.isAttached():
                shared_memory.detach()
            # Remove local server
            QLocalServer.removeServer("poise.voiceisolator.singleinstance")
        except Exception:
            pass
            
        QApplication.quit()
