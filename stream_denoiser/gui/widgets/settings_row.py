"""
Poise Voice Isolator - Settings Row

A game-menu style list row: title (+ subtitle) on the left, a control on
the right. Hovering or focusing the row lights it up with an accent wash
fading in from the left and a diamond marker in the secondary colour.
Rows sit flush inside a card, so the first/last rows clip their wash to
the card's rounded corners.
"""
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from PyQt6.QtCore import QEvent, QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor, QLinearGradient, QPainter, QPainterPath,
)

from ..animations import Blend
from ..scaling import sp
from ..themes import current as current_theme

CARD_RADIUS = 16


class SettingsRow(QFrame):
    """Title/subtitle + right-hand control with a menu-style highlight."""

    def __init__(self, title: str, subtitle: str = "",
                 control: QWidget = None, control_width: int = 0,
                 parent=None):
        super().__init__(parent)
        self.setObjectName("setting-row")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMinimumHeight(sp(74))
        self._hover = False
        self._focus_within = False
        self._lit_blend = Blend(self, self.update, 150)
        self._first = False
        self._last = False
        self._subtitle = subtitle

        row = QHBoxLayout(self)
        row.setContentsMargins(sp(52), sp(8), sp(28), sp(8))
        row.setSpacing(sp(24))

        text = QVBoxLayout()
        text.setSpacing(sp(2))
        self._title = QLabel(title)
        self._title.setObjectName("row-title")
        text.addWidget(self._title)
        self._sub = QLabel(subtitle)
        self._sub.setObjectName("row-sub")
        self._sub.setWordWrap(True)
        self._sub.setVisible(bool(subtitle))
        text.addWidget(self._sub)
        row.addLayout(text, stretch=1)

        self._control = control
        if control is not None:
            if control_width:
                control.setMinimumWidth(sp(control_width))
            row.addWidget(control, alignment=Qt.AlignmentFlag.AlignVCenter)
            self._watch(control)

    # -- structure -----------------------------------------------------------
    def set_position(self, first: bool, last: bool) -> None:
        """Mark the row's slot in its card (clips the wash to the corners)."""
        self._first, self._last = first, last
        self.update()

    def set_locked(self, locked: bool, note: str = "Locked while running"):
        """Swap the subtitle for a lock note while the control is frozen."""
        self._sub.setText(note if locked else self._subtitle)
        self._sub.setVisible(bool(locked or self._subtitle))
        if self._control is not None:
            self._control.setEnabled(not locked)

    # -- highlight state ------------------------------------------------------------
    def _watch(self, widget: QWidget) -> None:
        widget.installEventFilter(self)
        for child in widget.findChildren(QWidget):
            child.installEventFilter(self)

    def eventFilter(self, obj, event):  # noqa: N802 (Qt override)
        kind = event.type()
        if kind == QEvent.Type.FocusIn:
            # Light up for keyboard navigation only: the window's initial
            # focus (or a click, already covered by hover) must not leave
            # a row highlighted.
            self._focus_within = event.reason() in (
                Qt.FocusReason.TabFocusReason,
                Qt.FocusReason.BacktabFocusReason,
                Qt.FocusReason.ShortcutFocusReason)
            self._sync_lit()
        elif kind == QEvent.Type.FocusOut:
            self._focus_within = False
            self._sync_lit()
        return super().eventFilter(obj, event)

    def _sync_lit(self) -> None:
        self._lit_blend.set_target(1.0 if self.is_lit else 0.0)

    def enterEvent(self, event):  # noqa: N802 (Qt override)
        self._hover = True
        self._sync_lit()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802 (Qt override)
        self._hover = False
        self._sync_lit()
        super().leaveEvent(event)

    @property
    def is_lit(self) -> bool:
        return self._hover or self._focus_within

    def paintEvent(self, event):  # noqa: N802 (Qt override)
        super().paintEvent(event)
        lit = self._lit_blend.value
        if lit <= 0.01:
            return
        palette = current_theme()
        w, h = self.width(), self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        clip = QPainterPath()
        # Winding fill: the default odd-even rule turns the overlap of the
        # rounded rect and the squaring rects into holes (half-lit rows).
        clip.setFillRule(Qt.FillRule.WindingFill)
        r = sp(CARD_RADIUS)
        clip.addRoundedRect(QRectF(0, 0, w, h), r, r)
        if not self._first:
            clip.addRect(QRectF(0, 0, w, h / 2))
        if not self._last:
            clip.addRect(QRectF(0, h / 2, w, h / 2))
        p.setClipPath(clip)

        accent = QColor(palette["accent"])
        wash = QLinearGradient(0, 0, w * 0.75, 0)
        start = QColor(accent)
        start.setAlpha(int(255 * 0.14 * lit))
        end = QColor(accent)
        end.setAlpha(0)
        wash.setColorAt(0.0, start)
        wash.setColorAt(1.0, end)
        p.fillRect(QRectF(0, 0, w, h), wash)

        p.setClipping(False)
        p.setPen(Qt.PenStyle.NoPen)
        marker = QColor(palette["secondary"])
        marker.setAlphaF(lit)
        p.setBrush(marker)
        d = sp(5) * (0.6 + 0.4 * lit)
        p.translate(QPointF(sp(26), h / 2))
        p.rotate(45)
        p.drawRoundedRect(QRectF(-d, -d, 2 * d, 2 * d), 2, 2)
        p.end()
