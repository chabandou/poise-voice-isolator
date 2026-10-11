"""
Poise Voice Isolator - Power Button Widget

Large circular glowing power button matching the mockup: cyan disc with
an outer glow while active, dark disc while idle, red ring on error.
Keeps the old ToggleButton signal API (toggled_state / set_active /
set_transitioning / is_active) so MainWindow wiring is unchanged.

Apple-style juice (all layout-safe, paint-time only):
- press squash to ~0.93 while held (OutCubic down, spring back)
- success pop (OutBack) when processing starts
- breathing glow loop while active
- spinning arc while transitioning (Starting... / Stopping...)
All motion respects POISE_NO_ANIM / POISE_REDUCE_MOTION.
"""
from PyQt6.QtWidgets import QAbstractButton, QSizePolicy
from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal, pyqtProperty, QEasingCurve
from PyQt6.QtGui import (
    QPainter, QColor, QRadialGradient, QPen, QFont,
)

from ..scaling import sp
from ..themes import current as current_theme


class PowerButton(QAbstractButton):
    """Glowing circular power button."""

    toggled_state = pyqtSignal(bool)  # True = started, False = stopped

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        try:
            from ..cursors import apply_link_cursor
            apply_link_cursor(self)
        except Exception:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setMinimumSize(self.sizeHint())

        self._is_active = False
        self._is_transitioning = False
        self._has_error = False

        # Animation state (paint-time only — never touches layout).
        self._press = 0.0      # 1 while held
        self._pop = 1.0        # 0 -> 1 success pop (idle at 1)
        self._breathe = 0.0    # 0..1 looping glow while active
        self._spin = 0.0       # degrees, while transitioning

        self._press_anim = None
        self._pop_anim = None
        self._breathe_timer: QTimer | None = None
        self._breathe_t = 0.0
        self._spin_timer: QTimer | None = None

        self.clicked.connect(self._on_clicked)

    def sizeHint(self):  # noqa: N802 (Qt override)
        return QSize(sp(210), sp(210))

    # -- animated properties -------------------------------------------------
    def _get_press(self) -> float:
        return self._press

    def _set_press(self, v: float) -> None:
        self._press = float(v)
        self.update()

    press = pyqtProperty(float, _get_press, _set_press)

    def _get_pop(self) -> float:
        return self._pop

    def _set_pop(self, v: float) -> None:
        self._pop = float(v)
        self.update()

    pop = pyqtProperty(float, _get_pop, _set_pop)

    def _get_breathe(self) -> float:
        return self._breathe

    def _set_breathe(self, v: float) -> None:
        self._breathe = float(v)
        self.update()

    breathe = pyqtProperty(float, _get_breathe, _set_breathe)

    # -- state API (matches old ToggleButton) -------------------------------
    def _on_clicked(self):
        if self._is_transitioning:
            return
        self._is_active = not self._is_active
        self._has_error = False
        self.update()
        self.toggled_state.emit(self._is_active)

    def set_active(self, active: bool):
        was = self._is_active
        self._is_active = active
        if active:
            self._has_error = False
            if not was:
                self._play_pop()
            self._start_breathe()
        else:
            self._stop_breathe()
        self.update()

    def set_transitioning(self, transitioning: bool):
        self._is_transitioning = transitioning
        self.setEnabled(not transitioning)
        if transitioning:
            self._start_spin()
        else:
            self._stop_spin()
        self.update()

    def set_error(self, error: bool = True):
        self._has_error = error
        if error:
            self._stop_breathe()
        self.update()

    @property
    def is_active(self) -> bool:
        return self._is_active

    # -- press feedback -------------------------------------------------------
    def mousePressEvent(self, event):  # noqa: N802 (Qt override)
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self._tween_press(1.0, 110, QEasingCurve.Type.OutCubic)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802 (Qt override)
        self._tween_press(0.0, 220, QEasingCurve.Type.OutBack)
        super().mouseReleaseEvent(event)

    def _tween_press(self, end: float, ms: int, curve) -> None:
        from PyQt6.QtCore import QPropertyAnimation
        try:
            from ..animations import motion_ok
            if not motion_ok():
                self._press = end
                self.update()
                return
        except Exception:
            pass
        try:
            from PyQt6.QtCore import QPropertyAnimation
            if self._press_anim is not None:
                try:
                    self._press_anim.stop()
                except Exception:
                    pass
            self._press_anim = QPropertyAnimation(self, b"press", self)
            self._press_anim.setDuration(ms)
            self._press_anim.setStartValue(self._press)
            self._press_anim.setEndValue(end)
            self._press_anim.setEasingCurve(curve)
            self._press_anim.start()
        except Exception:
            self._press = end
            self.update()

    def _play_pop(self) -> None:
        try:
            from ..animations import motion_ok
            if not motion_ok():
                self._pop = 1.0
                return
        except Exception:
            pass
        try:
            from PyQt6.QtCore import QPropertyAnimation
            if self._pop_anim is not None:
                try:
                    self._pop_anim.stop()
                except Exception:
                    pass
            self._pop = 0.0
            self._pop_anim = QPropertyAnimation(self, b"pop", self)
            self._pop_anim.setDuration(320)
            self._pop_anim.setStartValue(0.0)
            self._pop_anim.setEndValue(1.0)
            curve = QEasingCurve(QEasingCurve.Type.OutBack)
            curve.setAmplitude(1.6)
            self._pop_anim.setEasingCurve(curve)
            self._pop_anim.start()
        except Exception:
            self._pop = 1.0

    # -- breathing glow + spin --------------------------------------------------
    def _motion_allowed(self) -> bool:
        try:
            from ..animations import motion_ok
            return motion_ok()
        except Exception:
            return True

    def _start_breathe(self) -> None:
        if not self._motion_allowed():
            return
        if self._breathe_timer is not None:
            return
        self._breathe_timer = QTimer(self)
        self._breathe_timer.setInterval(32)
        self._breathe_t = 0.0

        def _tick():
            # ~1.6s sine loop, 0..1.
            import math
            self._breathe_t += 32.0 / 1600.0
            self._breathe = 0.5 - 0.5 * math.cos(
                self._breathe_t * 2.0 * math.pi)
            self.update()

        self._breathe_timer.timeout.connect(_tick)
        self._breathe_timer.start()

    def _stop_breathe(self) -> None:
        if self._breathe_timer is not None:
            try:
                self._breathe_timer.stop()
            except Exception:
                pass
            self._breathe_timer = None
        self._breathe = 0.0

    def _start_spin(self) -> None:
        if not self._motion_allowed():
            return
        if self._spin_timer is not None:
            return
        self._spin_timer = QTimer(self)
        self._spin_timer.setInterval(16)

        def _tick():
            self._spin = (self._spin + 7.0) % 360.0
            self.update()

        self._spin_timer.timeout.connect(_tick)
        self._spin_timer.start()

    def _stop_spin(self) -> None:
        if self._spin_timer is not None:
            try:
                self._spin_timer.stop()
            except Exception:
                pass
            self._spin_timer = None
        self._spin = 0.0

    # -- painting ------------------------------------------------------------
    def paintEvent(self, event):  # noqa: N802 (Qt override)
        s = min(self.width(), self.height())
        cx = cy = s / 2
        disc_r = s * 0.36
        ring_r = s * 0.42

        active = self._is_active
        error = self._has_error
        palette = current_theme()
        accent = QColor(palette["accent"])

        # Combined squash+pop scale around the center (paint-time only).
        scale = (1.0 - 0.07 * max(0.0, min(1.0, self._press)))
        scale *= 0.86 + 0.14 * max(0.0, min(1.0, self._pop))

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(cx, cy)
        p.scale(scale, scale)
        p.translate(-cx, -cy)

        # Outer glow (breathes while active).
        glow_alpha = 110 if active else 28
        if active and not error:
            glow_alpha = int(78 + 48 * self._breathe)
        glow = QRadialGradient(cx, cy, s * 0.5)
        if error:
            glow.setColorAt(0.0, QColor(239, 68, 68, 90))
        elif active:
            glow.setColorAt(0.0, QColor(
                accent.red(), accent.green(), accent.blue(), glow_alpha))
        else:
            glow.setColorAt(0.0, QColor(
                accent.red(), accent.green(), accent.blue(), 28))
        glow.setColorAt(1.0, QColor(
            accent.red(), accent.green(), accent.blue(), 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(int(cx - s * 0.5), int(cy - s * 0.5), int(s), int(s))

        # Ring.
        if error:
            ring_color = QColor("#f87171")
        elif active:
            ring_color = accent.lighter(125)
        else:
            ring_color = QColor(palette["muted"])
            ring_color.setAlpha(90)
        p.setPen(QPen(ring_color, 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(int(cx - ring_r), int(cy - ring_r),
                      int(ring_r * 2), int(ring_r * 2))

        # Transitioning sweep: rotating arc over the ring.
        if self._is_transitioning:
            sweep = QPen(accent.lighter(140), 3)
            sweep.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(sweep)
            # Qt arcs: 0deg = 3 o'clock, positive counter-clockwise;
            # negate spin for clockwise motion.
            p.drawArc(int(cx - ring_r), int(cy - ring_r),
                      int(ring_r * 2), int(ring_r * 2),
                      int(-self._spin * 16), 70 * 16)

        # Disc.
        disc = QRadialGradient(cx - disc_r * 0.25, cy - disc_r * 0.3, disc_r * 1.4)
        if active:
            disc.setColorAt(0.0, accent.lighter(140))
            disc.setColorAt(1.0, accent)
        else:
            card = QColor(palette["card"])
            disc.setColorAt(0.0, card.lighter(135))
            disc.setColorAt(1.0, card)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(disc)
        p.drawEllipse(int(cx - disc_r), int(cy - disc_r),
                      int(disc_r * 2), int(disc_r * 2))

        # Power glyph: 300-degree arc + vertical line.
        if active:
            glyph = QColor(palette["bg"])
        elif error:
            glyph = QColor("#f87171")
        else:
            glyph = QColor(palette["muted"]).darker(140)
        pen = QPen(glyph, disc_r * 0.085)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        arc_box = disc_r * 0.336
        # Gap at the top: start 120deg, span 300deg (Qt: 0deg = 3 o'clock).
        p.drawArc(int(cx - arc_box), int(cy - arc_box),
                  int(arc_box * 2), int(arc_box * 2),
                  120 * 16, 300 * 16)
        p.drawLine(int(cx), int(cy - disc_r * 0.336), int(cx), int(cy - disc_r * 0.014))

        # State text.
        if self._is_transitioning:
            text = "..."
        elif error and not active:
            text = "ERR"
        else:
            text = "ON" if active else "OFF"
        p.setPen(glyph)
        p.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        p.drawText(int(cx - disc_r), int(cy + disc_r * 0.55),
                   int(disc_r * 2), 24, Qt.AlignmentFlag.AlignCenter, text)
        p.end()
