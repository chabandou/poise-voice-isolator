"""
Poise Voice Isolator - Model Cards

Selectable cards for the denoising engines (replaces the model dropdown).
Exposes the small QComboBox-like surface MainWindow already uses:
currentText() / setCurrentText() / currentTextChanged / setEnabled().
The value is the engine id (a MODEL_INFO key, e.g. "deepfilternet3").
Engines that are not usable here stay visible but disabled, with the
reason in place of the blurb.
"""
from PyQt6.QtWidgets import (
    QButtonGroup, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)
from PyQt6.QtCore import QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter

from ..scaling import sp
from ..themes import current as current_theme
from ...constants import MODEL_INFO


class _ModelCard(QPushButton):
    """One engine card: checkable, with a diamond marker when selected."""

    def __init__(self, model_id: str, name: str, blurb: str, parent=None):
        super().__init__(parent)
        self.model_id = model_id
        self.setObjectName("model-card")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(sp(96))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(sp(20), sp(16), sp(20), sp(16))
        layout.setSpacing(sp(4))
        self._name = QLabel(name)
        self._name.setObjectName("model-name")
        self._blurb = QLabel(blurb)
        self._blurb.setObjectName("model-blurb")
        self._blurb.setWordWrap(True)
        for label in (self._name, self._blurb):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self._name)
        layout.addWidget(self._blurb)
        layout.addStretch(1)

    def set_blurb(self, text: str) -> None:
        self._blurb.setText(text)

    def paintEvent(self, event):  # noqa: N802 (Qt override)
        super().paintEvent(event)
        if not self.isChecked():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(current_theme()["secondary"]))
        d = sp(7)
        p.translate(QPointF(self.width() - sp(26), sp(26)))
        p.rotate(45)
        p.drawRoundedRect(-d, -d, 2 * d, 2 * d, 2, 2)
        p.end()


class ModelCards(QWidget):
    """Radio-style engine picker."""

    currentTextChanged = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(sp(14))
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._cards = {}

        try:
            from ...engines import available_models, model_unavailable_reason
            usable = set(available_models())
        except Exception:
            usable, model_unavailable_reason = set(MODEL_INFO), None

        for model_id, info in MODEL_INFO.items():
            ok = model_id in usable
            blurb = info.get("card_blurb") or info.get("picker_blurb", "")
            if not ok and model_unavailable_reason is not None:
                reason = model_unavailable_reason(model_id)
                if reason:
                    blurb = f"Unavailable: {reason}"
            card = _ModelCard(model_id, info.get("label", model_id), blurb)
            card.setEnabled(ok)
            card.setProperty("available", ok)
            self._group.addButton(card)
            self._cards[model_id] = card
            layout.addWidget(card, stretch=1)
        self._group.buttonToggled.connect(self._on_toggled)

        first = next((m for m, c in self._cards.items() if c.isEnabled()), None)
        if first:
            self._cards[first].setChecked(True)

    def _on_toggled(self, button, checked: bool) -> None:
        if checked:
            self.currentTextChanged.emit(button.model_id)

    # -- QComboBox-like surface ---------------------------------------------------
    def currentText(self) -> str:
        for model_id, card in self._cards.items():
            if card.isChecked():
                return model_id
        return ""

    def setCurrentText(self, text: str) -> None:  # noqa: N802 (Qt style)
        card = self._cards.get((text or "").strip().lower())
        if card is not None and card.isEnabled():
            card.setChecked(True)

    def models(self):
        return list(self._cards)
