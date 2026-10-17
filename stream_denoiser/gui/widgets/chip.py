"""
Poise Voice Isolator - Icon Chip

Rounded-square tile holding a Phosphor icon in the theme's secondary
colour (tinted wash behind it). Used as the lead mark of cards; play()
runs the icon's hover motion (the speaker's waves emit, the chip's die
squeezes) when its card is pointed at.
"""
from PyQt6.QtWidgets import QFrame, QHBoxLayout
from PyQt6.QtCore import Qt

from .phosphor import MotionIcon
from ..scaling import sp
from ..themes import current as current_theme


class IconChip(QFrame):
    """Secondary-tinted icon tile (QSS: QFrame#chip)."""

    def __init__(self, icon: str, size: int = 44, icon_size: int = 22,
                 parent=None):
        super().__init__(parent)
        self.setObjectName("chip")
        self.setFixedSize(sp(size), sp(size))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._icon = MotionIcon(
            icon, color=current_theme()["secondary"], size=icon_size)
        layout.addWidget(self._icon, alignment=Qt.AlignmentFlag.AlignCenter)

    def play(self) -> None:
        """The icon's hover motion (if it has one)."""
        self._icon.play()

    def refresh_theme(self) -> None:
        """Re-tint after a theme switch (QSS wash follows the sheet)."""
        self._icon.set_color(current_theme()["secondary"])
