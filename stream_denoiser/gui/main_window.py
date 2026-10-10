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
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QCheckBox, QComboBox,
    QMessageBox, QApplication, QFrame, QStackedWidget,
    QTextEdit, QPushButton, QButtonGroup, QScrollArea, QBoxLayout,
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
    MSG_DEVICE_SWITCHING, MSG_DEVICE_SWITCHING_FIRST_TIME,
)
from .worker import AudioWorker
from .system_tray import SystemTray
from .widgets.phosphor import PhosphorIcon, clear_cache as clear_icon_cache
from .widgets.theme_tile import ThemeTile
from .widgets.power_button import PowerButton
from .widgets.switch import ToggleSwitch
from .widgets.slider import HoverSlider
from .widgets.sidebar import Sidebar
from .widgets.device_selector import DeviceSelector
from .widgets.combo import AnimatedComboBox
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
        self.setMinimumSize(*self._window_size(700, 560))
        self.setStyleSheet(get_stylesheet())
        self._resp = None  # responsive mode: wide / compact / narrow
        self._devices_narrow = False  # devices row order tracks this flag

        self.setup_ui()

        self.setup_worker()
        self.setup_tray()

        # Load persistent state
        self.restore_state()

        # Apple-style juice: window fade + staggered home entrance.
        self._status_pulse = None
        self._shown_once = False
        try:
            from .animations import install_press_fade
            for btn in self.findChildren(QPushButton):
                try:
                    name = btn.objectName()
                    if name in ("ghost", "icon-btn", "refresh-btn"):
                        install_press_fade(btn)
                except Exception:
                    continue
        except Exception:
            pass

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
    def _set_lowered(wrap: QWidget, offset: int) -> None:
        """Adjust a _lowered() wrapper's top offset (responsive)."""
        lay = wrap.layout()
        if lay is not None:
            lay.setContentsMargins(0, offset, 0, 0)

    def _layout_theme_grid(self, cols: int) -> None:
        """Arrange theme tiles in rows of `cols` (re-parenting is safe)."""
        for i, tile in enumerate(self.theme_tiles):
            self.theme_grid.addWidget(tile, i // cols, i % cols)
        for c in range(4):
            self.theme_grid.setColumnStretch(c, 0)
        self.theme_grid.setColumnStretch(cols, 1)

    def _layout_devices_row(self, narrow: bool) -> None:
        """Set devices row direction and order (power first when stacked).

        Input routing is fully automatic via VB-Cable: there is no input
        selector anymore, only power + output. Widgets re-add into a new
        position automatically, but re-adding an already-managed sublayout
        is a no-op — so the power column leaves first via takeAt (its
        wrapper is dropped; the layout itself survives on its member ref).
        Runs only when the narrow flag flips (see _apply_responsive).
        """
        self._devices_narrow = narrow
        row = self._devices_row
        top = Qt.AlignmentFlag.AlignTop
        try:
            for i in range(row.count()):
                if row.itemAt(i).layout() is self._power_wrap:
                    taken = row.takeAt(i)
                    del taken
                    break
        except Exception:
            pass
        if narrow:
            row.setDirection(QBoxLayout.Direction.TopToBottom)
            row.addLayout(self._power_wrap, stretch=4)
            row.addWidget(self._output_wrap, stretch=5, alignment=top)
        else:
            row.setDirection(QBoxLayout.Direction.LeftToRight)
            row.addLayout(self._power_wrap, stretch=4)
            row.addWidget(self._output_wrap, stretch=5, alignment=top)

    def _rv(self, wide, compact, narrow):
        """Pick a responsive value for the current mode."""
        if self._resp == "narrow":
            return narrow
        if self._resp == "compact":
            return compact
        return wide

    # -- responsive ----------------------------------------------------------
    def resizeEvent(self, event):  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._apply_responsive()

    def _apply_responsive(self) -> None:
        """Adapt chrome density and row direction to the window width.

        Wide keeps the dashboard mockup; compact tightens it; narrow
        stacks the rows and collapses the sidebar to an icon rail.
        Runs only on mode changes, so live resizes stay cheap. The
        window width alone drives the mode (internal changes never feed
        back into it), so this cannot oscillate.
        """
        w = self.width()
        # Design pixels, not window pixels: content scales with the UI
        # factor (e.g. 1.5x on HiDPI xcb), so a 1240px window can hold
        # only ~827px of layout. Without this the modes misjudge and
        # wide rows overflow on scaled displays.
        try:
            from .scaling import ui_scale
            w = w / max(0.5, ui_scale())
        except Exception:
            pass
        mode = ("narrow" if w < 850
                else "compact" if w < 1150 else "wide")
        if mode == self._resp:
            return
        self._resp = mode
        narrow = mode == "narrow"
        V = QBoxLayout.Direction.TopToBottom
        H = QBoxLayout.Direction.LeftToRight

        # Home
        self._home_layout.setContentsMargins(
            *self._rv((26, 26, 26, 26), (16, 16, 16, 16), (12, 12, 12, 12)))
        self._home_layout.setSpacing(self._rv(35, 24, 16))
        self._top_layout.setContentsMargins(
            *self._rv((78, 57, 66, 57), (40, 32, 36, 32), (20, 20, 20, 20)))
        self._top_layout.setSpacing(self._rv(26, 18, 14))
        if narrow != self._devices_narrow:
            self._layout_devices_row(narrow)
        self._devices_row.setSpacing(self._rv(24, 16, 12))
        # The lowered label column only aligns beside the tall button.
        lowered = 0 if narrow else self._power_third
        self._set_lowered(self._output_wrap, lowered)
        self._bottom_row.setDirection(V if narrow else H)
        self._bottom_row.setSpacing(self._rv(35, 24, 16))
        self._aad_layout.setContentsMargins(
            *self._rv((69, 51, 57, 51), (36, 28, 32, 28), (20, 20, 20, 20)))
        self._aad_layout.setSpacing(self._rv(16, 12, 10))

        # Settings
        self._settings_layout.setContentsMargins(
            *self._rv((26, 24, 26, 24), (16, 16, 16, 16), (12, 12, 12, 12)))
        self._settings_layout.setSpacing(self._rv(29, 20, 16))
        for card_layout in (self._model_layout, self._audio_layout,
                            self._appearance_layout, self._behavior_layout):
            card_layout.setContentsMargins(
                *self._rv((66, 45, 54, 45), (36, 28, 32, 28),
                          (20, 20, 20, 20)))
        self._layout_theme_grid(2 if narrow else 4)

        # Logs / About
        for page_layout in (self._logs_layout, self._about_layout):
            page_layout.setContentsMargins(
                *self._rv((34, 32, 34, 32), (20, 20, 20, 20),
                          (12, 12, 12, 12)))
        self._logs_layout.setSpacing(self._rv(14, 10, 8))
        self._about_layout.setSpacing(self._rv(10, 8, 8))

        # Sidebar rail on narrow windows.
        self.sidebar.set_compact(narrow)

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
        self._home_layout = layout

        # --- Top card: power + output (input is always VB-Cable) ---
        top_card = QFrame()
        top_card.setObjectName("card")
        top_layout = QVBoxLayout(top_card)
        top_layout.setContentsMargins(78, 57, 66, 57)
        top_layout.setSpacing(26)
        self._top_layout = top_layout

        devices_row = QHBoxLayout()
        devices_row.setSpacing(24)
        self._devices_row = devices_row

        # Labels start a third of the power button's height below its
        # top (per the design): offset the whole column downward.
        # (Lifted again in narrow mode, where the columns stack.)
        power_third = sp(210) // 3
        self._power_third = power_third

        power_wrap = QVBoxLayout()
        power_wrap.setSpacing(8)
        self._power_wrap = power_wrap
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
        self.status_label.setWordWrap(True)
        power_wrap.addWidget(self.status_label)
        devices_row.addLayout(power_wrap, stretch=4)

        self.output_selector = DeviceSelector("Output Device", "output")
        self.output_selector.device_changed.connect(
            lambda id: setattr(self.settings, 'output_device', id))
        self._output_wrap = self._lowered(self.output_selector, power_third)
        devices_row.addWidget(self._output_wrap,
                              stretch=5,
                              alignment=Qt.AlignmentFlag.AlignTop)

        top_layout.addLayout(devices_row)

        # Static routing note (no toggle): input always comes from VB-Cable.
        routing_note = QLabel(
            "System audio is captured automatically from VB-Cable "
            "(CABLE Output). If routing fails, Poise stops and shows "
            "manual steps.")
        routing_note.setObjectName("card-subtitle")
        routing_note.setWordWrap(True)
        routing_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_layout.addWidget(routing_note)

        layout.addWidget(top_card, stretch=55)

        # --- Bottom row: AAD card + stats card ---
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(35)
        self._bottom_row = bottom_row

        aad_card = QFrame()
        aad_card.setObjectName("card")
        aad_layout = QVBoxLayout(aad_card)
        aad_layout.setContentsMargins(69, 51, 57, 51)
        aad_layout.setSpacing(16)
        self._aad_layout = aad_layout

        aad_header = QHBoxLayout()
        aad_header.setSpacing(14)
        icon_circle = QFrame()
        icon_circle.setObjectName("icon-circle")
        icon_circle.setFixedSize(sp(44), sp(44))
        icon_layout = QHBoxLayout(icon_circle)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        self._badge_icon = self._make_badge_icon()
        icon_layout.addWidget(self._badge_icon)
        aad_header.addWidget(icon_circle)

        aad_titles = QVBoxLayout()
        aad_titles.setSpacing(2)
        aad_title = QLabel("AAD")
        aad_title.setObjectName("card-title")
        aad_titles.addWidget(aad_title)
        aad_sub = QLabel("Audio Activity detection")
        aad_sub.setObjectName("card-subtitle")
        aad_titles.addWidget(aad_sub)
        aad_header.addLayout(aad_titles)
        aad_header.addStretch()

        self.aad_switch = ToggleSwitch(checked=self.settings.aad_enabled)
        aad_header.addWidget(self.aad_switch)
        aad_layout.addLayout(aad_header)

        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFrameShape(QFrame.Shape.HLine)
        aad_layout.addWidget(divider)

        aad_layout.addStretch(1)

        thresh_title = QLabel("Threshold")
        thresh_title.setObjectName("section")
        aad_layout.addWidget(thresh_title)

        thresh_row = QHBoxLayout()
        thresh_row.setSpacing(14)
        self.thresh_slider = HoverSlider(Qt.Orientation.Horizontal)
        self.thresh_slider.setRange(-80, -10)
        self.thresh_slider.setValue(int(self.settings.aad_threshold))
        self.thresh_slider.valueChanged.connect(self._on_threshold_changed)
        self.thresh_slider.setEnabled(self.settings.aad_enabled)
        thresh_row.addWidget(self.thresh_slider, stretch=1)
        self.thresh_val_label = QLabel(f"{self.settings.aad_threshold:.0f} dB")
        self.thresh_val_label.setObjectName("thresh-value")
        self.thresh_val_label.setFixedWidth(sp(64))
        self.thresh_val_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        thresh_row.addWidget(self.thresh_val_label)
        aad_layout.addLayout(thresh_row)

        self.aad_switch.toggled.connect(self._on_aad_toggled)
        aad_layout.addStretch(1)
        bottom_row.addWidget(aad_card, stretch=3)

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
        self._settings_layout = layout

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
        self._model_layout = model_layout
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
        self.model_combo = AnimatedComboBox()
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
        self._audio_layout = audio_layout
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
        self.atten_slider = HoverSlider(Qt.Orientation.Horizontal)
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
        self._appearance_layout = appearance_layout
        appearance_title = QLabel("Appearance")
        appearance_title.setObjectName("card-title")
        appearance_head = QHBoxLayout()
        appearance_head.setSpacing(12)
        appearance_head.addWidget(PhosphorIcon("palette", size=20))
        appearance_head.addWidget(appearance_title)
        appearance_layout.addLayout(appearance_head)
        appearance_layout.addSpacing(10)

        theme_grid = QGridLayout()
        theme_grid.setContentsMargins(0, 0, 0, 0)
        theme_grid.setSpacing(14)
        self.theme_grid = theme_grid
        self.theme_tiles = []
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
            self.theme_tiles.append(tile)
        appearance_layout.addLayout(theme_grid)
        self._layout_theme_grid(4)
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
        self._behavior_layout = behavior_layout
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
        self._logs_layout = layout

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
        self._about_layout = layout
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
        try:
            from .animations import slide_stack
            slide_stack(self.stack, index)
        except Exception:
            self.stack.setCurrentIndex(index)
        if index == 2:  # Logs
            self._refresh_logs()

    def showEvent(self, event):  # noqa: N802 (Qt override)
        super().showEvent(event)
        if self._shown_once:
            return
        self._shown_once = True
        try:
            from .animations import motion_ok
            from PyQt6.QtCore import QPropertyAnimation, QEasingCurve
            # Window fade-in (Apple launch feel).
            if motion_ok():
                try:
                    self.setWindowOpacity(0.0)
                    anim = QPropertyAnimation(self, b"windowOpacity", self)
                    anim.setDuration(220)
                    anim.setStartValue(0.0)
                    anim.setEndValue(1.0)
                    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                    anim.start()
                    self._window_fade = anim  # keep alive
                except Exception:
                    pass
        except Exception:
            pass

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

        # Restore devices (output only — input is always VB-Cable)
        self.output_selector.selected_device_id = self.settings.output_device

    @staticmethod
    def _make_badge_icon() -> PhosphorIcon:
        """AAD badge glyph in the active theme's badge color."""
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
        # Input routing is always automatic via VB-Cable: capture from
        # CABLE Output after switching default playback to CABLE Input.
        self.worker.configure(
            model=self.model_combo.currentText() if hasattr(self, 'model_combo') else self.settings.model,
            onnx_path=self.settings.onnx_model_path,
            input_device=None,
            output_device=self.output_selector.selected_device_id,
            aad_enabled=self.aad_switch.isChecked(),
            aad_threshold=self.thresh_slider.value(),
            atten_lim_db=self.settings.atten_lim_db,
            vb_cable_enabled=True
        )

    def _set_controls_enabled(self, enabled: bool):
        self.output_selector.setEnabled(enabled)
        if hasattr(self, 'model_combo'):
            self.model_combo.setEnabled(enabled)

    def _on_worker_started(self):
        """Called when worker successfully starts."""
        self.power_btn.set_transitioning(False)
        self.power_btn.set_active(True)
        # First successful start: device switching (incl. one-time
        # AudioDeviceCmdlets install) has completed, so future runs
        # show the short "Switching audio device..." status.
        try:
            if not self.settings.device_switch_done:
                self.settings.device_switch_done = True
        except Exception:
            pass
        self.update_status("Isolating audio")
        self._start_status_pulse()

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
        self._stop_status_pulse()

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
        """Handle AAD threshold slider change."""
        self.thresh_val_label.setText(f"{value} dB")
        if not self.worker.is_running:
            self.settings.aad_threshold = float(value)
        # TODO: Support live updates to worker

    def _on_aad_toggled(self, checked):
        """Handle AAD switch toggle."""
        self.thresh_slider.setEnabled(checked)
        self.settings.aad_enabled = checked

    def update_status(self, message: str):
        """Update status line message."""
        # First-ever switch needs the AudioDeviceCmdlets one-time
        # install, which can take a few seconds with no other feedback.
        # Expand only that message, and only until the first successful
        # start flips device_switch_done.
        try:
            if (message == MSG_DEVICE_SWITCHING
                    and not self.settings.device_switch_done):
                message = MSG_DEVICE_SWITCHING_FIRST_TIME
        except Exception:
            pass
        self.status_label.setText(message)

        # Update status state
        state = "ready"
        if "Error" in message:
            state = "error"
        elif any(word in message for word in
                 ("Starting", "Stopping", "Loading", "Isolating", "Processing",
                  "Switching", "Switched", "Initializing", "Downloading",
                  "Installing", "Setting up")):
            state = "processing"

        self.status_label.setProperty("state", state)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

        _logger.info(f"Status update: {message}")

    def _start_status_pulse(self) -> None:
        """Breathe the status line while isolating (live-indicator feel)."""
        try:
            from .animations import cancel_fade, motion_ok
            from PyQt6.QtCore import QEasingCurve, QPropertyAnimation
            from PyQt6.QtWidgets import QGraphicsOpacityEffect
            self._stop_status_pulse()
            if not motion_ok():
                return
            # The pulse owns the label's effect exclusively: void any
            # entrance fade first so two animations never fight over it
            # (that replaces the effect mid-paint -> QPainter errors).
            cancel_fade(self.status_label)
            eff = QGraphicsOpacityEffect(self.status_label)
            self.status_label.setGraphicsEffect(eff)
            eff.setOpacity(1.0)
            anim = QPropertyAnimation(eff, b"opacity", self)
            anim.setDuration(1400)
            anim.setStartValue(1.0)
            anim.setKeyValueAt(0.5, 0.55)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.Type.InOutSine)
            anim.setLoopCount(-1)
            anim.start()
            self._status_pulse = anim
        except Exception:
            pass

    def _stop_status_pulse(self) -> None:
        try:
            if self._status_pulse is not None:
                try:
                    self._status_pulse.stop()
                except Exception:
                    pass
                self._status_pulse = None
            if hasattr(self, "status_label"):
                try:
                    self.status_label.setGraphicsEffect(None)
                except Exception:
                    pass
        except Exception:
            pass

    def handle_error(self, message: str):
        """Handle error from worker."""
        self._error_state = True
        self.power_btn.set_error(True)
        self._stop_status_pulse()
        self.update_status(f"Error: {message}")
        if self._is_vb_cable_error(message):
            # Blocking modal: processing cannot start without VB-Cable
            # routing. Always show it, even when a tray icon exists.
            self.bring_to_front()
            try:
                from .widgets.vb_cable_dialog import show_vb_cable_error
                show_vb_cable_error(self, message)
            except Exception:
                QMessageBox.critical(self, "VB-Cable routing failed", message)
        elif self.tray:
            self.tray.notify("Poise Error", message, is_error=True)
        else:
            QMessageBox.critical(self, "Error", message)

        _logger.error(f"Error: {message}")

    @staticmethod
    def _is_vb_cable_error(message: str) -> bool:
        """Check whether a worker error is a VB-Cable routing failure."""
        text = (message or "").upper()
        return "VB-CABLE" in text or ("CABLE" in text and "LOOPBACK" in text)

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
