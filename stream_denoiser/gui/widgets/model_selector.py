"""
Poise Voice Isolator - Model Selector

Home's model card content: icon chip and title over the same boxed
dropdown as the output device. Lists the engines usable on this machine
(Settings' model cards also show the unusable ones, with the reason).
Exposes the QComboBox-like surface ModelCards has, so MainWindow keeps
the two in step: currentText() / setCurrentText() / currentTextChanged.
"""
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from PyQt6.QtCore import pyqtSignal

from .chip import IconChip
from .combo import BLURB_ROLE, AnimatedComboBox
from ..animations import flash_colour
from ..scaling import sp
from ..themes import current as current_theme
from ...constants import MODEL_INFO


class ModelSelector(QWidget):
    """Engine dropdown; the value is the engine id (a MODEL_INFO key)."""

    currentTextChanged = pyqtSignal(str)
    CAPTION = "Takes effect the next time you start"
    LOCKED_NOTE = "Locked while running"

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(sp(14))

        header = QHBoxLayout()
        header.setSpacing(sp(14))
        self._chip = IconChip("cpu", size=48, icon_size=24)
        header.addWidget(self._chip)
        titles = QVBoxLayout()
        titles.setSpacing(sp(2))
        title = QLabel("Model")
        title.setObjectName("device-title")
        titles.addWidget(title)
        self._subtitle = QLabel(self.CAPTION)
        self._subtitle.setObjectName("row-sub")
        titles.addWidget(self._subtitle)
        header.addLayout(titles)
        header.addStretch(1)
        layout.addLayout(header)

        self._combo = AnimatedComboBox()
        self._combo.setObjectName("device-combo")
        self._combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._combo.setMinimumContentsLength(14)
        try:
            from ...engines import available_models
            usable = set(available_models())
        except Exception:
            usable = set(MODEL_INFO)
        for model_id, info in MODEL_INFO.items():
            if model_id in usable:
                self._combo.addItem(info.get("label", model_id), model_id)
                # The open list shows Settings' card blurb under the name.
                self._combo.setItemData(
                    self._combo.count() - 1,
                    info.get("card_blurb") or info.get("picker_blurb", ""),
                    BLURB_ROLE)
        self._combo.currentIndexChanged.connect(self._on_index_changed)
        layout.addWidget(self._combo)
        # Header + combo stay at the top if the card grows taller.
        layout.addStretch(1)

    def _on_index_changed(self, index: int) -> None:
        model_id = self._combo.itemData(index)
        if model_id:
            self.currentTextChanged.emit(model_id)

    # -- QComboBox-like surface ---------------------------------------------
    def currentText(self) -> str:  # noqa: N802 (Qt style)
        return self._combo.currentData() or ""

    def setCurrentText(self, text: str) -> None:  # noqa: N802 (Qt style)
        index = self._combo.findData((text or "").strip().lower())
        if index >= 0:
            self._combo.setCurrentIndex(index)

    def models(self):
        return [self._combo.itemData(i) for i in range(self._combo.count())]

    def set_locked(self, locked: bool) -> None:
        """No switching while running; the caption says why."""
        self._combo.setEnabled(not locked)
        self._subtitle.setText(self.LOCKED_NOTE if locked else self.CAPTION)

    @property
    def is_locked(self) -> bool:
        return not self._combo.isEnabled()

    def enterEvent(self, event):  # noqa: N802 (Qt override)
        self._chip.play()   # the chip's die squeezes
        super().enterEvent(event)

    def mousePressEvent(self, event):  # noqa: N802 (Qt override)
        # A click on the locked (disabled) combo arrives here: say why.
        if self.is_locked and self._combo.geometry().contains(
                event.position().toPoint()):
            self._combo.jiggle()
            flash_colour(self._subtitle, current_theme()["secondary"])
        super().mousePressEvent(event)

    def refresh_theme(self) -> None:
        self._chip.refresh_theme()
