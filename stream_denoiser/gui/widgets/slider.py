"""
Poise Voice Isolator - Painted Slider

A QSlider (value, range, signals and arrow keys are stock) painted and
driven by hand so its handle can move like the rest of the app:

- the handle glides to every new value instead of jumping: a click on
  the track, an arrow key or a reset springs there (a soft OutBack); a
  wheel notch slides there; a drag follows the pointer smoothly and
  settles onto the whole-number value on release;
- hovering the handle lifts it toward the text colour and grows it a
  little; holding it grows it more and lights a soft accent halo
  around it (both eased);
- the wheel nudges the value (one step per notch, a page with Ctrl), but
  only once the pointer has actually moved over the slider: a page
  scroll that slides the slider under a resting pointer keeps scrolling
  the page instead of grabbing the value.

All motion respects reduced motion (POISE_NO_ANIM / POISE_REDUCE_MOTION):
the handle then sits at the value and hover/press states snap. The app
stylesheet's QSlider rules still describe the look (and stock sliders);
the colours here are the same theme keys.
"""
from PyQt6.QtWidgets import QSlider, QSizePolicy
from PyQt6.QtCore import (
    QEasingCurve, QEvent, QPointF, QRectF, QSize, Qt, QVariantAnimation,
)
from PyQt6.QtGui import QColor, QPainter

from ..animations import Blend, motion_ok
from ..scaling import sp

HANDLE = 14              # handle side (sp px)
GROOVE = 4               # track thickness (sp px)
HOVER_GROW = 0.12        # handle growth on hover (fraction)
PRESS_GROW = 0.14        # extra growth while held
HALO = 1.75              # halo side while held, in handle sides
HALO_ALPHA = 0.20        # halo strength while held
HOVER_HALO_ALPHA = 0.08  # a faint halo already on hover
HOVER_TOWARD_TEXT = 0.5  # handle colour on hover: this far to the text

SPRING_MS = 360          # click on the track / reset / programmatic
KEY_MS = 260             # arrow keys
WHEEL_MS = 180           # a wheel notch
CHASE_MS = 50            # following a drag (just takes the edge off)
SETTLE_MS = 200          # drag released: onto the whole-number value
SPRING_OVERSHOOT = 1.1
WHEEL_INTENT_PX = 2      # pointer travel over the slider that arms the wheel


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    """Linear blend between two colors (t clamped to [0, 1])."""
    t = max(0.0, min(1.0, t))
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
    )


def _spring() -> QEasingCurve:
    curve = QEasingCurve(QEasingCurve.Type.OutBack)
    curve.setOvershoot(SPRING_OVERSHOOT)
    return curve


class HoverSlider(QSlider):
    """Horizontal slider whose handle glides, grows and glows."""

    DURATION_MS = 150        # hover ease (kept name: the old crossfade's)
    HOVER_TOWARD_TEXT = HOVER_TOWARD_TEXT

    def __init__(self, orientation=Qt.Orientation.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.setMouseTracking(True)
        # Tab / click focus for the arrow keys; the wheel never gives it.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)

        self._shown = float(self.value())     # where the handle is drawn
        self._glide = QVariantAnimation(self)
        self._glide.valueChanged.connect(self._set_shown)
        self._hover = Blend(self, self.update, self.DURATION_MS)
        self._press = Blend(self, self.update, 180)

        self._dragging = False
        self._grab = 0.0          # pointer -> handle centre offset (value)
        self._press_x = None      # chase the drag once it leaves here
        self._wheel_acc = 0
        self._wheel_armed = False
        self._enter_pos = None
        self._next_motion = None  # (duration, curve) for the next glide
        self.valueChanged.connect(self._on_value)

    def sizeHint(self):  # noqa: N802 (Qt override)
        return QSize(sp(200), sp(30))

    def minimumSizeHint(self):  # noqa: N802 (Qt override)
        return QSize(sp(60), sp(30))

    # -- geometry ---------------------------------------------------------------
    def _metrics(self):
        """(handle side, halo side, left x, right x) of the handle centre."""
        handle = float(sp(HANDLE))
        halo = handle * HALO
        inset = halo / 2.0
        return handle, halo, inset, max(inset + 1.0, self.width() - inset)

    def _x_for(self, value: float) -> float:
        _, _, left, right = self._metrics()
        span = self.maximum() - self.minimum()
        frac = 0.0 if span <= 0 else (value - self.minimum()) / span
        return left + (right - left) * max(0.0, min(1.0, frac))

    def _value_at(self, x: float) -> float:
        _, _, left, right = self._metrics()
        frac = (x - left) / (right - left)
        frac = max(0.0, min(1.0, frac))
        return self.minimum() + frac * (self.maximum() - self.minimum())

    def _on_handle(self, x: float, y: float) -> bool:
        handle, _, _, _ = self._metrics()
        reach = handle * 0.5 * (1 + HOVER_GROW) + sp(3)
        return (abs(x - self._x_for(self._shown)) <= reach
                and abs(y - self.height() / 2.0) <= reach + sp(4))

    # -- the handle's glide -----------------------------------------------------
    @property
    def shown_value(self) -> float:
        """Where the handle is drawn (eases toward value())."""
        return self._shown

    def _set_shown(self, v) -> None:
        self._shown = float(v)
        if self.underMouse() and not self._dragging:
            self._sync_states()      # it may arrive under a still pointer
        self.update()

    def _glide_to(self, target: float, ms: int, curve) -> None:
        target = float(target)
        if (not motion_ok() or not self.isVisible()
                or abs(target - self._shown) < 1e-3):
            self._glide.stop()
            self._set_shown(target)
            return
        start = self._shown
        self._glide.stop()
        self._glide.blockSignals(True)       # see Blend.set_target
        self._glide.setEasingCurve(curve)
        self._glide.setDuration(ms)
        self._glide.setStartValue(start)
        self._glide.setEndValue(target)
        self._glide.blockSignals(False)
        self._glide.start()

    def _on_value(self, value: int) -> None:
        if self._dragging:
            return                           # the drag moves the handle
        ms, curve = self._next_motion or (SPRING_MS, _spring())
        self._next_motion = None
        self._glide_to(value, ms, curve)

    # -- pointer ---------------------------------------------------------------------
    def mousePressEvent(self, event):  # noqa: N802 (Qt override)
        if not self.isEnabled():
            event.ignore()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        pos = event.position()
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        if self._on_handle(pos.x(), pos.y()):
            # Grabbed: the handle stays under the pointer where it was held.
            self._grab = self._shown - self._value_at(pos.x())
        else:
            # Track click: spring there, then keep following the drag.
            self._grab = 0.0
            self._next_motion = (SPRING_MS, _spring())
            self.setValue(round(self._value_at(pos.x())))
        self._press_x = pos.x()
        self._dragging = True
        self.setSliderDown(True)
        self._sync_states()
        event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802 (Qt override)
        pos = event.position()
        if self._enter_pos is not None and not self._wheel_armed:
            moved = pos - self._enter_pos
            if (abs(moved.x()) + abs(moved.y())) >= WHEEL_INTENT_PX:
                self._wheel_armed = True
        if self._dragging:
            want = self._value_at(pos.x()) + self._grab
            want = max(self.minimum(), min(self.maximum(), want))
            self.setValue(round(want))
            # A track click's spring plays out unless the drag really moves.
            if (self._press_x is None
                    or abs(pos.x() - self._press_x) >= sp(3)):
                self._press_x = None
                self._glide_to(want, CHASE_MS,
                               QEasingCurve(QEasingCurve.Type.OutCubic))
            event.accept()
        self._sync_states(pos)
        if not self._dragging:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802 (Qt override)
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self.setSliderDown(False)
            if self._press_x is None:
                # Dragged: settle onto the whole-number value. (A plain
                # click leaves its spring to play out.)
                self._glide_to(self.value(), SETTLE_MS,
                               QEasingCurve(QEasingCurve.Type.OutCubic))
            self._press_x = None
            self._sync_states(event.position())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def enterEvent(self, event):  # noqa: N802 (Qt override)
        self._enter_pos = QPointF(event.position())
        self._wheel_armed = False
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802 (Qt override)
        self._enter_pos = None
        self._wheel_armed = False
        self._wheel_acc = 0
        self._sync_states(None)
        super().leaveEvent(event)

    def wheelEvent(self, event):  # noqa: N802 (Qt override)
        """One step per notch (a page with Ctrl) once the pointer has
        moved over the slider; otherwise the page scrolls as usual."""
        if not self.isEnabled() or not self._wheel_armed:
            event.ignore()
            return
        delta = event.angleDelta().y() or event.angleDelta().x()
        self._wheel_acc += delta
        steps = int(self._wheel_acc / 120)
        if steps:
            self._wheel_acc -= steps * 120
            ctrl = event.modifiers() & Qt.KeyboardModifier.ControlModifier
            unit = self.pageStep() if ctrl else self.singleStep()
            self._next_motion = (WHEEL_MS,
                                 QEasingCurve(QEasingCurve.Type.OutCubic))
            self.setValue(self.value() + steps * unit)
            self._next_motion = None
        event.accept()

    def keyPressEvent(self, event):  # noqa: N802 (Qt override)
        self._next_motion = (KEY_MS, _spring())
        super().keyPressEvent(event)
        self._next_motion = None

    def changeEvent(self, event):  # noqa: N802 (Qt override)
        super().changeEvent(event)
        if event.type() == QEvent.Type.EnabledChange:
            if not self.isEnabled():
                self._dragging = False
                self._wheel_armed = False
            self._sync_states()
            self.update()

    # -- hover / press states -------------------------------------------------------
    def _sync_states(self, pos=None) -> None:
        enabled = self.isEnabled()
        if pos is None:
            pos = self.mapFromGlobal(self.cursor().pos()).toPointF() \
                if self.underMouse() else None
        over = (pos is not None and self.rect().contains(pos.toPoint())
                and self._on_handle(pos.x(), pos.y()))
        self._hover.set_target(1.0 if enabled and (over or self._dragging)
                               else 0.0)
        self._press.set_target(1.0 if enabled and self._dragging else 0.0)

    # -- painting -----------------------------------------------------------------------
    def paintEvent(self, event):  # noqa: N802 (Qt override)
        from ..themes import current as current_theme
        palette = current_theme()
        enabled = self.isEnabled()
        handle, halo, left, right = self._metrics()
        cy = self.height() / 2.0
        groove_h = float(sp(GROOVE))
        x = self._x_for(self._shown)
        hover, press = self._hover.value, self._press.value

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)

        # Track, then the filled part up to the handle.
        start = left - handle / 2.0
        end = right + handle / 2.0
        radius = groove_h / 2.0
        p.setBrush(QColor(palette["groove"]))
        p.drawRoundedRect(QRectF(start, cy - radius, end - start, groove_h),
                          radius, radius)
        fill = QColor(palette["accent"] if enabled else palette["groove"])
        if x > start:
            p.setBrush(fill)
            p.drawRoundedRect(QRectF(start, cy - radius, x - start,
                                     groove_h), radius, radius)

        if enabled and (hover > 0.01 or press > 0.01):
            glow = QColor(palette["accent"])
            glow.setAlphaF(min(1.0, HOVER_HALO_ALPHA * hover
                               + (HALO_ALPHA - HOVER_HALO_ALPHA) * press))
            side = handle * (1.0 + (HALO - 1.0) * (0.55 * hover
                                                    + 0.45 * press))
            p.setBrush(glow)
            r = side * 4.0 / 14.0 + side * 0.12
            p.drawRoundedRect(QRectF(x - side / 2, cy - side / 2, side, side),
                              r, r)

        if enabled:
            colour = _mix(QColor(palette["secondary"]),
                          QColor(palette["text"]),
                          hover * HOVER_TOWARD_TEXT)
        else:
            colour = QColor("#3f3f46")
        side = handle * (1.0 + HOVER_GROW * hover + PRESS_GROW * press)
        r = side * 4.0 / 14.0
        p.setBrush(colour)
        p.drawRoundedRect(QRectF(x - side / 2, cy - side / 2, side, side),
                          r, r)
        p.end()
