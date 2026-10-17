"""
Poise Voice Isolator - Rolling Number

A small readout ("-40 dB") whose digits roll like an odometer when the
value changes, the same motion as the dial's reduction-strength readout
on Home: each digit column springs to its new digit (OutBack, 400 ms)
and the number gives a little bump whenever it lands on a multiple of
ten. At this small size each digit rolls through a window just its own
height and fades as it leaves, so neighbours never peek in. Right-
aligned in its box; text() returns what it reads at rest.
Reduced motion shows each value straight away.
"""
import math

from PyQt6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt
from PyQt6.QtCore import QVariantAnimation
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ..animations import Blend, motion_ok, rise_fall
from ..scaling import sp

ROLL_MS = 400            # the dial's digit roll
ROLL_OVERSHOOT = 1.2     # the dial's spring, for a one-digit roll
#: OutBack overshoots in proportion to the travel, so a long roll (0 -> 7)
#: would spring a third of a digit past and half-hide it. The spring is
#: softened for longer rolls so it always settles from about this far
#: past (in digits).
ROLL_SETTLE = 0.08
BUMP_MS = 340            # the dial's ten-step bump
BUMP_PEAK = 0.4
BUMP_SCALE = 0.08


def _spring(travel: float = 1.0) -> QEasingCurve:
    """The roll's spring for a roll of `travel` digits."""
    curve = QEasingCurve(QEasingCurve.Type.OutBack)
    # OutBack's peak overshoot is ~0.065 of the travel at 1.2; keep the
    # absolute overshoot near ROLL_SETTLE however far the digit rolls.
    travel = max(1.0, abs(travel))
    curve.setOvershoot(min(ROLL_OVERSHOOT,
                           ROLL_OVERSHOOT * ROLL_SETTLE / (0.065 * travel)))
    return curve


class RollingNumber(QWidget):
    """Signed integer + unit with rolling digits."""

    def __init__(self, value: int = 0, suffix: str = "", digits: int = 2,
                 px: int = 15, weight=QFont.Weight.DemiBold,
                 colour_key: str = "accent", parent=None):
        super().__init__(parent)
        self._value = int(value)
        self._suffix = suffix
        self._digits = max(1, int(digits))
        self._px = px
        self._weight = weight
        self._colour_key = colour_key
        self._columns = [
            Blend(self, self.update, ROLL_MS, _spring(), d)
            for d in self._digit_values(self._value)]
        self._bump = QVariantAnimation(self)
        self._bump.setDuration(BUMP_MS)
        self._bump.setStartValue(0.0)
        self._bump.setEndValue(1.0)
        self._bump.valueChanged.connect(lambda _v: self.update())
        self._bump.finished.connect(self.update)
        self.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Fixed)
        self._sync_accessible()

    # -- value -------------------------------------------------------------------
    def value(self) -> int:
        return self._value

    def text(self) -> str:
        """What the readout says at rest ("-33 dB")."""
        return f"{self._value}{self._suffix}"

    def set_value(self, value: int, animated: bool | None = None) -> None:
        value = int(value)
        if value == self._value:
            return
        self._value = value
        if animated is None:
            animated = self.isVisible()
        animated = animated and motion_ok()
        for blend, digit in zip(self._columns, self._digit_values(value)):
            blend.set_target(digit, animated,
                             easing=_spring(digit - blend.value))
        if animated and value % 10 == 0:
            self._bump.stop()
            self._bump.start()
        self._sync_accessible()
        self.update()

    def _digit_values(self, value: int):
        magnitude = abs(int(value))
        return [(magnitude // 10 ** k) % 10
                for k in range(self._digits - 1, -1, -1)]

    def _sync_accessible(self) -> None:
        self.setAccessibleName(self.text())

    # -- sizing --------------------------------------------------------------------
    def _font(self) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(sp(self._px))
        font.setWeight(self._weight)
        return font

    def sizeHint(self):  # noqa: N802 (Qt override)
        metrics = QFontMetricsF(self._font())
        width = self._layout(metrics)[0]
        return QSize(int(math.ceil(width)) + sp(2),
                     int(math.ceil(metrics.height())) + sp(4))

    def _layout(self, metrics):
        digit_w = max(metrics.horizontalAdvance(str(d)) for d in range(10))
        minus_w = metrics.horizontalAdvance("-")
        suffix_w = metrics.horizontalAdvance(self._suffix)
        total = minus_w + self._digits * digit_w + suffix_w
        return total, digit_w, minus_w

    # -- painting ------------------------------------------------------------------
    def paintEvent(self, event):  # noqa: N802 (Qt override)
        from ..themes import current as current_theme
        font = self._font()
        metrics = QFontMetricsF(font)
        total, digit_w, minus_w = self._layout(metrics)
        cap = metrics.capHeight()
        pad = float(sp(3))             # headroom for the settle
        step = cap + float(sp(7))      # next digit sits just out of view
        baseline = (self.height() + metrics.ascent() - metrics.descent()) / 2
        right = float(self.width())
        x = right - total

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        bump = 0.0
        if self._bump.state() == QVariantAnimation.State.Running:
            bump = rise_fall(float(self._bump.currentValue() or 0.0),
                             BUMP_PEAK)
        if bump > 0:
            cx, cy = x + total / 2, baseline - metrics.ascent() / 2
            p.translate(cx, cy)
            p.scale(1 + BUMP_SCALE * bump, 1 + BUMP_SCALE * bump)
            p.translate(-cx, -cy)
        p.setFont(font)
        p.setPen(QColor(current_theme()[self._colour_key]))

        if self._value < 0:
            p.drawText(QPointF(x, baseline), "-")
        x += minus_w
        top = baseline - cap - pad
        for i, blend in enumerate(self._columns):
            column = blend.value
            p.save()
            p.setClipRect(QRectF(x - pad, top, digit_w + 2 * pad,
                                 cap + 2 * pad))
            first = max(0, int(math.floor(column)) - 1)
            for d in range(first, min(10, first + 3)):
                # Leading zeros stay hidden ("-5", not "-05").
                if d == 0 and i < self._digits - 1 and all(
                        b.target == 0 for b in self._columns[:i + 1]):
                    continue
                # Full strength near its slot (the settle included), then
                # fading as it rolls away.
                fade = max(0.0, min(1.0,
                                    1.0 - (abs(d - column) - 0.15) * 1.4))
                if fade <= 0.0:
                    continue
                p.setOpacity(fade)
                width = metrics.horizontalAdvance(str(d))
                p.drawText(QPointF(x + (digit_w - width) / 2,
                                   baseline + step * (d - column)), str(d))
            p.restore()
            x += digit_w
        if self._suffix:
            p.drawText(QPointF(x, baseline), self._suffix)
        p.end()
