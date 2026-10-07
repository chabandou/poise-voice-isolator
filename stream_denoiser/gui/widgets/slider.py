"""
Poise Voice Isolator - Animated-hover Slider

QSlider with a smoothly crossfading handle hover state. QSS has no
transitions, so the instant :hover snap is replaced here by a 150ms
crossfade between the very same theme colors (text/accent_light for the
fill, accent/text for the ring).

Only colors are ever overridden, per frame, on a widget-local sheet
that merges with the app stylesheet — metrics, groove, dragging, and
the :disabled rules all stay exactly as styled. At rest (or with
reduced motion, or when disabled) no local sheet is installed, so the
plain app QSS — including its instant :hover fallback — applies.
"""
from PyQt6.QtWidgets import QSlider
from PyQt6.QtCore import (
    Qt, QPropertyAnimation, QEasingCurve, pyqtProperty, QEvent,
)
from PyQt6.QtGui import QColor

from ..scaling import sp


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    """Linear blend between two colors (t clamped to [0, 1])."""
    t = max(0.0, min(1.0, t))
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
    )


class HoverSlider(QSlider):
    """QSlider whose handle colors glide in/out on hover."""

    DURATION_MS = 150

    def __init__(self, orientation=Qt.Orientation.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.setMouseTracking(True)
        self._hoverT = 0.0
        self._hover_target = False
        self._anim = QPropertyAnimation(self, b"hoverT", self)
        self._anim.setDuration(self.DURATION_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(self._finish_hover)

    # -- animated property ------------------------------------------------
    def _get_hoverT(self) -> float:  # noqa: N802 (Qt-style name)
        return self._hoverT

    def _set_hoverT(self, value: float) -> None:  # noqa: N802 (Qt-style)
        self._hoverT = float(value)
        self._apply_hover()

    hoverT = pyqtProperty(float, _get_hoverT, _set_hoverT)

    # -- hover tracking (handle rect only, like QSS :hover) -----------------
    def _handle_hit(self, pos) -> bool:
        try:
            from PyQt6.QtWidgets import QStyle, QStyleOptionSlider
            opt = QStyleOptionSlider()
            self.initStyleOption(opt)
            rect = self.style().subControlRect(
                QStyle.ComplexControl.CC_Slider, opt,
                QStyle.SubControl.SC_SliderHandle, self)
            return rect.contains(pos)
        except Exception:
            return False

    def mouseMoveEvent(self, event):  # noqa: N802 (Qt override)
        super().mouseMoveEvent(event)
        try:
            hit = self._handle_hit(event.position().toPoint())
            if hit != self._hover_target:
                self._target_hover(hit)
        except Exception:
            pass

    def leaveEvent(self, event):  # noqa: N802 (Qt override)
        try:
            self._target_hover(False)
        except Exception:
            pass
        super().leaveEvent(event)

    def changeEvent(self, event):  # noqa: N802 (Qt override)
        super().changeEvent(event)
        try:
            if event.type() == QEvent.Type.EnabledChange and not self.isEnabled():
                self._anim.stop()
                self._hoverT = 0.0
                self._hover_target = False
                self.setStyleSheet("")
        except Exception:
            pass

    # -- crossfade ------------------------------------------------------------
    def _theme_pair(self):
        from ..themes import current as current_theme
        palette = current_theme()
        return (QColor(palette["text"]), QColor(palette["accent_light"]),
                QColor(palette["accent"]), QColor(palette["text"]))

    def _target_hover(self, on: bool) -> None:
        self._hover_target = on
        try:
            from ..animations import motion_ok
            if not motion_ok() or not self.isEnabled():
                return  # instant QSS :hover (or :disabled) applies
        except Exception:
            pass
        try:
            self._anim.stop()
            self._anim.setStartValue(self._hoverT)
            self._anim.setEndValue(1.0 if on else 0.0)
            self._anim.start()
        except Exception:
            pass

    def _apply_hover(self) -> None:
        try:
            if not self.isEnabled() or self._hoverT <= 0.0:
                if self.styleSheet():
                    self.setStyleSheet("")
                return
            text, accent_light, accent, text_again = self._theme_pair()
            bg = _mix(text, accent_light, self._hoverT)
            ring = _mix(accent, text_again, self._hoverT)
            bw = max(1, sp(2))
            self.setStyleSheet(
                "QSlider::handle:horizontal{"
                f"background:{bg.name()};"
                f"border:{bw}px solid {ring.name()};"
                "}")
        except Exception:
            pass

    def _finish_hover(self) -> None:
        try:
            if self._hoverT <= 0.0 and self.styleSheet():
                self.setStyleSheet("")
        except Exception:
            pass
