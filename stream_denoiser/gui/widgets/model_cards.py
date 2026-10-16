"""
Poise Voice Isolator - Model Cards

Selectable cards for the denoising engines (replaces the model dropdown),
stacked as full-width rows: name over the tradeoff blurb.
Exposes the small QComboBox-like surface MainWindow already uses:
currentText() / setCurrentText() / currentTextChanged / setEnabled().
The value is the engine id (a MODEL_INFO key, e.g. "deepfilternet3").
Engines that are not usable here stay visible but disabled, with the
reason in place of the blurb.
"""
from PyQt6.QtWidgets import (
    QButtonGroup, QLabel, QPushButton, QVBoxLayout, QWidget,
)
from PyQt6.QtCore import QEvent, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen

from ..animations import Blend, mix_rgba
from ..scaling import sp
from ..themes import current as current_theme
from ...constants import MODEL_INFO


class _ModelCard(QPushButton):
    """One engine card: checkable, with a diamond marker when selected.

    The surface is painted here (QSS cannot transition): border and fill
    glide between rest, hover and selected, and the diamond fades/grows in.
    """

    def __init__(self, model_id: str, name: str, blurb: str, parent=None):
        super().__init__(parent)
        self.model_id = model_id
        self.setObjectName("model-card")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        # Right margin: room for the selection diamond.
        layout.setContentsMargins(sp(20), sp(14), sp(52), sp(14))
        layout.setSpacing(sp(2))
        self._name = QLabel(name)
        self._name.setObjectName("model-name")
        self._blurb = QLabel(blurb)
        self._blurb.setObjectName("model-blurb")
        self._blurb.setWordWrap(True)
        for label in (self._name, self._blurb):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self._name)
        layout.addWidget(self._blurb)

        self._hover = Blend(self, self.update, 150)
        self._check = Blend(self, self.update, 200)
        self.toggled.connect(self._on_toggled)

    def _on_toggled(self, checked: bool) -> None:
        # Restoring the saved choice before the window is shown must not
        # animate; real user changes do.
        self._check.set_target(1.0 if checked else 0.0,
                               animated=self.isVisible())

    def set_blurb(self, text: str) -> None:
        self._blurb.setText(text)
        self._fit_height()

    def _fit_height(self) -> None:
        """Grow to the wrapped blurb. A push button's height is fixed at
        its minimum, and its size hint ignores its layout: a narrow card
        would clip the text."""
        need = max(sp(72), self.layout().totalHeightForWidth(self.width()))
        if self.minimumHeight() != need:
            self.setMinimumHeight(need)

    def resizeEvent(self, event):  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._fit_height()

    def enterEvent(self, event):  # noqa: N802 (Qt override)
        if self.isEnabled():
            self._hover.set_target(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802 (Qt override)
        self._hover.set_target(0.0)
        super().leaveEvent(event)

    def changeEvent(self, event):  # noqa: N802 (Qt override)
        super().changeEvent(event)
        if (event.type() == QEvent.Type.EnabledChange
                and not self.isEnabled()):
            self._hover.snap(0.0)

    def paintEvent(self, event):  # noqa: N802 (Qt override)
        palette = current_theme()
        hover, check = self._hover.value, self._check.value
        secondary = QColor(palette["secondary"])
        w, h = self.width(), self.height()
        rect = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
        radius = float(sp(12))

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            edge = QColor(148, 163, 184)
            edge.setAlphaF(0.22)
            pen = QPen(edge, 1.0)
            pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect, radius, radius)
            p.end()
            return

        pill = QColor(palette["pill"])
        tint = mix_rgba(pill, secondary, 0.08)
        fill = mix_rgba(pill, tint, check)
        rest = QColor(148, 163, 184)
        rest.setAlphaF(0.18)
        hover_edge = QColor(secondary)
        hover_edge.setAlphaF(0.6)
        edge = mix_rgba(mix_rgba(rest, hover_edge, hover), secondary, check)
        p.setPen(QPen(edge, 1.0))
        p.setBrush(fill)
        p.drawRoundedRect(rect, radius, radius)

        if check > 0.01:
            marker = QColor(secondary)
            marker.setAlphaF(check)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(marker)
            d = sp(7) * (0.6 + 0.4 * check)
            p.translate(QPointF(w - sp(28), h / 2.0))
            p.rotate(45)
            p.drawRoundedRect(QRectF(-d, -d, 2 * d, 2 * d), 2, 2)
        p.end()


class ModelCards(QWidget):
    """Radio-style engine picker."""

    currentTextChanged = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(sp(10))
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
            layout.addWidget(card)
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
