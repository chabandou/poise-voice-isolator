"""
Poise Voice Isolator - Main Window

Dashboard layout matching the v1.1 mockup: sidebar navigation with
Home / Settings / Logs / About pages, glowing power button, toggle
pills, and live stat cards.
"""
import os
import sys
from typing import Optional

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QSlider, QCheckBox, QComboBox,
    QMessageBox, QApplication, QFrame, QStackedWidget,
    QTextEdit, QPushButton, QButtonGroup, QScrollArea,
)
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QIcon, QCloseEvent, QPixmap, QDesktopServices

from .styles import get_stylesheet
from .scaling import init_scaling, sp
from . import themes as theme_store
from .settings import get_settings
from .. import __version__
from ..constants import (
    MSG_PROCESSING_STARTED, MSG_PROCESSING_STOPPED, MODEL_INFO,
)
from .worker import AudioWorker
from .system_tray import SystemTray
from .widgets.phosphor import PhosphorIcon, clear_cache as clear_icon_cache
from .widgets.theme_tile import ThemeTile
from .widgets.power_button import PowerButton
from .widgets.switch import ToggleSwitch
from .widgets.sidebar import Sidebar
from .widgets.device_selector import DeviceSelector
from .widgets.stats_panel import StatsPanel
from ..logging_config import get_logger, get_log_file_path
from .utils import get_icon_path

_logger = get_logger(__name__)

GITHUB_URL = "https://github.com/chabandou/poise-voice-isolator"
ISSUES_URL = "https://github.com/chabandou/poise-voice-isolator/issues"


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
        self._error_state = False

        init_scaling()
        theme_store.set_current(self.settings.theme)

        self.setWindowTitle("Poise Voice Isolator")

        # Set App Icon
        icon_path = get_icon_path()
        if icon_path:
            app_icon = QIcon(icon_path)
            self.setWindowIcon(app_icon)
            # Also set for the application instance to ensure it propagates
            QApplication.instance().setWindowIcon(app_icon)

        self.resize(*self._window_size(1180, 760))
        self.setMinimumSize(*self._window_size(1024, 640))
        self.setStyleSheet(get_stylesheet())

        self.setup_ui()

        self.setup_worker()
        self.setup_tray()

        # Load persistent state
        self.restore_state()

    @staticmethod
    def _lowered(widget: QWidget, offset: int) -> QWidget:
        """Wrap a widget with a fixed top offset."""
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, offset, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(widget)
        return wrap

    @staticmethod
    def _window_size(base_w: int, base_h: int):
        """Scaled window size, clamped to fit the available screen."""
        w, h = sp(base_w), sp(base_h)
        screen = QApplication.instance().primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            w = min(w, int(avail.width() * 0.96))
            h = min(h, int(avail.height() * 0.94))
        return w, h

    # -- layout ------------------------------------------------------------
    def setup_ui(self):
        """Initialize all UI components."""
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setCentralWidget(root)

        self.sidebar = Sidebar()
        self.sidebar.page_requested.connect(self._on_page_requested)
        root_layout.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        for page in (self._build_home_page(),      # 0
                     self._build_settings_page(),  # 1
                     self._build_logs_page(),      # 2
                     self._build_about_page()):    # 3
            scroll = QScrollArea()
            scroll.setObjectName("page-scroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            # The viewport paints the style's light Base color by default;
            # leave it unfilled so the dark window shows through.
            scroll.viewport().setAutoFillBackground(False)
            page.setObjectName("page")
            page.setAutoFillBackground(False)
            scroll.setWidget(page)
            self.stack.addWidget(scroll)
        root_layout.addWidget(self.stack, stretch=1)

    # -- Home page ----------------------------------------------------------
    def _build_home_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(26, 26, 26, 26)
        layout.setSpacing(35)

        # --- Top card: devices + power + VB pill ---
        top_card = QFrame()
        top_card.setObjectName("card")
        top_layout = QVBoxLayout(top_card)
        top_layout.setContentsMargins(78, 57, 66, 57)
        top_layout.setSpacing(26)

        devices_row = QHBoxLayout()
        devices_row.setSpacing(24)

        self.input_selector = DeviceSelector("Input", "input")
        self.input_selector.device_changed.connect(
            lambda id: setattr(self.settings, 'input_device', id))
        # Labels start a third of the power button's height below its
        # top (per the design): offset the whole column downward.
        power_third = sp(210) // 3
        devices_row.addWidget(self._lowered(self.input_selector, power_third),
                              stretch=5,
                              alignment=Qt.AlignmentFlag.AlignTop)

        power_wrap = QVBoxLayout()
        power_wrap.setSpacing(8)
        power_row = QHBoxLayout()
        power_row.addStretch()
        self.power_btn = PowerButton()
        self.power_btn.toggled_state.connect(self.toggle_processing)
        power_row.addWidget(self.power_btn)
        power_row.addStretch()
        power_wrap.addLayout(power_row)
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("status-line")
        self.status_label.setProperty("state", "ready")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        power_wrap.addWidget(self.status_label)
        devices_row.addLayout(power_wrap, stretch=4)

        self.output_selector = DeviceSelector("Output", "output")
        self.output_selector.device_changed.connect(
            lambda id: setattr(self.settings, 'output_device', id))
        devices_row.addWidget(self._lowered(self.output_selector, power_third),
                              stretch=5,
                              alignment=Qt.AlignmentFlag.AlignTop)

        top_layout.addLayout(devices_row)

        # VB-Cable pill row
        vb_pill = QFrame()
        vb_pill.setObjectName("vb-pill")
        vb_layout = QHBoxLayout(vb_pill)
        vb_layout.setContentsMargins(51, 27, 39, 27)
        vb_layout.setSpacing(14)
        vb_layout.addWidget(PhosphorIcon("gear", size=22))
        vb_label = QLabel("Auto-switch Playback Device (VB Cable)")
        vb_layout.addWidget(vb_label)
        vb_layout.addStretch()
        self.vb_switch = ToggleSwitch(checked=self.settings.vb_cable_enabled)
        self.vb_switch.setToolTip(
            "Automatically switches Windows default playback device "
            "to VB Cable input when running")
        self.vb_switch.toggled.connect(self._on_vb_cable_toggled)
        vb_layout.addWidget(self.vb_switch)
        top_layout.addWidget(vb_pill)

        layout.addWidget(top_card, stretch=55)

        # Initial state
        self.input_selector.setEnabled(not self.settings.vb_cable_enabled)

        # --- Bottom row: VAD card + stats card ---
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(35)

        vad_card = QFrame()
        vad_card.setObjectName("card")
        vad_layout = QVBoxLayout(vad_card)
        vad_layout.setContentsMargins(69, 51, 57, 51)
        vad_layout.setSpacing(16)

        vad_header = QHBoxLayout()
        vad_header.setSpacing(14)
        icon_circle = QFrame()
        icon_circle.setObjectName("icon-circle")
        icon_circle.setFixedSize(sp(44), sp(44))
        icon_layout = QHBoxLayout(icon_circle)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        self._badge_icon = self._make_badge_icon()
        icon_layout.addWidget(self._badge_icon)
        vad_header.addWidget(icon_circle)

        vad_titles = QVBoxLayout()
        vad_titles.setSpacing(2)
        vad_title = QLabel("VAD")
        vad_title.setObjectName("card-title")
        vad_titles.addWidget(vad_title)
        vad_sub = QLabel("Voice Activity Detection")
        vad_sub.setObjectName("card-subtitle")
        vad_titles.addWidget(vad_sub)
        vad_header.addLayout(vad_titles)
        vad_header.addStretch()

        self.vad_switch = ToggleSwitch(checked=self.settings.vad_enabled)
        vad_header.addWidget(self.vad_switch)
        vad_layout.addLayout(vad_header)

        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFrameShape(QFrame.Shape.HLine)
        vad_layout.addWidget(divider)

        vad_layout.addStretch(1)

        thresh_title = QLabel("Threshold")
        thresh_title.setObjectName("section")
        vad_layout.addWidget(thresh_title)

        thresh_row = QHBoxLayout()
        thresh_row.setSpacing(14)
        self.thresh_slider = QSlider(Qt.Orientation.Horizontal)
        self.thresh_slider.setRange(-80, -10)
        self.thresh_slider.setValue(int(self.settings.vad_threshold))
        self.thresh_slider.valueChanged.connect(self._on_threshold_changed)
        self.thresh_slider.setEnabled(self.settings.vad_enabled)
        thresh_row.addWidget(self.thresh_slider, stretch=1)
        self.thresh_val_label = QLabel(f"{self.settings.vad_threshold:.0f} dB")
        self.thresh_val_label.setObjectName("thresh-value")
        self.thresh_val_label.setFixedWidth(sp(64))
        self.thresh_val_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        thresh_row.addWidget(self.thresh_val_label)
        vad_layout.addLayout(thresh_row)

        self.vad_switch.toggled.connect(self._on_vad_toggled)
        vad_layout.addStretch(1)
        bottom_row.addWidget(vad_card, stretch=3)

        stats_card = QFrame()
        stats_card.setObjectName("card")
        stats_layout = QVBoxLayout(stats_card)
        stats_layout.setContentsMargins(6, 6, 6, 6)
        self.stats_panel = StatsPanel()
        stats_layout.addWidget(self.stats_panel)
        bottom_row.addWidget(stats_card, stretch=2)

        layout.addLayout(bottom_row, stretch=45)
        return page

    # -- Settings page -------------------------------------------------------
    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(26, 24, 26, 24)
        layout.setSpacing(29)

        title = QLabel("Settings")
        title.setObjectName("page-title")
        layout.addWidget(title)
        subtitle = QLabel("Models, audio, and app behavior.")
        subtitle.setObjectName("page-subtitle")
        layout.addWidget(subtitle)
        layout.addSpacing(4)

        # Model card
        model_card = QFrame()
        model_card.setObjectName("card")
        model_layout = QVBoxLayout(model_card)
        model_layout.setContentsMargins(66, 45, 54, 45)
        model_layout.setSpacing(10)
        model_title = QLabel("Denoising model")
        model_title.setObjectName("card-title")
        model_head = QHBoxLayout()
        model_head.setSpacing(12)
        model_head.addWidget(PhosphorIcon("cpu", size=20))
        model_head.addWidget(model_title)
        model_layout.addLayout(model_head)
        model_layout.addSpacing(10)

        model_row = QHBoxLayout()
        model_row.setSpacing(14)
        self.model_combo = QComboBox()
        self.model_combo.setObjectName("settings-combo")
        try:
            from ..engines import available_models
            _models = available_models()
        except Exception:
            from ..constants import DEFAULT_MODEL as _default
            _models = [_default]
        self.model_combo.addItems(_models)
        try:
            _saved = self.settings.model
            if _saved in _models:
                self.model_combo.setCurrentText(_saved)
        except Exception:
            pass
        self.model_combo.currentTextChanged.connect(self._on_model_changed)
        model_row.addWidget(self.model_combo, stretch=1)
        model_row.addStretch()
        model_layout.addLayout(model_row)

        self.model_blurb = QLabel()
        self.model_blurb.setObjectName("card-subtitle")
        self.model_blurb.setWordWrap(True)
        model_layout.addWidget(self.model_blurb)
        self._update_model_blurb(self.model_combo.currentText())
        layout.addWidget(model_card)

        # Audio card
        audio_card = QFrame()
        audio_card.setObjectName("card")
        audio_layout = QVBoxLayout(audio_card)
        audio_layout.setContentsMargins(66, 45, 54, 45)
        audio_layout.setSpacing(10)
        audio_title = QLabel("Audio")
        audio_title.setObjectName("card-title")
        audio_head = QHBoxLayout()
        audio_head.setSpacing(12)
        audio_head.addWidget(PhosphorIcon("sliders", size=20))
        audio_head.addWidget(audio_title)
        audio_layout.addLayout(audio_head)
        audio_layout.addSpacing(10)

        atten_row = QHBoxLayout()
        atten_row.setSpacing(14)
        atten_label = QLabel("Max attenuation")
        atten_row.addWidget(atten_label)
        atten_row.addStretch()
        self.atten_slider = QSlider(Qt.Orientation.Horizontal)
        self.atten_slider.setRange(-80, -20)
        try:
            atten_val = int(self.settings.atten_lim_db)
        except Exception:
            atten_val = -60
        self.atten_slider.setValue(atten_val)
        self.atten_slider.valueChanged.connect(self._on_atten_changed)
        atten_row.addWidget(self.atten_slider, stretch=1)
        self.atten_val_label = QLabel(f"{atten_val} dB")
        self.atten_val_label.setObjectName("thresh-value")
        self.atten_val_label.setFixedWidth(sp(64))
        self.atten_val_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        atten_row.addWidget(self.atten_val_label)
        audio_layout.addLayout(atten_row)
        atten_note = QLabel("Applies the next time processing starts.")
        atten_note.setObjectName("card-subtitle")
        audio_layout.addWidget(atten_note)
        layout.addWidget(audio_card)

        # Appearance card
        appearance_card = QFrame()
        appearance_card.setObjectName("card")
        appearance_layout = QVBoxLayout(appearance_card)
        appearance_layout.setContentsMargins(66, 45, 54, 45)
        appearance_layout.setSpacing(10)
        appearance_title = QLabel("Appearance")
        appearance_title.setObjectName("card-title")
        appearance_head = QHBoxLayout()
        appearance_head.setSpacing(12)
        appearance_head.addWidget(PhosphorIcon("palette", size=20))
        appearance_head.addWidget(appearance_title)
        appearance_layout.addLayout(appearance_head)
        appearance_layout.addSpacing(10)

        theme_row = QHBoxLayout()
        theme_row.setSpacing(14)
        self.theme_group = QButtonGroup(self)
        self.theme_group.setExclusive(True)
        for index, theme_id in enumerate(theme_store.theme_ids()):
            palette = theme_store.get_theme(theme_id)
            tile = ThemeTile(
                accent=palette["accent"],
                background=palette["bg"],
                text_dark=palette["bg"],
                name=theme_store.theme_label(theme_id),
                parent=self,
            )
            self.theme_group.addButton(tile, index)
            theme_row.addWidget(tile)
        theme_row.addStretch()
        appearance_layout.addLayout(theme_row)
        try:
            saved = theme_store.theme_ids().index(self.settings.theme)
        except ValueError:
            saved = 0
        checked = self.theme_group.button(saved)
        if checked is not None:
            checked.setChecked(True)
        self.theme_group.idClicked.connect(self._on_theme_changed)

        self.theme_blurb = QLabel()
        self.theme_blurb.setObjectName("card-subtitle")
        self.theme_blurb.setWordWrap(True)
        appearance_layout.addWidget(self.theme_blurb)
        self._update_theme_blurb(self.settings.theme)
        layout.addWidget(appearance_card)

        # Behavior card
        behavior_card = QFrame()
        behavior_card.setObjectName("card")
        behavior_layout = QVBoxLayout(behavior_card)
        behavior_layout.setContentsMargins(66, 45, 54, 45)
        behavior_layout.setSpacing(12)
        behavior_title = QLabel("Behavior")
        behavior_title.setObjectName("card-title")
        behavior_head = QHBoxLayout()
        behavior_head.setSpacing(12)
        behavior_head.addWidget(PhosphorIcon("gear", size=20))
        behavior_head.addWidget(behavior_title)
        behavior_layout.addLayout(behavior_head)
        behavior_layout.addSpacing(10)

        self.tray_check = QCheckBox("Show tray icon")
        self.tray_check.setChecked(
            self.settings.get(self.settings.KEY_SHOW_TRAY_ICON, True))
        self.tray_check.toggled.connect(self._on_tray_toggled)
        behavior_layout.addWidget(self.tray_check)

        self.min_tray_check = QCheckBox("Minimize to tray instead of exiting")
        self.min_tray_check.setChecked(self.settings.minimize_to_tray)
        self.min_tray_check.toggled.connect(
            lambda checked: setattr(self.settings, 'minimize_to_tray', checked))
        behavior_layout.addWidget(self.min_tray_check)
        layout.addWidget(behavior_card)

        layout.addStretch()
        return page

    # -- Logs page ------------------------------------------------------------
    def _build_logs_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(34, 32, 34, 32)
        layout.setSpacing(14)

        title = QLabel("Logs")
        title.setObjectName("page-title")
        layout.addWidget(title)

        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.log_path_label = QLabel()
        self.log_path_label.setObjectName("card-subtitle")
        bar.addWidget(self.log_path_label, stretch=1)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setObjectName("ghost")
        refresh_btn.clicked.connect(self._refresh_logs)
        bar.addWidget(refresh_btn)

        folder_btn = QPushButton("Open Folder")
        folder_btn.setObjectName("ghost")
        folder_btn.clicked.connect(self._open_log_folder)
        bar.addWidget(folder_btn)
        layout.addLayout(bar)

        self.log_view = QTextEdit()
        self.log_view.setObjectName("logs")
        self.log_view.setReadOnly(True)
        layout.addWidget(self.log_view, stretch=1)

        self._refresh_logs()
        return page

    def _refresh_logs(self):
        """Load the tail of the current log file into the viewer."""
        path = get_log_file_path()
        if not path or not os.path.exists(path):
            self.log_path_label.setText("No log file active this session.")
            self.log_view.setPlainText(
                "File logging is not enabled.\n"
                "Start the app with --log-file <path> or POISE_LOG_FILE "
                "to capture logs here.")
            return
        self.log_path_label.setText(path)
        try:
            with open(path, "r", errors="replace") as f:
                lines = f.readlines()
            tail = lines[-400:]
            self.log_view.setPlainText("".join(tail))
            self.log_view.verticalScrollBar().setValue(
                self.log_view.verticalScrollBar().maximum())
        except OSError as e:
            self.log_view.setPlainText(f"Could not read log file: {e}")

    def _open_log_folder(self):
        path = get_log_file_path()
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))

    # -- About page -------------------------------------------------------------
    def _build_about_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(34, 32, 34, 32)
        layout.setSpacing(10)
        layout.addStretch()

        icon_path = get_icon_path()
        if icon_path:
            self._about_icon = QLabel()
            self._about_icon.setPixmap(
                QPixmap(icon_path).scaled(
                    240, 240, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
            self._about_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(self._about_icon)

        name = QLabel("Poise Voice Isolator")
        name.setObjectName("page-title")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(name)

        version = QLabel(f"v{__version__}")
        version.setObjectName("card-subtitle")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version)

        tagline = QLabel("Real-time voice isolation. Runs 100% on-device.")
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(tagline)
        layout.addSpacing(12)

        credits = QLabel(
            "Denoising: DeepFilterNet3 · RNNoise (xiph.org)\n"
            "Built with Python and PyQt6 · MIT licensed")
        credits.setObjectName("card-subtitle")
        credits.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(credits)
        layout.addSpacing(8)

        links = QHBoxLayout()
        links.addStretch()
        github_btn = QPushButton("GitHub")
        github_btn.setObjectName("ghost")
        github_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(GITHUB_URL)))
        links.addWidget(github_btn)
        issues_btn = QPushButton("Report an issue")
        issues_btn.setObjectName("ghost")
        issues_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(ISSUES_URL)))
        links.addWidget(issues_btn)
        links.addStretch()
        layout.addLayout(links)

        layout.addStretch()
        return page

    # -- navigation ------------------------------------------------------------
    def _on_page_requested(self, index: int):
        self.sidebar.set_active_page(index)
        self.stack.setCurrentIndex(index)
        if index == 2:  # Logs
            self._refresh_logs()

    # -- worker / tray / state (unchanged behavior) ------------------------------
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
            if self.tray is None:
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

    @staticmethod
    def _make_badge_icon() -> PhosphorIcon:
        """VAD badge glyph in the active theme's badge color."""
        return PhosphorIcon(
            "waveform", color=theme_store.current()["badge_fg"], size=24)

    def _on_theme_changed(self, index: int):
        """Persist the selected theme and apply it live."""
        theme_ids = theme_store.theme_ids()
        if index < 0 or index >= len(theme_ids):
            return
        theme_id = theme_ids[index]
        self._update_theme_blurb(theme_id)
        self._apply_theme(theme_id)

    def _update_theme_blurb(self, theme_id: str):
        self.theme_blurb.setText(theme_store.theme_blurb(theme_id))

    def _apply_theme(self, theme_id: str):
        """Switch palette everywhere (persisted)."""
        self.settings.theme = theme_id
        theme_store.set_current(theme_id)
        self.setStyleSheet(get_stylesheet())
        clear_icon_cache()
        self._badge_icon.set_color(theme_store.current()["badge_fg"])
        self.sidebar.refresh_theme()
        self._refresh_app_icon()
        self.update()

    def _refresh_app_icon(self):
        """Reload window, taskbar, tray, and About icons for the theme."""
        icon_path = get_icon_path()
        if not icon_path:
            return
        app_icon = QIcon(icon_path)
        self.setWindowIcon(app_icon)
        app = QApplication.instance()
        if app is not None:
            app.setWindowIcon(app_icon)
        if self.tray is not None:
            self.tray.setIcon(app_icon)
        if hasattr(self, "_about_icon"):
            self._about_icon.setPixmap(
                QPixmap(icon_path).scaled(
                    240, 240, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))

    def _on_model_changed(self, model: str):
        """Persist selected denoising engine."""
        try:
            self.settings.model = model
        except Exception:
            pass
        self._update_model_blurb(model)

    def _update_model_blurb(self, model: str):
        info = MODEL_INFO.get((model or "").strip().lower(), {})
        picker = info.get("picker_blurb", "")
        pipe = info.get("blurb", "")
        text = " · ".join(part for part in (picker, pipe) if part)
        self.model_blurb.setText(text)

    def _on_atten_changed(self, value: int):
        """Persist attenuation limit (applies on next start)."""
        self.atten_val_label.setText(f"{value} dB")
        try:
            self.settings.atten_lim_db = float(value)
        except Exception:
            pass

    def _on_tray_toggled(self, checked: bool):
        self.settings.set(self.settings.KEY_SHOW_TRAY_ICON, checked)
        if checked:
            self.setup_tray()
        elif self.tray is not None:
            self.tray.hide()
            self.tray = None

    def toggle_processing(self, start: bool):
        """Handle power button click."""
        if start:
            self._start_processing()
        else:
            self._stop_processing()

    def _start_processing(self):
        """Start the audio processing worker."""
        if self.worker.is_running:
            return

        self._error_state = False
        self.power_btn.set_error(False)
        self.power_btn.set_transitioning(True)
        self.update_status("Starting...")

        self._configure_worker()
        self.worker.start()

    def _stop_processing(self):
        """Stop the audio processing worker."""
        if not self.worker.is_running:
            return

        self.power_btn.set_transitioning(True)
        self.update_status("Stopping...")

        self.worker.stop()

    def _configure_worker(self):
        """Pass current UI settings to worker."""
        self.worker.configure(
            model=self.model_combo.currentText() if hasattr(self, 'model_combo') else self.settings.model,
            onnx_path=self.settings.onnx_model_path,
            input_device=self.input_selector.selected_device_id,
            output_device=self.output_selector.selected_device_id,
            vad_enabled=self.vad_switch.isChecked(),
            vad_threshold=self.thresh_slider.value(),
            atten_lim_db=self.settings.atten_lim_db,
            vb_cable_enabled=self.vb_switch.isChecked()
        )

    def _set_controls_enabled(self, enabled: bool):
        self.input_selector.setEnabled(
            enabled and not self.vb_switch.isChecked())
        self.output_selector.setEnabled(enabled)
        self.vb_switch.setEnabled(enabled)
        if hasattr(self, 'model_combo'):
            self.model_combo.setEnabled(enabled)

    def _on_worker_started(self):
        """Called when worker successfully starts."""
        self.power_btn.set_transitioning(False)
        self.power_btn.set_active(True)
        self.update_status("Isolating audio")

        # Disable controls while running
        self._set_controls_enabled(False)

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
        self.power_btn.set_transitioning(False)
        self.power_btn.set_active(False)

        # Re-enable controls
        self._set_controls_enabled(True)
        self.stats_panel.reset()

        if not self._error_state:
            self.update_status("Ready")

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
        """Handle VAD switch toggle."""
        self.thresh_slider.setEnabled(checked)
        self.settings.vad_enabled = checked

    def update_status(self, message: str):
        """Update status line message."""
        self.status_label.setText(message)

        # Update status state
        state = "ready"
        if "Error" in message:
            state = "error"
        elif any(word in message for word in
                 ("Starting", "Stopping", "Loading", "Isolating", "Processing")):
            state = "processing"

        self.status_label.setProperty("state", state)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

        _logger.info(f"Status update: {message}")

    def handle_error(self, message: str):
        """Handle error from worker."""
        self._error_state = True
        self.power_btn.set_error(True)
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
