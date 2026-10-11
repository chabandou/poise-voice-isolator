"""
Poise Voice Isolator - Setup Summary

Read-only "Current setup" card on Home: where audio comes from, which
model is loaded and whether silence skipping is on, with a shortcut to
Settings. Home keeps only the controls you touch every session; the rest
lives in Settings and is summarised here.
"""
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)
from PyQt6.QtCore import Qt, pyqtSignal

from .chip import IconChip
from ..scaling import sp
from ...constants import MODEL_INFO


class SetupSummary(QFrame):
    """Summary card; emits open_settings when the button is pressed."""

    open_settings = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(sp(24), sp(22), sp(24), sp(20))
        layout.setSpacing(0)

        head = QHBoxLayout()
        head.setSpacing(sp(14))
        self.chip = IconChip("sliders")
        head.addWidget(self.chip)
        titles = QVBoxLayout()
        titles.setSpacing(sp(2))
        title = QLabel("Current setup")
        title.setObjectName("card-title")
        sub = QLabel("Change these in Settings")
        sub.setObjectName("row-sub")
        titles.addWidget(title)
        titles.addWidget(sub)
        head.addLayout(titles)
        head.addStretch(1)
        layout.addLayout(head)
        layout.addSpacing(sp(10))

        self._source_value = self._add_row(
            layout, "Source", "Captured through VB-Cable", "System audio")
        self._model_value = self._add_row(layout, "Model", "", "")
        self._model_sub = self._last_sub
        self._aad_value = self._add_row(layout, "Skip silence", "", "")
        self._aad_sub = self._last_sub
        layout.addStretch(1)

        self.settings_btn = QPushButton("Open settings")
        self.settings_btn.setObjectName("ghost")
        self.settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_btn.clicked.connect(self.open_settings)
        row = QHBoxLayout()
        row.addWidget(self.settings_btn)
        row.addStretch(1)
        layout.addLayout(row)

    def _add_row(self, layout, title: str, sub: str, value: str) -> QLabel:
        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(divider)
        row = QHBoxLayout()
        row.setContentsMargins(0, sp(14), 0, sp(14))
        row.setSpacing(sp(16))
        text = QVBoxLayout()
        text.setSpacing(sp(2))
        name = QLabel(title)
        name.setObjectName("row-title")
        caption = QLabel(sub)
        caption.setObjectName("row-sub")
        caption.setWordWrap(True)   # long blurbs must not set the min width
        text.addWidget(name)
        text.addWidget(caption)
        row.addLayout(text, stretch=1)
        val = QLabel(value)
        val.setObjectName("row-value")
        row.addWidget(val, alignment=Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(row)
        self._last_sub = caption
        return val

    def refresh(self, model_id: str, aad_on: bool, threshold_db: float):
        """Re-read the values shown (call after Settings change)."""
        info = MODEL_INFO.get((model_id or "").strip().lower(), {})
        self._model_value.setText(info.get("label", model_id or "-"))
        self._model_sub.setText(
            info.get("card_blurb") or info.get("picker_blurb", ""))
        self._aad_value.setText("On" if aad_on else "Off")
        self._aad_sub.setText(
            f"Anything quieter than {threshold_db:.0f} dB is skipped"
            if aad_on else "Every frame is processed")

    def refresh_theme(self) -> None:
        self.chip.refresh_theme()
