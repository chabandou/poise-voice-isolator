"""
Poise Voice Isolator - Dial Button

The Start/Stop control: a 270-degree ring of ticks around a power disc.
The ring doubles as the reduction-strength control (drag, wheel, arrow
keys): lit ticks = how strongly unwanted sound is removed. Idle the ring
is the theme's secondary colour; while isolating it turns to the accent.

Evolves PowerButton and keeps its API (toggled_state / set_active /
set_transitioning / set_error / is_active), so MainWindow wiring is
unchanged. Press squash, success pop and the breathing loop come from
PowerButton; the transitioning spin becomes a highlight that travels
over the ticks. All motion respects POISE_NO_ANIM / POISE_REDUCE_MOTION.

Geometry is authored in a 300-unit square and scaled to the widget, so
the dial stays crisp at any UI scale.
"""
import math

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen

from .power_button import PowerButton
from ..fonts import heading_family
from ..scaling import sp
from ..themes import current as current_theme

# dB limits of the reduction ring (matches the old Max-attenuation slider).
ATTEN_STRONG = -80   # most reduction  -> ring full
ATTEN_GENTLE = -20   # least reduction -> ring empty

REF = 300.0          # design square
TICKS = 55           # ticks on the arc
ARC_START = 135.0    # degrees, y-down screen space (bottom-left)
ARC_SPAN = 270.0     # clockwise sweep to bottom-right
MAJOR_EVERY = 9      # longer tick every N ticks
R_OUT = 136.0
R_IN = 118.0
R_IN_MAJOR = 110.0
DISC_R = 88.0
RING_HIT_MIN = 102.0  # ring zone (drag) vs disc zone (click)
RING_HIT_MAX = 150.0
DISC_HIT = 100.0


def clamp_db(db) -> int:
    """Clamp to the dial range as an integer dB value."""
    return int(max(ATTEN_STRONG, min(ATTEN_GENTLE, round(db))))


def strength_fraction(db) -> float:
    """0.0 (gentlest, ring empty) .. 1.0 (strongest, ring full)."""
    span = ATTEN_GENTLE - ATTEN_STRONG
    return (ATTEN_GENTLE - clamp_db(db)) / span


def db_from_fraction(frac: float) -> int:
    """Inverse of strength_fraction (rounded to whole dB)."""
    frac = max(0.0, min(1.0, frac))
    return clamp_db(ATTEN_GENTLE - frac * (ATTEN_GENTLE - ATTEN_STRONG))


def angle_to_fraction(angle_deg: float, previous: float = None) -> float:
    """Map a pointer angle (degrees, y-down, 0 = 3 o'clock) to 0..1.

    The ring is open at the bottom: angles inside that gap snap to the
    nearer end. When `previous` is given and the pointer jumps across the
    gap, the value pins to the end it came from instead of wrapping.
    """
    rel = (angle_deg - ARC_START) % 360.0
    if rel > ARC_SPAN:
        rel = ARC_SPAN if rel < ARC_SPAN + (360.0 - ARC_SPAN) / 2 else 0.0
    frac = rel / ARC_SPAN
    if previous is not None and abs(frac - previous) > 0.5:
        frac = 1.0 if previous > 0.5 else 0.0
    return frac


def tick_geometry(index: int, count: int = TICKS):
    """(angle in degrees, inner radius, outer radius) of one tick."""
    angle = ARC_START + ARC_SPAN * index / (count - 1)
    inner = R_IN_MAJOR if index % MAJOR_EVERY == 0 else R_IN
    return angle, inner, R_OUT


class DialButton(PowerButton):
    """Tick-ring Start/Stop dial that also sets the reduction strength."""

    strength_changed = pyqtSignal(int)   # new dB value, user-driven only

    _dial_px = 0   # 0 -> sp(300); set by set_dial_size()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self._dial_px = sp(int(REF))
        self.setFixedSize(self._dial_px, self._dial_px)
        self._strength_db = -60
        self._dragging = False
        self._drag_frac = 0.0
        self._key_focus = False
        self._hot = False
        self._wheel_acc = 0
        self.setAccessibleName("Start isolating")
        self.setToolTip(
            "Press to start or stop. Drag the ring to set the reduction "
            "strength (applies the next time you start).")

    # -- sizing ---------------------------------------------------------------
    def sizeHint(self):  # noqa: N802 (Qt override)
        px = self._dial_px or sp(int(REF))
        return QSize(px, px)

    def set_dial_size(self, px: int) -> None:
        """Resize the (square) dial; used by the responsive modes."""
        px = max(120, int(px))
        if px == self._dial_px:
            return
        self._dial_px = px
        self.setFixedSize(px, px)
        self.updateGeometry()
        self.update()

    # -- strength API -----------------------------------------------------------
    def strength_db(self) -> int:
        return self._strength_db

    def set_strength_db(self, db) -> None:
        """Set the value programmatically (does not emit)."""
        db = clamp_db(db)
        if db != self._strength_db:
            self._strength_db = db
            self.update()

    def _user_set_strength(self, db) -> None:
        db = clamp_db(db)
        if db != self._strength_db:
            self._strength_db = db
            self.update()
            self.strength_changed.emit(db)

    # -- state overrides: keep the accessible name honest ------------------------
    def set_active(self, active: bool):
        super().set_active(active)
        self._sync_accessible()

    def _on_clicked(self):
        super()._on_clicked()
        self._sync_accessible()

    def _sync_accessible(self) -> None:
        self.setAccessibleName(
            "Stop isolating" if self._is_active else "Start isolating")

    def state_label(self) -> str:
        if self._is_transitioning:
            return "..."
        if self._has_error and not self._is_active:
            return "Retry"
        return "Stop" if self._is_active else "Start"

    # -- geometry helpers -----------------------------------------------------------
    def _ref_point(self, pos):
        k = min(self.width(), self.height()) / REF
        return ((pos.x() - self.width() / 2) / k,
                (pos.y() - self.height() / 2) / k)

    def _zone(self, pos):
        dx, dy = self._ref_point(pos)
        r = math.hypot(dx, dy)
        if r <= DISC_HIT:
            return "disc"
        if RING_HIT_MIN <= r <= RING_HIT_MAX:
            return "ring"
        return None

    def hitButton(self, pos):  # noqa: N802 (Qt override)
        """Only the centre disc clicks; the ring is the strength control."""
        return self._zone(pos) == "disc"

    # -- pointer ---------------------------------------------------------------------
    def _drag_to(self, pos) -> None:
        dx, dy = self._ref_point(pos)
        angle = math.degrees(math.atan2(dy, dx))
        frac = angle_to_fraction(angle, self._drag_frac)
        self._drag_frac = frac
        self._user_set_strength(db_from_fraction(frac))

    def _update_hover_cursor(self, pos) -> None:
        zone = self._zone(pos)
        self._hot = zone in ("ring", "disc")   # head needle lights on both
        if self._dragging:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif zone == "ring":
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        elif zone == "disc":
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()

    def mousePressEvent(self, event):  # noqa: N802 (Qt override)
        if (event.button() == Qt.MouseButton.LeftButton and self.isEnabled()
                and self._zone(event.position()) == "ring"):
            self._dragging = True
            self._drag_frac = strength_fraction(self._strength_db)
            self._drag_to(event.position())
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802 (Qt override)
        if self._dragging:
            self._drag_to(event.position())
            event.accept()
            return
        self._update_hover_cursor(event.position())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802 (Qt override)
        if self._dragging:
            self._dragging = False
            self._update_hover_cursor(event.position())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):  # noqa: N802 (Qt override)
        self._hot = False
        self.update()
        super().leaveEvent(event)

    def wheelEvent(self, event):  # noqa: N802 (Qt override)
        if not self.isEnabled():
            return super().wheelEvent(event)
        self._wheel_acc += event.angleDelta().y()
        steps = int(self._wheel_acc / 120)
        if steps:
            self._wheel_acc -= steps * 120
            unit = 5 if (event.modifiers() & Qt.KeyboardModifier.ControlModifier) else 1
            self._user_set_strength(self._strength_db - steps * unit)  # up = stronger
        event.accept()

    # -- keyboard ------------------------------------------------------------------------
    def keyPressEvent(self, event):  # noqa: N802 (Qt override)
        key = event.key()
        step = {Qt.Key.Key_Right: -1, Qt.Key.Key_Up: -1,
                Qt.Key.Key_Left: 1, Qt.Key.Key_Down: 1,
                Qt.Key.Key_PageUp: -5, Qt.Key.Key_PageDown: 5}.get(key)
        if step is not None:
            self._user_set_strength(self._strength_db + step)
            event.accept()
        elif key == Qt.Key.Key_Home:
            self._user_set_strength(ATTEN_GENTLE)
            event.accept()
        elif key == Qt.Key.Key_End:
            self._user_set_strength(ATTEN_STRONG)
            event.accept()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.click()
            event.accept()
        else:
            super().keyPressEvent(event)

    def focusInEvent(self, event):  # noqa: N802 (Qt override)
        self._key_focus = event.reason() in (
            Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason,
            Qt.FocusReason.ShortcutFocusReason)
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event):  # noqa: N802 (Qt override)
        self._key_focus = False
        super().focusOutEvent(event)
        self.update()

    # -- painting ------------------------------------------------------------------------
    @staticmethod
    def _blend(a: QColor, b: QColor, t: float) -> QColor:
        t = max(0.0, min(1.0, t))
        return QColor(
            int(a.red() + (b.red() - a.red()) * t),
            int(a.green() + (b.green() - a.green()) * t),
            int(a.blue() + (b.blue() - a.blue()) * t),
            int(a.alpha() + (b.alpha() - a.alpha()) * t))

    @staticmethod
    def _centered_text(p, text, cx, baseline, font, color) -> None:
        from PyQt6.QtGui import QFontMetricsF
        p.setFont(font)
        p.setPen(color)
        width = QFontMetricsF(font).horizontalAdvance(text)
        p.drawText(QPointF(cx - width / 2, baseline), text)

    def paintEvent(self, event):  # noqa: N802 (Qt override)
        w, h = self.width(), self.height()
        k = min(w, h) / REF
        palette = current_theme()
        active, error = self._is_active, self._has_error
        accent = QColor(palette["accent"])
        text = QColor(palette["text"])
        muted = QColor(palette["muted"])
        if error and not active:
            live = QColor(palette["error"])
        elif active:
            live = accent
        else:
            live = QColor(palette["secondary"])
        unlit = QColor(muted)
        unlit.setAlpha(80)

        press = max(0.0, min(1.0, self._press))
        pop = max(0.0, min(1.0, self._pop))
        scale = (1.0 - 0.07 * press) * (0.86 + 0.14 * pop)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.translate(w / 2, h / 2)
        p.scale(k * scale, k * scale)
        p.translate(-REF / 2, -REF / 2)
        c = REF / 2

        # Tick ring: lit ticks show the reduction strength.
        lit = int(round(TICKS * strength_fraction(self._strength_db)))
        head_hot = self._dragging or self._hot
        for i in range(TICKS):
            angle, r_in, r_out = tick_geometry(i)
            width = 4.0
            if i < lit:
                col = QColor(live)
                if active and not error:
                    col.setAlpha(int(205 + 50 * self._breathe))
            else:
                col = QColor(unlit)
            if i == lit - 1 and lit > 0 and (active or head_hot):
                col, width = QColor(text), 5.0
            if self._is_transitioning:
                d = abs(((angle - self._spin) + 180.0) % 360.0 - 180.0)
                if d < 28.0:
                    col = self._blend(col, QColor(palette["accent_light"]),
                                      1.0 - d / 28.0)
                    width = 5.0
            pen = QPen(col, width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            rad = math.radians(angle)
            cs, sn = math.cos(rad), math.sin(rad)
            p.drawLine(QPointF(c + r_in * cs, c + r_in * sn),
                       QPointF(c + r_out * cs, c + r_out * sn))

        # Disc.
        p.setPen(QPen(QColor(palette["groove"]), 2.0))
        p.setBrush(QColor(palette["pill"]))
        p.drawEllipse(QPointF(c, c), DISC_R, DISC_R)
        if self._key_focus and self.hasFocus():
            focus = QColor(palette["accent_light"])
            p.setPen(QPen(focus, 2.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(c, c), DISC_R + 6.0, DISC_R + 6.0)

        # Power glyph + state label, centred together in the disc.
        glyph = QPen(live, 5.5)
        glyph.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(glyph)
        p.setBrush(Qt.BrushStyle.NoBrush)
        gy, gr = 137.75, 20.0
        p.drawLine(QPointF(c, gy - 26.0), QPointF(c, gy - 6.0))
        p.drawArc(QRectF(c - gr, gy - gr, 2 * gr, 2 * gr), 130 * 16, 280 * 16)

        head = QFont(heading_family())
        head.setPixelSize(21)
        head.setWeight(QFont.Weight.Bold)
        label_color = QColor(palette["error"]) if (error and not active) else text
        self._centered_text(p, self.state_label(), c, 191.0, head, label_color)

        # Reduction readout below the disc, inside the ring's open end.
        big = QFont(heading_family())
        big.setPixelSize(30)
        big.setWeight(QFont.Weight.Bold)
        self._centered_text(p, f"{self._strength_db} dB", c, 266.0, big, text)
        small = QFont(self.font())
        small.setPixelSize(12)
        self._centered_text(p, "reduction strength", c, 284.0, small, muted)
        self._centered_text(p, "gentle", 52.0, 268.0, small, muted)
        self._centered_text(p, "strong", 248.0, 268.0, small, muted)
        p.end()
