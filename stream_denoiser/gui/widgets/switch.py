"""
Poise Voice Isolator - Toggle Switch Widget

iOS-style sliding toggle switch, painted manually for full control.
"""
from PyQt6.QtWidgets import QAbstractButton, QSizePolicy
from PyQt6.QtCore import QSize, Qt, QPropertyAnimation, QEasingCurve, pyqtProperty
from PyQt6.QtGui import QPainter, QColor

from ..scaling import sp
from ..themes import current as current_theme


class ToggleSwitch(QAbstractButton):
    """Sliding on/off switch bound to the checked state."""

    def __init__(self, parent=None, checked: bool = False):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setMinimumSize(self.sizeHint())

        self._knob = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob")
        self._anim.setDuration(120)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._on_toggled)

    def sizeHint(self):  # noqa: N802 (Qt override)
        return QSize(sp(52), sp(30))

    # -- animation property ------------------------------------------------
    def _get_knob(self) -> float:
        return self._knob

    def _set_knob(self, value: float) -> None:
        self._knob = value
        self.update()

    knob = pyqtProperty(float, _get_knob, _set_knob)

    def _on_toggled(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._knob)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def setChecked(self, checked: bool) -> None:  # noqa: N802 (Qt override)
        self._knob = 1.0 if checked else 0.0
        super().setChecked(checked)
        self.update()

    # -- painting -----------------------------------------------------------
    def paintEvent(self, event):  # noqa: N802 (Qt override)
        w, h = self.width(), self.height()
        knob_d = h - 6
        travel = w - 6 - knob_d
        cx = 3 + travel * self._knob + knob_d / 2

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)

        # Track: theme accent when on, groove tone when off.
        palette = current_theme()
        on = QColor(palette["accent"])
        off = QColor(palette["groove"])
        t = self._knob
        track = QColor(
            int(off.red() + (on.red() - off.red()) * t),
            int(off.green() + (on.green() - off.green()) * t),
            int(off.blue() + (on.blue() - off.blue()) * t),
        )
        p.setBrush(track)
        p.drawRoundedRect(0, 0, w, h, h / 2, h / 2)

        # Knob: dark on light accents (e.g. Mono silver), white otherwise.
        knob = QColor(palette["bg"]) if on.lightnessF() > 0.7 else QColor("#f8fafc")
        p.setBrush(knob)
        p.drawEllipse(int(cx - knob_d / 2), 3, knob_d, knob_d)
        p.end()
