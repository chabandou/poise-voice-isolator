"""
Poise Voice Isolator - Dial Button

The Start/Stop control: a 270-degree ring of ticks around a power disc.
The ring doubles as the reduction-strength control (drag, wheel, arrow
keys): lit ticks = how strongly unwanted sound is removed. Idle the ring
is the theme's secondary colour; while isolating it turns to the accent.

Evolves PowerButton and keeps its API (toggled_state / set_active /
set_transitioning / set_error / is_active), so MainWindow wiring is
unchanged. The press squash comes from PowerButton; everything else runs
on the dial's own clock. All motion respects POISE_NO_ANIM /
POISE_REDUCE_MOTION (the dial then shows each state's resting look).

Motion, phase by phase:
- hover: ticks near the pointer lift outward and the head needle fades
  in; over the disc its rim warms and the power stem lifts;
- drag: the needle glides tick to tick and plucks (harder every 10 dB,
  when the readout bumps too); the readout's digits roll like an
  odometer; past either end the ring stretches up to OVERSHOOT_MAX
  degrees and springs back on release, which snaps to the nearest
  SNAP_DB step when within SNAP_WITHIN dB of it;
- starting: lit ticks dim and a comet laps the ring once a second; the
  label's three dots light up in step with it;
- live: ticks ignite one after another; when the sweep closes the needle
  flashes, the disc pops, a ripple leaves it and `ignited` fires (the
  lattice pings follow it, see PatternCard). A slow brightness crest
  then flows over the lit ticks, and the disc charges up (glow and rim)
  in the second before each later ping;
- stopping: the accent drains back from the head; the dots settle; a
  charge glow caught mid-way fades out (CHARGE_DROP_MS) rather than
  cutting off, and no new charge starts;
- error: lit ticks flash white then settle red and the disc shakes.

Geometry is authored in a 300-unit square and scaled to the widget, so
the dial stays crisp at any UI scale.
"""
import math
import time

from PyQt6.QtCore import (
    QEasingCurve, QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor, QFont, QFontMetricsF, QPainter, QPen, QRadialGradient,
)

from .pattern_card import PING_PERIOD_MS
from .power_button import PowerButton
from ..animations import (
    Blend, mix_rgba, motion_ok,
    ease_back as _back, ease_in as _ease_in, ease_in_out as _ease_in_out,
    ease_out as _ease_out, rise_fall as _rise_fall,
)
from ..fonts import heading_family
from ..scaling import sp
from ..themes import current as current_theme

# dB limits of the reduction ring. The engines mix f = 10**(dB/20) of the
# original signal back in, so past about -50 dB the leftover noise is
# below the model's own residual and further steps are inaudible; -10 dB
# keeps roughly a third of the original. The whole sweep is audible.
ATTEN_STRONG = -50   # most reduction  -> ring full
ATTEN_GENTLE = -10   # least reduction -> ring empty
ATTEN_DEFAULT = ATTEN_STRONG   # out of the box: full reduction
WHEEL_STEP = 2          # dB per wheel notch
WHEEL_STEP_COARSE = 10  # with Ctrl held
SNAP_DB = 5             # a released drag snaps to these steps...
SNAP_WITHIN = 1         # ...when this close to one

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

# -- motion (ms unless noted) ---------------------------------------------------
SWEEP_DELAY_MS = 300      # first show: the ring sweeps on from the gentle end
SWEEP_MS = 900
SWELL_PX = 3.4            # hover lift of the ticks nearest the pointer
SWELL_DEG = 13.0          # ...and how far it spreads
OVERSHOOT_MAX = 4.0       # degrees the ring stretches past an end
COMET_MS = 990            # starting: one lap of the comet
COMET_STEP = 18           # ...the delay between neighbouring ticks
DOT_STEP = 330            # the label's dots, a third of a lap apart
IGNITE_STEP = 14          # live: between ticks igniting
IGNITE_MS = 520           # one tick's ignition
IGNITE_TAIL = 100         # the sweep "closes" this long after the last tick
FLOW_MS = 3190            # live: the brightness crest's lap
FLOW_STEP = 58
NEEDLE_IN_MS = 460
POP_MS = 480
RIPPLE_MS = 1050
CHARGE_LEAD_MS = 1144     # the disc charges this long before each later ping
CHARGE_FADE_MS = 624
CHARGE_DROP_MS = 420      # a charge caught by Stop fades out (cf. the ring)
DRAIN_STEP = 9            # stopping: between ticks draining back
DRAIN_MS = 320
DOTS_OUT_MS = 520
GLYPH_MS = 420
ERROR_FLASH_MS = 640
SHAKE_MS = 480
SHAKE = (0, -2, 4, -7, 7, -7, 7, -7, 4, -2, 0)   # design px, evenly spaced
PLUCK_MS = 230
PLUCK_BIG_MS = 420
BUMP_MS = 340
FRAME_MS = 16             # transitions
LOOP_FRAME_MS = 33        # steady loops (the live crest and charge)

LABELS = ("Start", "...", "Stop", "Retry")   # "..." is drawn as three dots
LABEL_OF_PHASE = {"idle": 0, "starting": 1, "stopping": 1, "live": 2,
                  "error": 3}


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


def lit_count(db) -> int:
    """How many ticks are lit at a strength."""
    return int(round(TICKS * strength_fraction(db)))


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


def overshoot_degrees(angle_deg: float, frac: float) -> float:
    """How far the ring stretches (signed degrees) for a pointer at
    `angle_deg` while the value sits at `frac`: 0 inside the arc, easing
    toward OVERSHOOT_MAX past the end the value is pinned to."""
    rel = (angle_deg - ARC_START) % 360.0
    if frac >= 1.0:
        past = rel - ARC_SPAN if rel >= ARC_SPAN else 45.0
    elif frac <= 0.0:
        past = rel - 360.0 if rel > ARC_SPAN else (-45.0 if rel > 0 else 0.0)
    else:
        return 0.0
    past = max(-45.0, min(45.0, past))
    return math.copysign(
        OVERSHOOT_MAX * (1.0 - math.exp(-abs(past) / 16.0)), past)


def tick_geometry(index: int, count: int = TICKS):
    """(angle in degrees, inner radius, outer radius) of one tick."""
    angle = ARC_START + ARC_SPAN * index / (count - 1)
    inner = R_IN_MAJOR if index % MAJOR_EVERY == 0 else R_IN
    return angle, inner, R_OUT


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def _spring_curve(overshoot: float) -> QEasingCurve:
    curve = QEasingCurve(QEasingCurve.Type.OutBack)
    curve.setOvershoot(overshoot)
    return curve


class DialButton(PowerButton):
    """Tick-ring Start/Stop dial that also sets the reduction strength."""

    strength_changed = pyqtSignal(int)   # new dB value, user-driven only
    ignited = pyqtSignal()               # the live sweep closed

    _dial_px = 0   # 0 -> sp(300); set by set_dial_size()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self._dial_px = sp(int(REF))
        self.setFixedSize(self._dial_px, self._dial_px)
        self._strength_db = ATTEN_DEFAULT
        self._dragging = False
        self._drag_frac = 0.0
        self._drag_dir = 0                # -1 gentler, +1 stronger
        self._key_focus = False
        self._hot = False
        self._hot_blend = Blend(self, self.update, 140)  # head needle glow
        self._wheel_acc = 0

        # One clock drives every timed effect; the phase says which.
        self._phase = "idle"
        self._phase_at = time.monotonic()
        self._ignite_lit = 0              # lit ticks when the sweep began
        self._ignited = False
        self._drain_at = None             # stopping began (outlasts it)
        self._charge_from = 0.0           # charge glow when live ended
        self._charge_drop_at = None
        self._sweep_at = None             # first show: the ring sweeps on
        self._swept = False
        self._pluck_at = None
        self._pluck_big = False
        self._bump_at = None
        self._clock = QTimer(self)
        self._clock.setInterval(FRAME_MS)
        self._clock.timeout.connect(self._tick)

        # Eased states.
        self._swell = Blend(self, self.update, 220)
        self._swell_angle = 0.0
        self._disc_hot = Blend(self, self.update, 220)
        self._gentle_hot = Blend(self, self.update, 200)
        self._strong_hot = Blend(self, self.update, 200)
        self._label = Blend(self, self.update, 400, _spring_curve(1.3))
        tens, ones = divmod(-self._strength_db, 10)
        self._tens = Blend(self, self.update, 400, _spring_curve(1.2), tens)
        self._ones = Blend(self, self.update, 400, _spring_curve(1.2), ones)
        self._over = 0.0                  # ring stretch, degrees
        self._over_anim = QVariantAnimation(self)
        self._over_anim.setDuration(560)
        self._over_anim.setEasingCurve(_spring_curve(2.2))
        self._over_anim.valueChanged.connect(self._set_over)

        self.setAccessibleName("Start isolating")
        self.setToolTip(
            "Press to start or stop. Drag the ring to set the reduction "
            "strength; it applies live.")

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
            self._roll_digits()
            self.update()

    def _user_set_strength(self, db) -> None:
        db = clamp_db(db)
        if db == self._strength_db:
            return
        old = self._strength_db
        self._strength_db = db
        if self._dragging:
            now = time.monotonic()
            if lit_count(db) != lit_count(old):
                self._pluck_at = now
                self._pluck_big = db % 10 == 0
            if db % 10 == 0:
                self._bump_at = now
            self._drag_dir = 1 if db < old else -1
            self._sync_ends()
            self._run_clock()
        self._roll_digits()
        self.update()
        self.strength_changed.emit(db)

    def _roll_digits(self) -> None:
        tens, ones = divmod(-self._strength_db, 10)
        animated = self.isVisible()
        self._tens.set_target(tens, animated)
        self._ones.set_target(ones, animated)

    # -- state overrides: keep the accessible name and phase honest ------------
    def set_active(self, active: bool):
        super().set_active(active)
        self._sync_accessible()
        self._sync_phase()

    def set_transitioning(self, transitioning: bool):
        super().set_transitioning(transitioning)
        self._sync_phase()

    def set_error(self, error: bool = True):
        super().set_error(error)
        self._sync_phase()

    def _on_clicked(self):
        super()._on_clicked()
        self._sync_accessible()
        self._sync_phase()

    def _sync_accessible(self) -> None:
        self.setAccessibleName(
            "Stop isolating" if self._is_active else "Start isolating")

    def state_label(self) -> str:
        if self._is_transitioning:
            return "..."
        if self._has_error and not self._is_active:
            return "Retry"
        return "Stop" if self._is_active else "Start"

    # PowerButton's own loops are replaced by the phase clock, and its
    # success pop by the one that lands when the live sweep closes.
    def _start_breathe(self) -> None:
        self._run_clock()

    def _stop_breathe(self) -> None:
        pass

    def _start_spin(self) -> None:
        self._run_clock()

    def _stop_spin(self) -> None:
        pass

    def _play_pop(self) -> None:
        pass

    # -- phases ---------------------------------------------------------------------
    def _phase_now(self) -> str:
        if self._is_transitioning:
            return "starting" if self._is_active else "stopping"
        if self._has_error:
            return "error"
        return "live" if self._is_active else "idle"

    def _sync_phase(self) -> None:
        phase = self._phase_now()
        if phase == self._phase:
            return
        if self._phase == "live":
            # Leaving live mid-charge: let that glow fade, not cut off.
            self._charge_from = self._charge(self._ms())
            self._charge_drop_at = time.monotonic()
        elif phase == "live":
            self._charge_from, self._charge_drop_at = 0.0, None
        self._phase = phase
        self._phase_at = time.monotonic()
        if phase == "stopping":
            self._drain_at = self._phase_at
        elif phase != "idle":
            self._drain_at = None
        if phase == "live":
            self._ignite_lit = lit_count(self._strength_db)
            self._ignited = False
            if not motion_ok():
                self._ignite()
        self._label.set_target(LABEL_OF_PHASE[phase], self.isVisible())
        self._run_clock()
        self.update()

    def phase(self) -> str:
        """idle | starting | live | stopping | error"""
        return self._phase

    def _ms(self) -> float:
        """Milliseconds into the phase (settled when motion is reduced)."""
        if not motion_ok():
            return 1e9
        return (time.monotonic() - self._phase_at) * 1000.0

    @staticmethod
    def _since(stamp) -> float:
        """Milliseconds since a monotonic stamp (None: long ago)."""
        if stamp is None or not motion_ok():
            return 1e9
        return (time.monotonic() - stamp) * 1000.0

    def _ignite_end(self) -> float:
        """When the live sweep closes (ms into the live phase)."""
        return self._ignite_lit * IGNITE_STEP + IGNITE_TAIL

    def _ignite(self) -> None:
        if not self._ignited:
            self._ignited = True
            self.ignited.emit()

    # -- the clock ------------------------------------------------------------------
    def _run_clock(self) -> None:
        if motion_ok() and not self._clock.isActive() and self._animating():
            self._clock.setInterval(FRAME_MS)
            self._clock.start()

    def _animating(self) -> bool:
        if self._phase in ("starting", "live", "stopping"):
            return True
        if self._since(self._drain_at) < (TICKS - 1) * DRAIN_STEP + DRAIN_MS:
            return True
        if self._phase == "error" and self._ms() < ERROR_FLASH_MS:
            return True
        if (self._charge_from > 0.01
                and self._since(self._charge_drop_at) < CHARGE_DROP_MS):
            return True
        return (self._since(self._pluck_at) < PLUCK_BIG_MS
                or self._since(self._bump_at) < BUMP_MS
                or self._sweeping())

    def _sweeping(self) -> bool:
        return (self._sweep_at is not None
                and self._since(self._sweep_at) < SWEEP_MS)

    def _tick(self) -> None:
        if (self._phase == "live" and not self._ignited
                and self._ms() >= self._ignite_end()):
            self._ignite()
        if not self._animating():
            self._clock.stop()
        else:
            # Once the live sweep has settled only slow loops are left.
            settled = (self._phase == "live"
                       and self._ms() > self._ignite_end() + RIPPLE_MS
                       and self._since(self._pluck_at) >= PLUCK_BIG_MS
                       and self._since(self._bump_at) >= BUMP_MS)
            interval = LOOP_FRAME_MS if settled else FRAME_MS
            if self._clock.interval() != interval:
                self._clock.setInterval(interval)
        if self.isVisible():
            self.update()

    def showEvent(self, event):  # noqa: N802 (Qt override)
        super().showEvent(event)
        if not self._swept:
            self._swept = True
            if motion_ok():
                self._sweep_at = time.monotonic() + SWEEP_DELAY_MS / 1000.0
        self._run_clock()

    def hideEvent(self, event):  # noqa: N802 (Qt override)
        self._clock.stop()   # nothing to see (e.g. hidden to the tray)
        super().hideEvent(event)

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
        frac = angle_to_fraction(angle, self._drag_frac)  # None: no pinning
        self._drag_frac = frac
        self._over_anim.stop()
        self._set_over(overshoot_degrees(angle, frac))
        self._user_set_strength(db_from_fraction(frac))

    def _set_over(self, value) -> None:
        self._over = float(value)
        self.update()

    def _spring_back(self) -> None:
        """Let a stretched ring go."""
        if abs(self._over) < 0.01 or not motion_ok():
            self._set_over(0.0)
            return
        self._over_anim.stop()
        self._over_anim.setStartValue(self._over)
        self._over_anim.setEndValue(0.0)
        self._over_anim.start()

    def _update_hover_cursor(self, pos) -> None:
        zone = self._zone(pos)
        self._hot = zone in ("ring", "disc")   # head needle lights on both
        self._sync_hot()
        if zone == "ring" and not self._dragging:
            dx, dy = self._ref_point(pos)
            self._swell_angle = math.degrees(math.atan2(dy, dx))
        self._swell.set_target(
            1.0 if (zone == "ring" or self._dragging) else 0.0)
        self._disc_hot.set_target(1.0 if zone == "disc" else 0.0)
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
            self._drag_dir = 0
            self._sync_hot()
            self._swell.set_target(1.0)
            # No gap-pinning on the press itself: it lands wherever it is
            # clicked (from a full ring, a click on the first half used to
            # read as a jump across the bottom gap and be ignored).
            self._drag_frac = None
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
            # A release just off a SNAP_DB step lands on it.
            db = self._strength_db
            step = int(round(db / SNAP_DB)) * SNAP_DB
            if step != db and abs(step - db) <= SNAP_WITHIN:
                self._user_set_strength(step)
            self._drag_dir = 0
            self._sync_ends()
            self._spring_back()
            self._update_hover_cursor(event.position())   # re-syncs the glow
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _sync_hot(self) -> None:
        self._hot_blend.set_target(1.0 if (self._hot or self._dragging)
                                   else 0.0)

    def _sync_ends(self) -> None:
        """"gentle" / "strong" light up on the side a drag is heading."""
        self._gentle_hot.set_target(1.0 if self._drag_dir < 0 else 0.0)
        self._strong_hot.set_target(1.0 if self._drag_dir > 0 else 0.0)

    def leaveEvent(self, event):  # noqa: N802 (Qt override)
        self._hot = False
        self._sync_hot()
        if not self._dragging:
            self._swell.set_target(0.0)
        self._disc_hot.set_target(0.0)
        self.update()
        super().leaveEvent(event)

    def wheelEvent(self, event):  # noqa: N802 (Qt override)
        if not self.isEnabled():
            return super().wheelEvent(event)
        self._wheel_acc += event.angleDelta().y()
        steps = int(self._wheel_acc / 120)
        if steps:
            self._wheel_acc -= steps * 120
            ctrl = event.modifiers() & Qt.KeyboardModifier.ControlModifier
            unit = WHEEL_STEP_COARSE if ctrl else WHEEL_STEP
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

    # -- what each part looks like now ----------------------------------------------
    @staticmethod
    def _colours(palette) -> dict:
        white = QColor("#ffffff")
        gold = QColor(palette["secondary"])
        unlit = QColor(palette["muted"])
        unlit.setAlpha(80)
        dim = QColor(gold)
        dim.setAlphaF(0.36)
        return {
            "gold": gold, "accent": QColor(palette["accent"]),
            "unlit": unlit, "dim": dim, "white": white,
            "text": QColor(palette["text"]), "muted": QColor(palette["muted"]),
            "error": QColor(palette["error"]),
            "comet": mix_rgba(gold, white, 0.75),
            "flash": mix_rgba(QColor(palette["accent_light"]), white, 0.6),
            "groove": QColor(palette["groove"]),
            "pill": QColor(palette["pill"]),
            "focus": QColor(palette["accent_light"]),
        }

    def _comet_look(self, i: int, base: QColor, col: dict, t: float):
        """Starting: (colour, radial scale) of tick i as the comet laps."""
        u = t - i * COMET_STEP
        if u < 0 or not motion_ok():
            return base, 1.0
        ph = (u % COMET_MS) / COMET_MS
        if ph < 0.07:
            return (mix_rgba(col["comet"], col["gold"], ph / 0.07),
                    1.0 + 0.05 * (1 - ph / 0.07))
        if ph < 0.18:
            return mix_rgba(col["gold"], base, (ph - 0.07) / 0.11), 1.0
        return base, 1.0

    def _lit_look(self, i: int, col: dict, t: float):
        """(colour, alpha factor, radial scale) of lit tick i."""
        phase = self._phase
        if phase == "starting":
            colour, scale = self._comet_look(i, col["dim"], col, t)
            return colour, 1.0, scale
        if phase == "live":
            u = (t - i * IGNITE_STEP) / IGNITE_MS
            if u < 0:
                colour, scale = col["gold"], 1.0
            elif u < 0.35:
                colour = mix_rgba(col["gold"], col["flash"], u / 0.35)
                scale = 1.0 + 0.07 * _ease_out(u / 0.35)
            elif u < 1:
                v = _ease_out((u - 0.35) / 0.65)
                colour = mix_rgba(col["flash"], col["accent"], v)
                scale = 1.07 - 0.07 * v
            else:
                colour, scale = col["accent"], 1.0
            # A brightness crest flows clockwise over the lit ticks.
            ph = ((t + (TICKS - 1 - i) * FLOW_STEP) % FLOW_MS) / FLOW_MS
            crest = (_ease_in_out(_rise_fall(ph / 0.32, 0.375))
                     if ph < 0.32 else 0.0)
            return colour, 0.78 + 0.22 * crest, scale
        if phase == "error":
            return (mix_rgba(col["white"], col["error"],
                             _ease_out(t / ERROR_FLASH_MS)), 1.0, 1.0)
        # idle / stopping: gold, or still draining back from the accent.
        if self._drain_at is not None:
            d = self._since(self._drain_at) - (TICKS - 1 - i) * DRAIN_STEP
            if d < DRAIN_MS:
                return (mix_rgba(col["accent"], col["gold"],
                                 _ease_out(max(0.0, d) / DRAIN_MS)), 1.0, 1.0)
        return col["gold"], 1.0, 1.0

    def _sweep_visibility(self, i: int) -> float:
        """First show: how much of tick i the entrance sweep has drawn."""
        if self._sweep_at is None:
            return 1.0
        u = self._since(self._sweep_at) / SWEEP_MS
        if u >= 1.0:
            return 1.0
        if u < 0:
            return 0.0
        edge = -16.0 + 316.0 * _ease_out(u)
        return _clamp((edge + 16.0 - ARC_SPAN * i / (TICKS - 1)) / 16.0)

    def _swell_px(self, angle: float, head_angle: float) -> float:
        amount = self._swell.value
        if amount <= 0.01:
            return 0.0
        centre = head_angle if self._dragging else self._swell_angle
        d = abs(((angle - centre) + 180.0) % 360.0 - 180.0)
        return amount * SWELL_PX * math.exp(-(d / SWELL_DEG) ** 2)

    def _needle(self, t: float):
        """(alpha, glow, radial scale) of the head needle."""
        live = self._phase == "live"
        if live and not self._dragging:
            u = (t - (self._ignite_end() - 60)) / NEEDLE_IN_MS
            alpha = _ease_out(u / 0.4)
            glow = _rise_fall(u, 0.4)
        elif self._phase in ("idle", "live"):
            alpha = 1.0 if (self._dragging or live) else self._hot_blend.value
            glow = 0.0
        else:
            return 0.0, 0.0, 1.0
        scale = 1.0
        if self._dragging and self._pluck_at is not None:
            span = PLUCK_BIG_MS if self._pluck_big else PLUCK_MS
            hit = _rise_fall(self._since(self._pluck_at) / span, 0.38)
            scale += (0.1 if self._pluck_big else 0.045) * hit
            if self._pluck_big:
                glow = max(glow, hit)
        return alpha, glow, scale

    def _pop_scale(self, t: float) -> float:
        if self._phase != "live":
            return 1.0
        u = (t - self._ignite_end()) / POP_MS
        if u < 0 or u >= 1:
            return 1.0
        if u < 0.3:
            return 1.0 - 0.1 * _ease_out(u / 0.3)
        return 0.9 + 0.1 * _back((u - 0.3) / 0.7)

    def _charge(self, t: float) -> float:
        """Live: 0..1 glow of the disc around each later lattice ping
        (after live: the glow it was left with, fading out)."""
        if not motion_ok():
            return 0.0
        if self._phase != "live":
            u = self._since(self._charge_drop_at) / CHARGE_DROP_MS
            if self._charge_from <= 0.0 or u >= 1.0:
                return 0.0
            return self._charge_from * (1.0 - _ease_out(u))
        rel = t - self._ignite_end()
        k = max(1, round(rel / PING_PERIOD_MS))
        d = rel - k * PING_PERIOD_MS
        if -CHARGE_LEAD_MS <= d < 0:
            return _ease_in(1.0 + d / CHARGE_LEAD_MS)
        if 0 <= d < CHARGE_FADE_MS:
            return 1.0 - _ease_out(d / CHARGE_FADE_MS)
        return 0.0

    def _shake_px(self, t: float) -> float:
        if self._phase != "error" or t >= SHAKE_MS:
            return 0.0
        pos = t / SHAKE_MS * (len(SHAKE) - 1)
        i = int(pos)
        nxt = SHAKE[min(i + 1, len(SHAKE) - 1)]
        return SHAKE[i] + (nxt - SHAKE[i]) * (pos - i)

    def _glyph_colour(self, col: dict, t: float) -> QColor:
        phase = self._phase
        if phase == "error":
            return col["error"]
        if phase == "live":
            start = self._ignite_end() - 120
            return mix_rgba(col["gold"], col["accent"],
                            _ease_out((t - start) / GLYPH_MS))
        if phase == "stopping":
            return mix_rgba(col["accent"], col["gold"], _ease_out(t / GLYPH_MS))
        return col["gold"]

    # -- painting ------------------------------------------------------------------------
    @staticmethod
    def _centered_text(p, text, cx, baseline, font, color) -> None:
        p.setFont(font)
        p.setPen(color)
        width = QFontMetricsF(font).horizontalAdvance(text)
        p.drawText(QPointF(cx - width / 2, baseline), text)

    @staticmethod
    def _line(p, angle, r0, r1, colour, width) -> None:
        c = REF / 2
        pen = QPen(colour, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        rad = math.radians(angle)
        cs, sn = math.cos(rad), math.sin(rad)
        p.drawLine(QPointF(c + r0 * cs, c + r0 * sn),
                   QPointF(c + r1 * cs, c + r1 * sn))

    def paintEvent(self, event):  # noqa: N802 (Qt override)
        w, h = self.width(), self.height()
        k = min(w, h) / REF
        col = self._colours(current_theme())
        t = self._ms()
        c = REF / 2

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.translate(w / 2, h / 2)
        p.scale(k, k)
        p.translate(-c, -c)
        self._paint_ring(p, col, t)
        self._paint_core(p, col, t)
        self._paint_readout(p, col)
        p.end()

    def _paint_ring(self, p, col, t) -> None:
        """The ticks (lit ones show the strength) and the head needle."""
        c = REF / 2
        lit = lit_count(self._strength_db)
        head_angle = ARC_START + ARC_SPAN * max(0, lit - 1) / (TICKS - 1)
        p.save()
        p.translate(c, c)
        p.rotate(self._over)          # stretched past an end
        p.translate(-c, -c)
        for i in range(TICKS):
            visible = self._sweep_visibility(i)
            if visible <= 0.0:
                continue
            angle, r_in, r_out = tick_geometry(i)
            if i < lit:
                colour, alpha, scale = self._lit_look(i, col, t)
            elif self._phase == "starting":
                colour, scale = self._comet_look(i, col["unlit"], col, t)
                alpha = 1.0
            else:
                colour, alpha, scale = col["unlit"], 1.0, 1.0
            colour = QColor(colour)
            colour.setAlphaF(colour.alphaF() * alpha * visible)
            lift = self._swell_px(angle, head_angle)
            self._line(p, angle, (r_in + lift) * scale,
                       (r_out + lift) * scale, colour, 4.0)

        # The head needle: white over the last lit tick.
        if lit > 0:
            alpha, glow, scale = self._needle(t)
            alpha *= self._sweep_visibility(lit - 1)
            if alpha > 0.01:
                _, r_in, r_out = tick_geometry(lit - 1)
                lift = self._swell_px(head_angle, head_angle)
                r0, r1 = (r_in + lift) * scale, (r_out + lift) * scale
                halo = QColor(col["white"])
                halo.setAlphaF(alpha * (0.12 + 0.4 * glow))
                self._line(p, head_angle, r0, r1, halo, 8.0 + 8.0 * glow)
                needle = QColor(col["text"])
                needle.setAlphaF(alpha)
                self._line(p, head_angle, r0, r1, needle, 5.0)
        p.restore()

    def _paint_core(self, p, col, t) -> None:
        """Ripple, disc, charge glow, power glyph and the rolling label."""
        c = REF / 2
        live = self._phase == "live"

        # The ripple leaving the disc as the live sweep closes.
        if live:
            u = (t - self._ignite_end()) / RIPPLE_MS
            if 0 <= u < 1:
                ring = QColor(col["accent"])
                ring.setAlphaF(0.8 * (1 - u))
                p.setPen(QPen(ring, 2.0))
                p.setBrush(Qt.BrushStyle.NoBrush)
                radius = DISC_R * (1 + 0.64 * (1 - (1 - u) ** 4))
                p.drawEllipse(QPointF(c, c), radius, radius)

        press = max(0.0, min(1.0, self._press))
        scale = (1.0 - 0.07 * press) * self._pop_scale(t)
        p.save()
        p.translate(c + self._shake_px(t), c)
        p.scale(scale, scale)
        p.translate(-c, -c)

        charge = self._charge(t)
        if charge > 0.01:   # soft light just outside the rim
            glow = QRadialGradient(QPointF(c, c), DISC_R + 26)
            outer, clear = QColor(col["accent"]), QColor(col["accent"])
            outer.setAlphaF(0.18 * charge)
            clear.setAlphaF(0.0)
            glow.setColorAt(DISC_R / (DISC_R + 26), outer)
            glow.setColorAt(1.0, clear)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow)
            p.drawEllipse(QPointF(c, c), DISC_R + 26, DISC_R + 26)

        # Disc: the rim warms under the pointer (gold idle, accent live).
        hot = self._disc_hot.value
        tint = QColor(col["accent"] if live else col["gold"])
        tint.setAlphaF(0.45)
        p.setPen(QPen(mix_rgba(col["groove"], tint, hot), 2.0))
        p.setBrush(col["pill"].lighter(100 + int(8 * hot)))
        p.drawEllipse(QPointF(c, c), DISC_R, DISC_R)
        if charge > 0.01:   # glow inside the rim, and the rim itself
            inner = QRadialGradient(QPointF(c, c), DISC_R)
            edge, clear = QColor(col["accent"]), QColor(col["accent"])
            edge.setAlphaF(0.3 * charge)
            clear.setAlphaF(0.0)
            inner.setColorAt(0.62, clear)
            inner.setColorAt(1.0, edge)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(inner)
            p.drawEllipse(QPointF(c, c), DISC_R - 1, DISC_R - 1)
            rim = QColor(col["accent"])
            rim.setAlphaF(0.9 * charge)
            p.setPen(QPen(rim, 2.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(c, c), DISC_R - 0.5, DISC_R - 0.5)
        if self._key_focus and self.hasFocus():
            p.setPen(QPen(col["focus"], 2.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(c, c), DISC_R + 6.0, DISC_R + 6.0)

        # Power glyph: the stem sinks under a press and lifts on hover.
        glyph = QPen(self._glyph_colour(col, t), 5.5)
        glyph.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(glyph)
        p.setBrush(Qt.BrushStyle.NoBrush)
        gy, gr = 137.75, 20.0
        stem = 3.0 * press - 1.5 * hot
        p.drawLine(QPointF(c, gy - 26.0 + stem), QPointF(c, gy - 6.0 + stem))
        p.drawArc(QRectF(c - gr, gy - gr, 2 * gr, 2 * gr), 130 * 16, 280 * 16)

        self._paint_label(p, col, t)
        p.restore()

    def _paint_label(self, p, col, t) -> None:
        """Start / dots / Stop / Retry, rolled through like a drum."""
        c = REF / 2
        top, step = 173.0, 26.0
        p.save()
        p.setClipRect(QRectF(c - 60, top, 120, step))
        head = QFont(heading_family())
        head.setPixelSize(21)
        head.setWeight(QFont.Weight.Bold)
        pos = self._label.value
        for index, text in enumerate(LABELS):
            y = top + step * (index - pos)
            if y <= top - step or y >= top + step:
                continue
            if index == 1:
                self._paint_dots(p, col, t, y + step / 2)
            else:
                colour = col["error"] if index == 3 else col["text"]
                self._centered_text(p, text, c, y + 18.0, head, colour)
        p.restore()

    def _paint_dots(self, p, col, t, cy) -> None:
        """The "..." label: lit in step with the comet while starting,
        settling right to left while stopping."""
        c = REF / 2
        p.setPen(Qt.PenStyle.NoPen)
        for j in range(3):
            colour, alpha, lift, scale = QColor(col["text"]), 0.35, 0.0, 1.0
            if self._phase == "starting" and motion_ok():
                colour, alpha = QColor(col["gold"]), 0.3
                u = t - j * DOT_STEP
                if u >= 0:
                    ph = (u % COMET_MS) / COMET_MS
                    if ph < 0.33:
                        v = ph / 0.33
                        lift, scale = -4.0 * (1 - v), 1.25 - 0.25 * v
                        if ph < 0.12:
                            colour = mix_rgba(col["comet"], col["gold"],
                                              ph / 0.12)
                            alpha = 1.0
                        else:
                            alpha = 1.0 - 0.7 * (ph - 0.12) / 0.21
            elif self._phase == "stopping":
                q = _ease_in((t - (2 - j) * 110) / DOTS_OUT_MS)
                colour = mix_rgba(col["accent"], col["gold"], q)
                alpha, lift, scale = 1.0 - 0.75 * q, 3.0 * q, 1.0 - 0.3 * q
            colour.setAlphaF(colour.alphaF() * alpha)
            p.setBrush(colour)
            r = 3.0 * scale
            p.drawEllipse(QPointF(c + (j - 1) * 13.0, cy + lift), r, r)

    def _paint_readout(self, p, col) -> None:
        """"-50 dB" with rolling digits, its caption and the end labels."""
        c = REF / 2
        big = QFont(heading_family())
        big.setPixelSize(30)
        big.setWeight(QFont.Weight.Bold)
        metrics = QFontMetricsF(big)
        digit_w = max(metrics.horizontalAdvance(str(d)) for d in range(10))
        minus_w = metrics.horizontalAdvance("-")
        unit_w = metrics.horizontalAdvance("dB")
        total = minus_w + 2 * digit_w + 6.0 + unit_w
        baseline, step = 276.0, 32.0

        p.save()
        bump = _rise_fall(self._since(self._bump_at) / BUMP_MS, 0.4)
        if bump > 0:
            p.translate(c, baseline - 11)
            p.scale(1 + 0.08 * bump, 1 + 0.08 * bump)
            p.translate(-c, -(baseline - 11))
        x = c - total / 2
        p.setFont(big)
        p.setPen(col["text"])
        p.drawText(QPointF(x, baseline), "-")
        x += minus_w
        for column in (self._tens.value, self._ones.value):
            p.save()
            p.setClipRect(QRectF(x, baseline - 28, digit_w, 34))
            first = max(0, int(math.floor(column)) - 1)
            for d in range(first, min(10, first + 3)):
                width = metrics.horizontalAdvance(str(d))
                p.drawText(QPointF(x + (digit_w - width) / 2,
                                   baseline + step * (d - column)), str(d))
            p.restore()
            x += digit_w
        p.drawText(QPointF(x + 6.0, baseline), "dB")
        p.restore()

        small = QFont(self.font())
        small.setPixelSize(12)
        self._centered_text(p, "reduction strength", c, 294.0, small,
                            col["muted"])
        for label, x, blend, shift in (
                ("gentle", 52.0, self._gentle_hot, -3.0),
                ("strong", 248.0, self._strong_hot, 3.0)):
            tone = mix_rgba(col["muted"], col["text"], blend.value)
            self._centered_text(p, label, x + shift * blend.value, 278.0,
                                small, tone)
