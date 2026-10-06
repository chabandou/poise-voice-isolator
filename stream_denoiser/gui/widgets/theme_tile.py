"""
Poise Voice Isolator - Theme Tile Widget

Swatch-style theme picker tile: a rounded square filled with the theme's
main accent color with the theme name inside. The checked tile gets a
thick outline and a bold name.
"""
from PyQt6.QtWidgets import QAbstractButton, QSizePolicy
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QPainter, QColor, QFont, QPen

from ..scaling import sp


class ThemeTile(QAbstractButton):
    """Checkable accent swatch with the theme name."""

    def __init__(self, accent: str, background: str, text_dark: str,
                 name: str, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self._accent = QColor(accent)
        self._background = QColor(background)
        self._text_dark = QColor(text_dark)
        self._name = name
        self.setMinimumSize(self.sizeHint())

    def sizeHint(self):  # noqa: N802 (Qt override)
        return QSize(sp(120), sp(88))

    def paintEvent(self, event):  # noqa: N802 (Qt override)
        side_w, side_h = self.width(), self.height()
        radius = sp(18)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Swatch fill (dimmed when not selected).
        fill = QColor(self._accent)
        if not self.isChecked():
            fill.setAlpha(110)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(0, 0, side_w, side_h, radius, radius)

        # Thick outline for the selected tile (dark ring on the swatch).
        if self.isChecked():
            pen = QPen(self._background, sp(4))
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            inset = sp(4) // 2 + 1
            p.drawRoundedRect(inset, inset, side_w - inset * 2,
                              side_h - inset * 2, radius, radius)

        # Name, bottom-left corner.
        font = QFont("Segoe UI", sp(14))
        font.setWeight(QFont.Weight.Bold if self.isChecked()
                       else QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(self._text_dark)
        pad_left, pad_bottom = sp(12), sp(10)
        p.drawText(pad_left, 0, side_w - pad_left, side_h - pad_bottom,
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                   self._name)
        p.end()
