"""
Poise Voice Isolator - Main Window

Dashboard layout: sidebar navigation with Home / Settings / Logs / About
pages. Home is the tick-ring dial (Start/Stop + reduction strength) above
two cards: the output device and the model; everything else lives in
Settings. Live performance stats sit in the status bar.
"""
import datetime
import logging
import os
import sys
from typing import Optional

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel,
    QMessageBox, QApplication, QFrame, QStackedWidget,
    QPlainTextEdit, QPushButton, QButtonGroup, QScrollArea, QBoxLayout,
    QFileDialog,
)
from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import (
    QIcon, QCloseEvent, QPixmap, QDesktopServices, QColor, QFont,
    QTextCharFormat, QTextCursor,
)

from .styles import get_stylesheet
from .scaling import init_scaling, sp
from .fonts import load_fonts
from .animations import install_hover_fades
from .titlebar import apply_titlebar
from . import themes as theme_store
from .settings import get_settings
from .. import __version__
from ..constants import (
    MSG_PROCESSING_STARTED, MSG_PROCESSING_STOPPED,
    MSG_DEVICE_SWITCHING, MSG_DEVICE_SWITCHING_FIRST_TIME,
)
from .worker import AudioWorker
from .system_tray import SystemTray
from .widgets.phosphor import (
    clear_cache as clear_icon_cache, icon as phosphor_icon,
)
from .widgets.theme_tile import ThemeTile
from .widgets.dial import ATTEN_DEFAULT, DialButton, clamp_db
from .widgets.donate_button import DonateButton
from .widgets.switch import ToggleSwitch
from .widgets.slider import HoverSlider
from .widgets.sidebar import Sidebar
from .widgets.device_selector import DeviceSelector
from .widgets.chip import IconChip
from .widgets.model_cards import ModelCards
from .widgets.settings_row import SettingsRow
from .widgets.model_selector import ModelSelector
from .widgets.stats_bar import StatsBar, status_word
from .widgets.emblem import Emblem
from .widgets.pattern_card import PatternCard
from ..logging_config import (
    get_logger, get_log_file_path, get_memory_handler,
)
from .utils import get_icon_path

_logger = get_logger(__name__)

HOME_TITLES = {
    "ready": "Ready to isolate",
    "starting": "Starting...",
    "isolating": "Isolating voices",
    "stopping": "Stopping...",
    "error": "Couldn't start",
}
HOME_READY_SUB = "Press the dial to start."
HOME_ISOLATING_SUB = "Processing"

GITHUB_URL = "https://github.com/chabandou/poise-voice-isolator"
ISSUES_URL = "https://github.com/chabandou/poise-voice-isolator/issues"
VB_AUDIO_URL = "https://vb-audio.com/"
# Where the About page's Donate button goes. Empty hides the button.
DONATE_URL = ""


class MainWindow(QMainWindow):
    """
    Main application window for Poise Voice Isolator.
    """

    CARDS_STACK_BELOW = 1000  # design px: Home's two cards stack below this

    def __init__(self):
        super().__init__()

        self.settings = get_settings()
        self.worker: Optional[AudioWorker] = None
        self.tray: Optional[SystemTray] = None
        self._forcing_quit = False
        self._error_state = False

        init_scaling()
        load_fonts()
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
        self._cards_stacked = None
        self._icon_buttons = []  # (button, icon name) re-tinted per theme

        self.setup_ui()
        install_hover_fades(self)

        self.setup_worker()
        self.setup_tray()

        # Load persistent state
        self.restore_state()

        # Apple-style juice: window fade + staggered home entrance.
        self._status_pulse = None
        self._status_pulse_eff = None
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

    def _layout_theme_grid(self, cols: int) -> None:
        """Arrange theme tiles in rows of `cols` (re-parenting is safe)."""
        for i, tile in enumerate(self.theme_tiles):
            self.theme_grid.addWidget(tile, i // cols, i % cols)
        # Equal-width columns; the tiles stretch to fill the card.
        for c in range(max(cols, len(self.theme_tiles))):
            self.theme_grid.setColumnStretch(c, 1 if c < cols else 0)

    def _rv(self, wide, compact, narrow):
        """Pick a responsive value for the current mode."""
        if self._resp == "narrow":
            return narrow
        if self._resp == "compact":
            return compact
        return wide

    def _rm(self, wide, compact, narrow):
        """Responsive margins as scaled pixels (a 4-tuple per mode)."""
        return tuple(sp(v) for v in self._rv(wide, compact, narrow))

    def _icon_button(self, text: str, icon_name: str,
                     color_key: str = "secondary",
                     button_cls=QPushButton) -> QPushButton:
        """Ghost button with a theme-tinted Phosphor icon (palette key)."""
        from PyQt6.QtCore import QSize
        from .scaling import isp
        btn = button_cls(text)
        btn.setObjectName("ghost")
        btn.setIconSize(QSize(isp(16), isp(16)))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._icon_buttons.append((btn, icon_name, color_key))
        self._tint_icon_buttons()
        return btn

    def _tint_icon_buttons(self) -> None:
        palette = theme_store.current()
        for btn, name, key in self._icon_buttons:
            btn.setIcon(phosphor_icon(name, 16, palette[key]))

    # -- responsive ----------------------------------------------------------
    def resizeEvent(self, event):  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._apply_responsive()

    def _apply_responsive(self) -> None:
        """Adapt chrome density and row direction to the window width.

        Home is always the dial card over its two cards; compact tightens
        it (and below CARDS_STACK_BELOW stacks the two cards); narrow
        collapses the sidebar to an icon rail. Runs only on mode changes,
        so live resizes stay cheap. The
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
        cards_stacked = w < self.CARDS_STACK_BELOW
        if mode == self._resp and cards_stacked == self._cards_stacked:
            return
        self._resp = mode
        self._cards_stacked = cards_stacked
        narrow = mode == "narrow"
        V = QBoxLayout.Direction.TopToBottom
        H = QBoxLayout.Direction.LeftToRight

        # Home
        # Wide paddings are trimmed vertically so the default window shows
        # the dial card and both cards without scrolling.
        self._home_layout.setContentsMargins(
            *self._rm((26, 20, 26, 20), (16, 16, 16, 16), (12, 12, 12, 12)))
        self._home_layout.setSpacing(sp(self._rv(16, 16, 12)))
        self._stage_layout.setContentsMargins(
            *self._rm((26, 24, 26, 20), (20, 24, 20, 20), (16, 20, 16, 18)))
        self.power_btn.set_dial_size(sp(self._rv(300, 270, 240)))
        # The cards stack before narrow mode: side by side they need more
        # room than compact chrome leaves.
        self._cards_layout.setDirection(V if cards_stacked else H)
        self._cards_layout.setSpacing(sp(self._rv(16, 16, 12)))
        for card_layout in self._home_card_layouts:
            card_layout.setContentsMargins(
                *self._rm((24, 20, 24, 20), (20, 18, 20, 18),
                          (16, 16, 16, 16)))

        # Settings
        self._settings_layout.setContentsMargins(
            *self._rm((26, 24, 26, 24), (16, 16, 16, 16), (12, 12, 12, 12)))
        self._settings_layout.setSpacing(sp(self._rv(20, 16, 12)))
        self._settings_bottom.setDirection(V if narrow else H)
        self._settings_bottom.setSpacing(sp(self._rv(20, 16, 12)))
        for card_layout in (self._model_layout, self._appearance_layout):
            card_layout.setContentsMargins(
                *self._rm((24, 22, 24, 22), (20, 18, 20, 18),
                          (16, 16, 16, 16)))
        self._layout_theme_grid(3)

        # Logs / About
        for page_layout in (self._logs_layout, self._about_layout):
            page_layout.setContentsMargins(
                *self._rm((34, 32, 34, 32), (20, 20, 20, 20),
                          (12, 12, 12, 12)))
        self._logs_layout.setSpacing(sp(self._rv(14, 10, 8)))
        self._about_layout.setSpacing(sp(self._rv(10, 8, 8)))

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

        # Performance readout lives in the status bar (not on Home).
        bar = self.statusBar()
        bar.setSizeGripEnabled(False)
        bar.setContentsMargins(0, 0, 0, 0)
        self.stats_bar = StatsBar()
        bar.addWidget(self.stats_bar, 1)

    # -- Home page ----------------------------------------------------------
    def _saved_atten_db(self) -> int:
        """Saved strength, clamped to the dial (older builds allowed -80..-20)."""
        try:
            return clamp_db(self.settings.atten_lim_db)
        except Exception:
            return ATTEN_DEFAULT

    def _divider(self) -> QFrame:
        line = QFrame()
        line.setObjectName("divider")
        line.setFrameShape(QFrame.Shape.HLine)
        return line

    def _build_home_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(sp(26), sp(26), sp(26), sp(26))
        layout.setSpacing(sp(20))
        self._home_layout = layout
        center = Qt.AlignmentFlag.AlignCenter

        # --- Left: dial card (state headline, Start/Stop, strength) ---
        stage = PatternCard()
        stage.setObjectName("card")
        self._stage = stage
        stage_layout = QVBoxLayout(stage)
        stage_layout.setContentsMargins(sp(26), sp(28), sp(26), sp(24))
        stage_layout.setSpacing(sp(8))
        self._stage_layout = stage_layout

        self.home_title = QLabel(HOME_TITLES["ready"])
        self.home_title.setObjectName("home-title")
        self.home_title.setAlignment(center)
        self.home_title.setWordWrap(True)
        stage_layout.addWidget(self.home_title)

        self.status_label = QLabel(HOME_READY_SUB)
        self.status_label.setObjectName("status-line")
        self.status_label.setProperty("state", "ready")
        self.status_label.setAlignment(center)
        self.status_label.setWordWrap(True)
        stage_layout.addWidget(self.status_label)
        # Status changes fade instead of snapping (several can arrive in
        # quick succession while starting; only the newest fades in).
        from .animations import TextSwap
        self._title_swap = TextSwap(self.home_title)
        self._status_swap = TextSwap(self.status_label)
        self._status_swap.settled.connect(self._on_status_settled)
        self._pulse_wanted = False   # start the pulse once the text settles

        stage_layout.addStretch(1)
        self.power_btn = DialButton()
        self.power_btn.toggled_state.connect(self.toggle_processing)
        self.power_btn.set_strength_db(self._saved_atten_db())
        self.power_btn.strength_changed.connect(self._on_atten_changed)
        stage_layout.addWidget(
            self.power_btn, alignment=Qt.AlignmentFlag.AlignHCenter)
        stage_layout.addStretch(1)

        hint = QLabel("Drag the ring to set the reduction strength. "
                      "Changes apply right away.")
        hint.setObjectName("row-sub")
        hint.setAlignment(center)
        hint.setWordWrap(True)
        stage_layout.addWidget(hint)
        layout.addWidget(stage, stretch=1)

        # --- Below: output device and model, side by side ---
        cards = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        cards.setSpacing(sp(16))
        self._cards_layout = cards
        self._home_card_layouts = []

        # Input is always VB-Cable (named in the status bar); only the
        # output is picked here.
        self.output_selector = DeviceSelector(
            "Output device", "output", "Where the clean audio plays")
        self.output_selector.device_changed.connect(
            lambda id: setattr(self.settings, 'output_device', id))
        # Settings' model cards stay in step (see _on_model_changed).
        self.model_selector = ModelSelector()
        self.model_selector.currentTextChanged.connect(
            self._on_home_model_picked)
        for content in (self.output_selector, self.model_selector):
            card = QFrame()
            card.setObjectName("card")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(sp(24), sp(22), sp(24), sp(22))
            card_layout.addWidget(content)
            self._home_card_layouts.append(card_layout)
            cards.addWidget(card, stretch=1)
        layout.addLayout(cards)
        return page

    # -- Settings page -------------------------------------------------------
    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(sp(26), sp(24), sp(26), sp(24))
        layout.setSpacing(sp(20))
        self._settings_layout = layout

        title = QLabel("Settings")
        title.setObjectName("page-title")
        layout.addWidget(title)
        subtitle = QLabel("Silence skipping, model, appearance, and app "
                          "behavior. Reduction strength is the dial on Home.")
        subtitle.setObjectName("page-subtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # List card: menu-style rows.
        list_card = QFrame()
        list_card.setObjectName("card")
        list_layout = QVBoxLayout(list_card)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(0)

        self.aad_switch = ToggleSwitch(checked=self.settings.aad_enabled)
        self.aad_switch.toggled.connect(self._on_aad_toggled)
        aad_row = SettingsRow(
            "Skip silence",
            "Audio Activity detection. Saves CPU while nothing plays.",
            self.aad_switch)
        self._aad_row = aad_row

        thresh_box = QWidget()
        thresh_layout = QHBoxLayout(thresh_box)
        thresh_layout.setContentsMargins(0, 0, 0, 0)
        thresh_layout.setSpacing(sp(14))
        self.thresh_slider = HoverSlider(Qt.Orientation.Horizontal)
        self.thresh_slider.setRange(-80, -10)
        self.thresh_slider.setValue(int(self.settings.aad_threshold))
        self.thresh_slider.valueChanged.connect(self._on_threshold_changed)
        self.thresh_slider.setEnabled(self.settings.aad_enabled)
        self.thresh_slider.setMinimumWidth(sp(230))
        thresh_layout.addWidget(self.thresh_slider, stretch=1)
        self.thresh_val_label = QLabel(f"{self.settings.aad_threshold:.0f} dB")
        self.thresh_val_label.setObjectName("thresh-value")
        self.thresh_val_label.setFixedWidth(sp(64))
        self.thresh_val_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        thresh_layout.addWidget(self.thresh_val_label)
        thresh_row = SettingsRow(
            "Silence threshold", "Anything quieter counts as silence.",
            thresh_box)

        self.tray_switch = ToggleSwitch(
            checked=self.settings.get(self.settings.KEY_SHOW_TRAY_ICON, True))
        self.tray_switch.toggled.connect(self._on_tray_toggled)
        tray_row = SettingsRow(
            "Show tray icon", "Keep Poise in the system tray.",
            self.tray_switch)

        self.min_tray_switch = ToggleSwitch(
            checked=self.settings.minimize_to_tray)
        self.min_tray_switch.toggled.connect(
            lambda checked: setattr(self.settings, 'minimize_to_tray', checked))
        min_tray_row = SettingsRow(
            "Keep running in the tray when closed",
            "Closing the window does not stop Poise.", self.min_tray_switch)

        self.reset_btn = self._icon_button("Reset", "reset")
        self.reset_btn.clicked.connect(self._confirm_reset_defaults)
        reset_row = SettingsRow(
            "Reset to defaults",
            "Restore every setting and the reduction strength. "
            "Output device and theme stay.",
            self.reset_btn)
        self._reset_row = reset_row

        rows = [aad_row, thresh_row, tray_row, min_tray_row, reset_row]
        for i, row in enumerate(rows):
            row.set_position(i == 0, i == len(rows) - 1)
            list_layout.addWidget(row)
            if i < len(rows) - 1:
                list_layout.addWidget(self._divider())
        self._aad_row = aad_row
        layout.addWidget(list_card)

        # Bottom: model cards + appearance.
        bottom = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        bottom.setSpacing(sp(20))
        self._settings_bottom = bottom

        model_card = QFrame()
        model_card.setObjectName("card")
        model_layout = QVBoxLayout(model_card)
        model_layout.setContentsMargins(sp(24), sp(22), sp(24), sp(22))
        model_layout.setSpacing(sp(16))
        self._model_layout = model_layout
        model_layout.addLayout(self._card_head(
            "cpu", "Model", "Takes effect the next time you start."))
        self.model_cards = ModelCards()
        try:
            self.model_cards.setCurrentText(self.settings.model)
        except Exception:
            pass
        self.model_cards.currentTextChanged.connect(self._on_model_changed)
        self.model_selector.setCurrentText(self.model_cards.currentText())
        model_layout.addWidget(self.model_cards)
        model_layout.addStretch(1)
        bottom.addWidget(model_card, stretch=3)

        appearance_card = QFrame()
        appearance_card.setObjectName("card")
        appearance_layout = QVBoxLayout(appearance_card)
        appearance_layout.setContentsMargins(sp(24), sp(22), sp(24), sp(22))
        appearance_layout.setSpacing(sp(16))
        self._appearance_layout = appearance_layout
        appearance_layout.addLayout(self._card_head(
            "palette", "Appearance", ""))

        theme_grid = QGridLayout()
        theme_grid.setContentsMargins(0, 0, 0, 0)
        theme_grid.setSpacing(sp(14))
        self.theme_grid = theme_grid
        self.theme_tiles = []
        self.theme_group = QButtonGroup(self)
        self.theme_group.setExclusive(True)
        for index, theme_id in enumerate(theme_store.theme_ids()):
            tile = ThemeTile(theme_id, parent=self)
            self.theme_group.addButton(tile, index)
            self.theme_tiles.append(tile)
        appearance_layout.addLayout(theme_grid)
        self._layout_theme_grid(3)
        try:
            saved = theme_store.theme_ids().index(self.settings.theme)
        except ValueError:
            saved = 0
        checked = self.theme_group.button(saved)
        if checked is not None:
            checked.setChecked(True)
        self.theme_group.idClicked.connect(self._on_theme_changed)

        self.theme_blurb = QLabel()
        self.theme_blurb.setObjectName("row-sub")
        self.theme_blurb.setWordWrap(True)
        appearance_layout.addWidget(self.theme_blurb)
        appearance_layout.addStretch(1)
        self._update_theme_blurb(self.settings.theme)
        bottom.addWidget(appearance_card, stretch=2)

        layout.addLayout(bottom)
        layout.addStretch()
        return page

    def _card_head(self, icon: str, title: str, subtitle: str):
        """Chip + title (+ caption) header row used by Settings cards."""
        head = QHBoxLayout()
        head.setSpacing(sp(14))
        head.addWidget(IconChip(icon))
        titles = QVBoxLayout()
        titles.setSpacing(sp(2))
        name = QLabel(title)
        name.setObjectName("card-title")
        titles.addWidget(name)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("row-sub")
            titles.addWidget(sub)
        head.addLayout(titles)
        head.addStretch(1)
        return head

    # -- Logs page ------------------------------------------------------------
    LOG_POLL_MS = 500          # live refresh while the Logs page is open
    LOG_MAX_BLOCKS = 5000      # view trims its oldest lines past this

    def _build_logs_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(34, 32, 34, 32)
        layout.setSpacing(14)
        self._logs_layout = layout

        title = QLabel("Logs")
        title.setObjectName("page-title")
        layout.addWidget(title)
        subtitle = QLabel("What Poise is doing this session, updated live. "
                          "Copy or save it when reporting a problem.")
        subtitle.setObjectName("page-subtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.log_path_label = QLabel()
        self.log_path_label.setObjectName("log-path")
        self.log_path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        bar.addWidget(self.log_path_label, stretch=1)

        self.log_copy_btn = self._icon_button("Copy", "copy")
        self.log_copy_btn.setToolTip("Copy this session's log")
        self.log_copy_btn.clicked.connect(self._copy_logs)
        bar.addWidget(self.log_copy_btn)

        save_btn = self._icon_button("Save…", "save")
        save_btn.setToolTip("Save this session's log to a file")
        save_btn.clicked.connect(self._save_logs)
        bar.addWidget(save_btn)

        self.log_folder_btn = self._icon_button("Open Folder", "folder")
        self.log_folder_btn.setToolTip(
            "Open the folder with the log files of this and earlier sessions")
        self.log_folder_btn.clicked.connect(self._open_log_folder)
        bar.addWidget(self.log_folder_btn)
        layout.addLayout(bar)

        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("logs")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(self.LOG_MAX_BLOCKS)
        self.log_view.setPlaceholderText("Nothing logged yet.")
        mono = QFont()
        mono.setFamilies(["JetBrains Mono", "Cascadia Mono", "Consolas",
                          "DejaVu Sans Mono", "Liberation Mono"])
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setFixedPitch(True)
        self.log_view.setFont(mono)
        layout.addWidget(self.log_view, stretch=1)

        self._log_seq = 0
        self._log_timer = QTimer(self)
        self._log_timer.setInterval(self.LOG_POLL_MS)
        self._log_timer.timeout.connect(self._poll_logs)

        self._refresh_logs()
        return page

    def _show_logs_page(self, shown: bool) -> None:
        """Follow the log live only while its page is open."""
        if shown:
            self._update_log_source()
            self._poll_logs()
            self._log_timer.start()
        else:
            self._log_timer.stop()

    def _refresh_logs(self):
        """Re-render the whole session log (first build, theme change)."""
        self._update_log_source()
        self.log_view.clear()
        self._log_seq = 0
        self._poll_logs()
        bar = self.log_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _update_log_source(self) -> None:
        path = get_log_file_path()
        if path:
            self.log_path_label.setText(path)
            self.log_path_label.setToolTip(
                "Log file for this and earlier sessions")
        else:
            self.log_path_label.setText("This session only, not saved to disk")
            self.log_path_label.setToolTip("")
        self.log_folder_btn.setVisible(bool(path))

    def _poll_logs(self) -> None:
        """Append records logged since the last poll, colouring problems."""
        handler = get_memory_handler()
        if handler is None:
            self.log_view.setPlaceholderText(
                "Session logging is off (the app was started without it).")
            return
        seq, entries = handler.entries_since(self._log_seq)
        self._log_seq = seq
        if not entries:
            return
        bar = self.log_view.verticalScrollBar()
        follow = bar.value() >= bar.maximum() - 4
        palette = theme_store.current()
        error_fmt, warn_fmt = QTextCharFormat(), QTextCharFormat()
        error_fmt.setForeground(QColor(palette["error"]))
        warn_fmt.setForeground(QColor(palette["warning"]))
        plain = QTextCharFormat()

        cursor = QTextCursor(self.log_view.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.beginEditBlock()
        first = self.log_view.document().isEmpty()
        for levelno, text in entries:
            if levelno >= logging.ERROR:
                fmt = error_fmt
            elif levelno >= logging.WARNING:
                fmt = warn_fmt
            else:
                fmt = plain
            if not first:
                cursor.insertBlock()
            first = False
            cursor.insertText(text, fmt)
        cursor.endEditBlock()
        if follow:
            bar.setValue(bar.maximum())

    def _session_log_text(self) -> str:
        handler = get_memory_handler()
        return handler.text() if handler else self.log_view.toPlainText()

    def _copy_logs(self) -> None:
        QApplication.clipboard().setText(self._session_log_text())
        self.log_copy_btn.setText("Copied")
        QTimer.singleShot(1500, lambda: self.log_copy_btn.setText("Copy"))

    def _save_logs(self) -> None:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        suggested = os.path.join(os.path.expanduser("~"),
                                 f"poise-log-{stamp}.txt")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save log", suggested,
            "Text files (*.txt *.log);;All files (*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._session_log_text() + "\n")
        except OSError as e:
            QMessageBox.warning(self, "Save log", f"Could not save the log:\n{e}")
            return
        _logger.info(f"Session log saved to {path}")

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

        self._about_icon = Emblem()
        icon_path = get_icon_path()
        if icon_path:
            self._about_icon.set_pixmap(QPixmap(icon_path))
        layout.addWidget(
            self._about_icon, alignment=Qt.AlignmentFlag.AlignHCenter)

        name = QLabel("Poise Voice Isolator")
        name.setObjectName("page-title")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(name)

        version = QLabel(f"v{__version__}")
        version.setObjectName("about-version")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version)

        tagline = QLabel("Real-time voice isolation. Runs 100% on-device.")
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(tagline)
        layout.addSpacing(12)

        credits = QLabel()
        credits.setObjectName("card-subtitle")
        credits.setAlignment(Qt.AlignmentFlag.AlignCenter)
        credits.setTextFormat(Qt.TextFormat.RichText)
        credits.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByKeyboard)
        credits.linkActivated.connect(
            lambda url: QDesktopServices.openUrl(QUrl(url)))
        credits.linkHovered.connect(
            lambda url: self._refresh_credits(hover=bool(url)))
        self.about_credits = credits
        self._refresh_credits()
        layout.addWidget(credits)
        layout.addSpacing(8)

        links = QHBoxLayout()
        links.addStretch()
        github_btn = self._icon_button("GitHub", "info")
        github_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(GITHUB_URL)))
        links.addWidget(github_btn)
        issues_btn = self._icon_button("Report an issue", "doc")
        issues_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(ISSUES_URL)))
        links.addWidget(issues_btn)
        # Poise is free: a filled button (dark label on the secondary
        # colour) stands apart from the ghost links. Hidden until
        # DONATE_URL is set.
        donate_btn = self._icon_button(
            "Donate", "heart", color_key="bg", button_cls=DonateButton)
        donate_btn.setObjectName("donate")
        donate_btn.setToolTip(
            "Poise is free. If it helps you, you can support its "
            "development.")
        donate_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(DONATE_URL)))
        donate_btn.setVisible(bool(DONATE_URL))
        self.donate_btn = donate_btn
        links.addWidget(donate_btn)
        links.addStretch()
        layout.addLayout(links)

        layout.addStretch()
        return page

    def _refresh_credits(self, hover: bool = False) -> None:
        """About credits as rich text; VB-Audio's name is an embedded link.

        The link takes the theme accent, underlines on hover and carries
        an external-link arrow. Rebuilt on theme switches.
        """
        accent = theme_store.current()["accent"]
        underline = "underline" if hover else "none"
        link = (f'<a href="{VB_AUDIO_URL}" style="color:{accent}; '
                f'text-decoration:{underline};">VB-Audio Software \u2197</a>')
        self.about_credits.setText(
            "Denoising: DeepFilterNet3 · GTCRN · RNNoise (xiph.org)<br>"
            f"Audio routing: VB-CABLE by {link} · third-party, donationware"
            "<br>Built with Python and PyQt6 · MIT licensed")

    # -- navigation ------------------------------------------------------------
    def _on_page_requested(self, index: int):
        self.sidebar.set_active_page(index)
        try:
            from .animations import slide_stack
            slide_stack(self.stack, index)
        except Exception:
            self.stack.setCurrentIndex(index)
        self._show_logs_page(index == 2)  # Logs

    def showEvent(self, event):  # noqa: N802 (Qt override)
        super().showEvent(event)
        # Native title bar follows the theme (Windows only; re-applied on
        # every show since hiding to the tray can recreate the frame).
        apply_titlebar(self, theme_store.current())
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
        self.worker.stats_updated.connect(self.stats_bar.update_stats)
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
        """Switch palette everywhere (persisted), crossfading when live."""
        snapshot = None
        if self.isVisible() and theme_id != theme_store.current_id():
            try:
                from .animations import motion_ok
                if motion_ok():
                    snapshot = self.grab()
            except Exception:
                snapshot = None
        self.settings.theme = theme_id
        theme_store.set_current(theme_id)
        self.setStyleSheet(get_stylesheet())
        clear_icon_cache()
        self.sidebar.refresh_theme()
        self._refresh_app_icon()
        for chip in self.findChildren(IconChip):
            chip.refresh_theme()
        self.output_selector.refresh_theme()
        self.model_selector.refresh_theme()
        apply_titlebar(self, theme_store.current())
        self._refresh_credits()
        self._tint_icon_buttons()
        self._refresh_logs()   # re-colour warnings/errors for the new palette
        self.power_btn.update()
        self.stats_bar.update()
        self.update()
        if snapshot is not None:
            from .animations import crossfade_from
            crossfade_from(self, snapshot)

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
            self._about_icon.set_pixmap(QPixmap(icon_path))

    def _on_model_changed(self, model: str):
        """Persist selected denoising engine (and show it on Home)."""
        try:
            self.settings.model = model
        except Exception:
            pass
        self.model_selector.setCurrentText(model)

    def _on_home_model_picked(self, model: str):
        """Home's dropdown drives Settings' cards, which persist it."""
        self.model_cards.setCurrentText(model)

    def _on_atten_changed(self, value: int):
        """Persist the attenuation limit and apply it to a running worker."""
        try:
            self.settings.atten_lim_db = float(value)
        except Exception:
            pass
        if self.worker is not None:
            self.worker.set_atten_lim_db(float(value))

    def _confirm_reset_defaults(self) -> None:
        reply = QMessageBox.question(
            self, "Reset to defaults",
            "Reset reduction strength, silence skipping, tray behavior "
            "and model to their defaults?\n\n"
            "Your output device and theme stay as they are.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.reset_to_defaults()

    def reset_to_defaults(self) -> None:
        """Restore the user-facing settings to Settings.DEFAULTS.

        Goes through the controls, so each value is saved and applied as
        if changed by hand. Output device, theme, window geometry and
        first-run state are left alone.
        """
        s = self.settings
        defaults = s.DEFAULTS
        self.aad_switch.setChecked(bool(defaults[s.KEY_AAD_ENABLED]))
        self.thresh_slider.setValue(int(defaults[s.KEY_AAD_THRESHOLD]))
        self.tray_switch.setChecked(bool(defaults[s.KEY_SHOW_TRAY_ICON]))
        self.min_tray_switch.setChecked(bool(defaults[s.KEY_MINIMIZE_TO_TRAY]))
        self.model_cards.setCurrentText(defaults[s.KEY_MODEL])
        strength = clamp_db(defaults[s.KEY_ATTEN_LIM_DB])
        self.power_btn.set_strength_db(strength)
        self._on_atten_changed(strength)
        _logger.info("Settings reset to defaults")

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
            model=self.model_cards.currentText() or self.settings.model,
            onnx_path=self.settings.onnx_model_path,
            input_device=None,
            output_device=self.output_selector.selected_device_id,
            aad_enabled=self.aad_switch.isChecked(),
            aad_threshold=self.thresh_slider.value(),
            atten_lim_db=float(self._saved_atten_db()),
            vb_cable_enabled=True
        )

    def _set_controls_enabled(self, enabled: bool):
        self.output_selector.set_locked(not enabled)
        self.model_selector.set_locked(not enabled)
        self.model_cards.setEnabled(enabled)
        # Turning silence skipping on/off would rebuild the detector inside
        # the running processor; the threshold itself stays live.
        self._aad_row.set_locked(not enabled)
        self._reset_row.set_locked(not enabled)   # it resets those too

    def _on_worker_started(self):
        """Called when worker successfully starts."""
        self.power_btn.set_transitioning(False)
        self.power_btn.set_active(True)
        self._stage.set_live(True)
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
        self._stage.set_live(False)
        self._stop_status_pulse()

        # Re-enable controls
        self._set_controls_enabled(True)
        self.stats_bar.reset()

        if not self._error_state:
            self.update_status("Ready")

        # Update tray
        if self.tray:
            self.tray.set_processing_state(False)

        _logger.info(MSG_PROCESSING_STOPPED)

    def _on_threshold_changed(self, value):
        """Persist the AAD threshold and apply it to a running worker."""
        self.thresh_val_label.setText(f"{value} dB")
        self.settings.aad_threshold = float(value)
        if self.worker is not None:
            self.worker.set_aad_threshold(float(value))

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
        # Update status state
        state = "ready"
        if "Error" in message:
            state = "error"
        elif any(word in message for word in
                 ("Starting", "Stopping", "Loading", "Isolating", "Processing",
                  "Switching", "Switched", "Initializing", "Downloading",
                  "Installing", "Setting up")):
            state = "processing"

        title_key, sub = self._home_copy(message, state)
        self._title_swap.set_text(HOME_TITLES[title_key])
        if sub != self._status_swap.text():
            # The swap needs the label's effect; the isolating pulse only
            # belongs to the isolating line anyway.
            self._stop_status_pulse()

        def restyle(label=self.status_label, state=state):
            label.setProperty("state", state)
            label.style().unpolish(label)
            label.style().polish(label)

        self._status_swap.set_text(sub, on_apply=restyle)
        self.stats_bar.set_state(state, status_word(state, message))

        _logger.info(f"Status update: {message}")

    @staticmethod
    def _home_copy(message: str, state: str):
        """(HOME_TITLES key, subtitle) for a worker status message."""
        if state == "error":
            return "error", message
        if state == "ready":
            return "ready", (
                HOME_READY_SUB if message.strip() in ("", "Ready") else message)
        lowered = message.lower()
        # "Processing" comes from the worker's loop, after the GUI already
        # said "Isolating audio" (it used to flip Home back to the
        # starting headline).
        if lowered.startswith(("isolating", "processing")):
            return "isolating", HOME_ISOLATING_SUB
        if lowered.startswith("stopping"):
            return "stopping", message
        return "starting", message

    def _start_status_pulse(self) -> None:
        """Breathe the status line while isolating (live-indicator feel).

        Waits for a running text swap to settle: the swap and the pulse
        each need the label's opacity effect, and fades must not nest.
        """
        self._pulse_wanted = True
        if not self._status_swap.busy:
            self._begin_status_pulse()

    def _on_status_settled(self) -> None:
        if self._pulse_wanted and self._status_pulse is None:
            self._begin_status_pulse()

    def _begin_status_pulse(self) -> None:
        try:
            from .animations import cancel_fade, motion_ok
            from PyQt6.QtCore import QEasingCurve, QPropertyAnimation
            from PyQt6.QtWidgets import QGraphicsOpacityEffect
            self._stop_status_pulse()
            self._pulse_wanted = True
            if not motion_ok():
                return
            # The pulse owns the label's effect exclusively: void any
            # entrance fade first so two animations never fight over it
            # (that replaces the effect mid-paint -> QPainter errors).
            cancel_fade(self.status_label)
            eff = QGraphicsOpacityEffect(self.status_label)
            self.status_label.setGraphicsEffect(eff)
            self._status_pulse_eff = eff
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
        self._pulse_wanted = False
        try:
            if self._status_pulse is not None:
                try:
                    self._status_pulse.stop()
                except Exception:
                    pass
                self._status_pulse = None
            # Remove only the pulse's own effect: a text swap may own the
            # label's effect right now.
            eff = getattr(self, "_status_pulse_eff", None)
            self._status_pulse_eff = None
            if eff is not None and hasattr(self, "status_label"):
                try:
                    if self.status_label.graphicsEffect() is eff:
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

        # Stop worker (it restores the default playback device), then the
        # audio process. The worker gives the audio process up to 5 s.
        if self.worker.is_running:
            self.worker.stop()
            self.worker.wait(7000)
        self.worker.shutdown()

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
