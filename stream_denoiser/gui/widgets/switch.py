"""
Poise Voice Isolator - Toggle Switch Widget

Sliding toggle painted manually: a rounded-square outline track with a
square-ish knob. Off it is a quiet muted outline; on, the outline and the
knob take the accent with a faint accent fill behind.
"""
from PyQt6.QtWidgets import QAbstractButton, QSizePolicy
from PyQt6.QtCore import (
    QRectF, QSize, Qt, QPropertyAnimation, QEasingCurve, pyqtProperty,
)
from PyQt6.QtGui import QPainter, QColor, QPen

from ..scaling import sp
from ..themes import current as current_theme


class ToggleSwitch(QAbstractButton):
    """Sliding on/off switch bound to the checked state."""

    def __init__(self, parent=None, checked: bool = False):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        try:
            from ..cursors import apply_link_cursor
            apply_link_cursor(self)
        except Exception:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setMinimumSize(self.sizeHint())

        self._knob = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob")
        self._anim.setDuration(200)
        spring = QEasingCurve(QEasingCurve.Type.OutBack)
        spring.setAmplitude(0.9)
        self._anim.setEasingCurve(spring)
        # Block signals so __init__ doesn't animate from 0.
        self.blockSignals(True)
        self.setChecked(checked)
        self.blockSignals(False)
        self.toggled.connect(self._on_toggled)

    def sizeHint(self):  # noqa: N802 (Qt override)
        return QSize(sp(50), sp(26))

    # -- animation property ------------------------------------------------
    def _get_knob(self) -> float:
        return self._knob

    def _set_knob(self, value: float) -> None:
        self._knob = value
        self.update()

    knob = pyqtProperty(float, _get_knob, _set_knob)

    def _on_toggled(self, checked: bool) -> None:
        try:
            from ..animations import motion_ok
            if not motion_ok():
                self._knob = 1.0 if checked else 0.0
                self.update()
                return
        except Exception:
            pass
        self._anim.stop()
        self._anim.setStartValue(self._knob)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def setChecked(self, checked: bool) -> None:  # noqa: N802 (Qt override)
        # NOTE: never snap _knob here — the toggled handler tweens it,
        # which is what makes the switch slide instead of jumping.
        # While signals are blocked (init / restore) snap instantly.
        if self.signalsBlocked():
            self._knob = 1.0 if checked else 0.0
        super().setChecked(checked)
        self.update()

    # -- painting -----------------------------------------------------------
    @staticmethod
    def _mix(a: QColor, b: QColor, t: float) -> QColor:
        t = max(0.0, min(1.0, t))
        return QColor(
            int(a.red() + (b.red() - a.red()) * t),
            int(a.green() + (b.green() - a.green()) * t),
            int(a.blue() + (b.blue() - a.blue()) * t),
            int(a.alpha() + (b.alpha() - a.alpha()) * t),
        )

    def knob_geometry(self):
        """(left x, side) of the knob. NOT clamped: the slide rides an
        OutBack spring, so the knob overshoots the far end and settles
        back (the toggle's bounce)."""
        w, h = self.width(), self.height()
        inset = h * 4.0 / 26.0          # knob margin (4px at 26px tall)
        knob = h - 2.0 * inset
        travel = w - 2.0 * inset - knob
        return inset + travel * self._knob, knob

    def paintEvent(self, event):  # noqa: N802 (Qt override)
        w, h = self.width(), self.height()
        border_w = max(1.0, float(sp(1)))
        x, knob = self.knob_geometry()
        inset = h * 4.0 / 26.0
        # Colours are blended with a clamped factor so they never
        # extrapolate past either endpoint (that reads as a flash at the
        # end of the slide); only the knob's position springs past them.
        t = max(0.0, min(1.0, self._knob))

        palette = current_theme()
        accent = QColor(palette["accent"])
        muted = QColor(palette["muted"])
        off_edge = QColor(muted)
        off_edge.setAlpha(110)
        off_knob = QColor(muted)
        off_knob.setAlpha(150)
        edge = self._mix(off_edge, accent, t)
        knob_color = self._mix(off_knob, accent, t)
        wash = QColor(accent)
        wash.setAlphaF(0.14 * t)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        half = border_w / 2.0
        track = QRectF(half, half, w - border_w, h - border_w)
        radius = h * 8.0 / 26.0
        p.setPen(QPen(edge, border_w))
        p.setBrush(wash)
        p.drawRoundedRect(track, radius, radius)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(knob_color)
        p.drawRoundedRect(QRectF(x, inset, knob, knob),
                          knob * 5.0 / 18.0, knob * 5.0 / 18.0)
        p.end()
