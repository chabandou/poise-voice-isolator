"""
Poise Voice Isolator - Settings Row

A game-menu style list row: title (+ subtitle) on the left, a control on
the right. Hovering or focusing the row lights it up with an accent wash
and a diamond marker in the secondary colour. The wash fades in while
it extends from part-way across to its full reach, and fades out while
drawing back, so the light grows out of the left edge rather than
wiping on from nothing. A row
whose control is a toggle flips it from a click anywhere on the row.
Rows sit flush inside a card, so the first/last rows clip their wash to
the card's rounded corners.
"""
from PyQt6.QtWidgets import (
    QAbstractButton, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)
from PyQt6.QtCore import QEasingCurve, QEvent, QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor, QLinearGradient, QPainter, QPainterPath,
)

from ..animations import Blend
from ..scaling import sp
from ..themes import current as current_theme

CARD_RADIUS = 16
LIT_IN_MS = 260      # light up: responsive, settles softly
LIT_OUT_MS = 320     # let go: a touch slower, never lingering
LIT_IN_EASE = QEasingCurve.Type.OutCubic
LIT_OUT_EASE = QEasingCurve.Type.OutQuad
#: How far across the row the lit wash reaches (fraction of the width).
WASH_REACH = 0.75
#: Where the wash's front starts (fraction of the reach) when it begins
#: to light: it extends from here as it fades in, and draws back here as
#: it fades out.
WASH_FROM = 0.4
WASH_ALPHA = 0.14    # strength at the left edge, fading to 0 at the reach
WASH_EDGE = 0.3      # soft front, as a fraction of how far it reaches
WASH_STOPS = 16


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
        self._lit_blend = Blend(self, self.update, LIT_IN_MS, LIT_IN_EASE)
        self._pressed = False
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
        self._sync_cursor()

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

    # -- whole-row toggle ------------------------------------------------------
    @property
    def toggle(self) -> QAbstractButton | None:
        """The row's switch when its control is a checkable button (the
        whole row flips it), else None."""
        control = self._control
        if isinstance(control, QAbstractButton) and control.isCheckable():
            return control
        return None

    def _toggle_ready(self) -> bool:
        toggle = self.toggle
        return toggle is not None and toggle.isEnabled()

    def _sync_cursor(self) -> None:
        if self._toggle_ready():
            try:
                from ..cursors import apply_link_cursor
                apply_link_cursor(self)
            except Exception:
                self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.unsetCursor()

    def mousePressEvent(self, event):  # noqa: N802 (Qt override)
        if (event.button() == Qt.MouseButton.LeftButton
                and self._toggle_ready()):
            self._pressed = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802 (Qt override)
        if self._pressed and event.button() == Qt.MouseButton.LeftButton:
            self._pressed = False
            # Like a button: only a release still over the row counts.
            if (self.rect().contains(event.position().toPoint())
                    and self._toggle_ready()):
                self.toggle.click()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # -- highlight state ------------------------------------------------------------
    def _watch(self, widget: QWidget) -> None:
        widget.installEventFilter(self)
        for child in widget.findChildren(QWidget):
            child.installEventFilter(self)

    def eventFilter(self, obj, event):  # noqa: N802 (Qt override)
        kind = event.type()
        if kind == QEvent.Type.EnabledChange and obj is self._control:
            self._sync_cursor()              # no hand over a locked switch
        elif kind == QEvent.Type.FocusIn:
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
        if self.is_lit:
            self._lit_blend.set_target(1.0, duration_ms=LIT_IN_MS,
                                       easing=LIT_IN_EASE)
        else:
            self._lit_blend.set_target(0.0, duration_ms=LIT_OUT_MS,
                                       easing=LIT_OUT_EASE)

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

    def wash_front(self, lit: float) -> float:
        """x of the wash's front at light level `lit` (0..1): from
        WASH_FROM of the reach when it starts lighting, to the reach."""
        reach = self.width() * WASH_REACH
        lit = max(0.0, min(1.0, lit))
        return reach * (WASH_FROM + (1.0 - WASH_FROM) * lit)

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

        # The resting wash fades from WASH_ALPHA at the left to nothing at
        # the reach. While lighting it fades in (opacity = lit) and its
        # front travels from WASH_FROM to the reach; the front is a soft
        # smoothstep falloff so there is never a visible edge.
        accent = QColor(palette["accent"])
        reach = w * WASH_REACH
        front = self.wash_front(lit)
        edge = max(1.0, front * WASH_EDGE)
        wash = QLinearGradient(0, 0, front, 0)
        for i in range(WASH_STOPS + 1):
            t = i / WASH_STOPS
            x = front * t
            soft = max(0.0, min(1.0, (front - x) / edge))
            soft = soft * soft * (3.0 - 2.0 * soft)          # smoothstep
            strength = WASH_ALPHA * lit * (1.0 - x / reach) * soft
            color = QColor(accent)
            color.setAlphaF(max(0.0, min(1.0, strength)))
            wash.setColorAt(t, color)
        p.fillRect(QRectF(0, 0, front, h), wash)

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
