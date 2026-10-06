"""
Poise Voice Isolator - Sidebar Navigation

Left navigation rail matching the mockup: logo row, nav buttons with an
active indicator, and a version label pinned to the bottom.
"""
from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QWidget,
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QFont, QPixmap

from .phosphor import PhosphorIcon
from ..scaling import isp, sp
from ..themes import current as current_theme
from ..utils import get_icon_path
from ... import __version__


class NavButton(QPushButton):
    """Sidebar navigation entry with an active state."""

    def __init__(self, index: int, icon: str, text: str, parent=None):
        super().__init__(parent)
        self._index = index
        self.setObjectName("nav")
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(26, 0, 8, 0)
        layout.setSpacing(12)
        self._icon = PhosphorIcon(
            icon, color=current_theme()["nav_muted"], size=20)
        layout.addWidget(self._icon)
        self._label = QLabel(text)
        self._label.setObjectName("nav-text")
        layout.addWidget(self._label, stretch=1)

    @property
    def index(self) -> int:
        return self._index

    def set_active(self, active: bool) -> None:
        palette = current_theme()
        self.setChecked(active)
        self.setProperty("active", active)
        self._icon.set_color(
            palette["accent_light"] if active else palette["nav_muted"])
        # Repolish the label too: polishing only the button leaves the
        # child's QSS color (nav-text) frozen on its previous state.
        for widget in (self, self._label):
            self.style().unpolish(widget)
            self.style().polish(widget)


class Sidebar(QFrame):
    """Navigation rail. Emits page_requested(index) on nav clicks."""

    page_requested = pyqtSignal(int)

    PAGES = (
        ("Home", "waveform"),
        ("Settings", "gear"),
        ("Logs", "doc"),
        ("About", "info"),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(sp(216))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 24, 16, 22)
        layout.setSpacing(8)

        # Logo row (keeps its 16px from the edge via its own margins).
        logo_widget = QWidget()
        logo_widget_layout = QHBoxLayout(logo_widget)
        logo_widget_layout.setContentsMargins(16, 0, 0, 0)
        logo_widget_layout.setSpacing(12)
        self._logo_icon = self._make_logo_icon()
        logo_widget_layout.addWidget(self._logo_icon)
        logo_label = QLabel("POISE")
        logo_label.setObjectName("logo")
        font = logo_label.font()
        font.setPointSize(sp(19))
        font.setWeight(QFont.Weight.DemiBold)
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 135)
        logo_label.setFont(font)
        logo_widget_layout.addWidget(logo_label)
        logo_widget_layout.addStretch()
        layout.addWidget(logo_widget)
        layout.addSpacing(30)

        # Nav buttons.
        self._buttons = []
        for i, (text, icon) in enumerate(self.PAGES):
            btn = NavButton(i, icon, text)
            btn.clicked.connect(self._on_nav_clicked)
            layout.addWidget(btn)
            self._buttons.append(btn)
        self._buttons[0].set_active(True)

        layout.addStretch()

        # Version footer.
        version = QLabel(f"POISE v{__version__}")
        version.setObjectName("version")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version)

    @staticmethod
    def _make_logo_icon() -> QLabel:
        """App icon pixmap, falling back to the painted glyph."""
        icon_path = get_icon_path()
        if icon_path:
            label = QLabel()
            label.setObjectName("logo-icon")
            side = isp(34)
            label.setPixmap(
                QPixmap(icon_path).scaled(
                    side, side, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
            return label
        return PhosphorIcon("waveform", size=26)

    def _on_nav_clicked(self):
        btn = self.sender()
        if not isinstance(btn, NavButton):
            return
        self.set_active_page(btn.index)
        self.page_requested.emit(btn.index)

    def set_active_page(self, index: int) -> None:
        for i, btn in enumerate(self._buttons):
            btn.set_active(i == index)

    def refresh_theme(self) -> None:
        """Re-apply state colors after a theme switch."""
        for btn in self._buttons:
            btn.set_active(btn.isChecked())
        self._reload_logo()

    def _reload_logo(self) -> None:
        """Reload the logo pixmap for the active theme's icon variant."""
        if isinstance(self._logo_icon, PhosphorIcon):
            return  # painted fallback has no file to reload
        icon_path = get_icon_path()
        if icon_path:
            side = isp(34)
            self._logo_icon.setPixmap(
                QPixmap(icon_path).scaled(
                    side, side, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
