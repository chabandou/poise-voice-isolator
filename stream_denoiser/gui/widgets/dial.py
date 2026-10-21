"""
Poise Voice Isolator - Dial Button

The Start/Stop control: a 270-degree ring of ticks around a power disc.
The ring doubles as the reduction-strength control (drag, wheel, arrow
keys): lit ticks = how strongly unwanted sound is removed. Idle the ring
is the theme's secondary colour; while isolating it turns to the accent.

Evolves PowerButton and keeps its API (toggled_state / set_active /
set_transitioning / set_error / is_active), so MainWindow wiring is
unchanged. The press squash comes from PowerButton; everything else runs
on the dial's own clock. All of it is ambient motion (animations.
ambient_ok): POISE_NO_ANIM / POISE_REDUCE_MOTION or Reduce motion in
Settings show each state's resting look; hover feedback stays.

Motion, phase by phase:
- hover: ticks near the pointer lift outward and the head needle fades
  in; over the disc its rim warms and the power stem lifts;
- drag: the needle glides tick to tick and plucks (harder every 10 dB,
  when the readout bumps too); the readout's digits roll like an
  odometer; past either end the ring stretches up to OVERSHOOT_MAX
  degrees and springs back on release, which snaps to the nearest
  SNAP_DB step when within SNAP_WITHIN dB of it;
- wheel / arrow keys: the needle shows and glides to the new value
  (NUDGE_GLIDE_MS), the lit ticks filling or emptying behind it; each
  tick it passes flashes like the starting comet and settles (a short
  trail), it plucks and the ticks around it lift as in a drag, the end
  it heads for lights, and a step past either end stretches the ring and
  springs back. NUDGE_HOLD_MS after the last step it all fades away;
- starting: lit ticks dim and a comet sweeps the ring in about a second,
  resting a beat before the next sweep; the label's three dots light up
  in step with it;
- live: ticks ignite one after another; when the sweep closes the needle
  flashes, the disc pops, a ripple leaves it and `ignited` fires (the
  lattice pings follow it, see PatternCard). In the second before each
  later ping the disc charges up (glow and rim) and the lit ticks all
  brighten with it, fading together as the ping leaves;
- stopping: the accent drains back from the head; the dots settle; a
  charge glow caught mid-way fades out (CHARGE_DROP_MS) rather than
  cutting off, and no new charge starts;
- error: lit ticks flash white then settle red and the disc shakes.

A theme whose motion is "breath" (Vigil, Eclipse) moves the same phases slower
and softer, on the night sky's rhythm (widgets/sky.py): idle, the lit
ticks breathe; starting, light gathers from the ends of the lit arc
inward; live, it blooms from the middle out, the disc swells (no pop),
and then the ticks and the disc's charge (glow and rim) breathe on one
BREATH_MS cycle, a pulse leaving the dial as each breath begins (the
halos and band are the sky's); stopping, the ends settle back first; an
error trembles. The label mists from one to the next instead of rolling,
and so does each readout digit that changes, dissolving like smoke in
place.

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
    QColor, QFont, QFontMetricsF, QImage, QPainter, QPen, QRadialGradient,
)

from .pattern_card import PING_PERIOD_MS
from .power_button import PowerButton
from .sky import (
    BREATH as _breath, BREATH_MS, CHARGE, EASE_IN_OUT as _css_in_out,
    GATHER_MS, IDLE_BREATH_MS, SOFT as _soft, TICKS_IDLE, TICKS_LIVE,
    breath_pos, keyframes,
)
from ..animations import (
    Blend, EASE_BREATHE, FrameTimer, ambient_ok, cubic_bezier_fn, mix_rgba,
    smoke_spread, smoke_wisps,
    ease_back as _back, ease_in as _ease_in, ease_in_out as _ease_in_out,
    ease_out as _ease_out, rise_fall as _rise_fall,
)
from ..fonts import heading_family
from ..scaling import sp
from ..themes import breathing, current as current_theme

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
#: The disc's parts, bottom up, and how far each reaches (design px): the
#: glow around it, its face, and the inner glow and rim the charge lights.
DISC_PARTS = (("glow", DISC_R + 36.0), ("face", DISC_R + 2.0),
              ("inner", DISC_R + 2.0), ("rim", DISC_R + 2.0))
RING_HIT_MIN = 102.0  # ring zone (drag) vs disc zone (click)
RING_HIT_MAX = 150.0
DISC_HIT = 100.0

# -- motion (ms unless noted) ---------------------------------------------------
SWEEP_DELAY_MS = 300      # first show: the ring sweeps on from the gentle end
SWEEP_MS = 1150
SWEEP_FADE_DEG = 10.0     # ...a tick fades in as the edge crosses this
SWEEP_CREST_DEG = 40.0    # ...and its crest fades over this, behind it
SWEEP_HOLD_MS = 3000      # ...held for the window's entrance at most this
SWEEP_EARLY_S = 0.02      # a sweep timer may fire this early
SWELL_PX = 3.4            # hover lift of the ticks nearest the pointer
SWELL_DEG = 13.0          # ...and how far it spreads
OVERSHOOT_MAX = 4.0       # degrees the ring stretches past an end
COMET_MS = 990            # starting: one sweep of the comet
COMET_STEP = 18           # ...the delay between neighbouring ticks
COMET_REST_MS = 330       # ...and the pause before the next sweep
COMET_LAP_MS = COMET_MS + COMET_REST_MS
COMET_FLASH_MS = 69       # a tick flashes, fades to gold...
COMET_TAIL_MS = 178       # ...and is back to its own colour by here
DOT_STEP = 330            # the label's dots, a third of a sweep apart
DOT_LIFT_MS = 327         # one dot's lift...
DOT_FLASH_MS = 119        # ...brightest over its first part
IGNITE_STEP = 14          # live: between ticks igniting
IGNITE_MS = 520           # one tick's ignition
IGNITE_TAIL = 100         # the sweep "closes" this long after the last tick
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
NUDGE_GLIDE_MS = 220      # wheel / key step: the needle glides there
NUDGE_HOLD_MS = 650       # ...stays lit this long after the last step
NUDGE_FADE_MS = 360       # ...then fades back
NUDGE_STRETCH = 0.55      # a step past an end stretches the ring this much
TRAIL_MS = 520            # a tick the needle passes flashes, then settles
TRAIL_PEAK = 0.14         # ...reaching full flash this far in
PLUCK_BIG_MS = 420
BUMP_MS = 340
FRAME_MS = 16             # transitions
LOOP_FRAME_MS = 33        # steady loops (the live charge)

# -- the breathing rhythm (themes whose motion is "breath") --------------------
BLOOM_STEP = 18           # live: between ticks, outward from the middle
BLOOM_MS = 900            # one tick's bloom...
BLOOM_PEAK = 0.45         # ...brightest this far in
BLOOM_CLOSE = 520         # the bloom closes this long after the middle's
GATHER_STEP = 24          # starting: between ticks, inward from the ends
GATHER_FLASH = 0.26       # ...each flash fading over this much of a lap
SETTLE_STEP = 14          # stopping: the ends settle back first
SETTLE_MS = 700
SWELL_LEAD = 200          # the disc swells (and the needle rises) this
BREATH_SWELL_MS = 1300    # ...long before the bloom closes
BREATH_NEEDLE_MS = 1000
BREATH_GLYPH_LEAD = 400
BREATH_GLYPH_MS = 1200
BREATH_SWEEP_DELAY_MS = 500
BREATH_SWEEP_MS = 1800
CHARGE_RAMP_MS = 400      # live begins part-way into a breath: ease it in
DOT_BREATH_STEP = 300     # starting: the dots breathe a beat apart
DOT_SETTLE_STEP = 240     # stopping: and settle
DOT_SETTLE_MS = 900
MIST_MS = 600             # label: the old one mists away as the new rises
NUMBER_MIST_MS = 520      # readout: each changing digit, the same...
DRAG_MIST_MS = 260        # ...quicker while dragging
SMOKE_PX = 6.0            # design px a digit's smoke spreads as it fades
ERROR_PULSE_MS = 1100     # error: lit ticks dim and return, twice...
TREMBLE_MS = 700          # ...and the disc trembles
TREMBLE = ((0, 0.0, _css_in_out), (0.15, -2.0, _css_in_out),
           (0.35, 2.0, _css_in_out), (0.55, -2.0, _css_in_out),
           (0.75, 2.0, _css_in_out), (1, 0.0, _css_in_out))
GLOW_ALPHA = 0.32         # a lit tick's glow at full strength
GLOW_IDLE, GLOW_LIVE = 0.3, 0.55

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


# The first show's sweep: eases in, then glides a long way to rest.
_sweep_ease = cubic_bezier_fn(0.3, 0.0, 0.15, 1.0)


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
    phase_changed = pyqtSignal(str)      # idle | starting | live | ...

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
        # Wheel / key steps: where the needle is drawn (in ticks; glides),
        # how engaged the step motion is, and the passed ticks' flashes.
        self._needle_pos = Blend(self, self.update, NUDGE_GLIDE_MS,
                                 QEasingCurve.Type.OutCubic,
                                 lit_count(self._strength_db) - 1)
        self._nudge = Blend(self, self.update, 140)
        self._nudge_timer = QTimer(self)
        self._nudge_timer.setSingleShot(True)
        self._nudge_timer.timeout.connect(self._end_nudge)
        self._trail = {}                  # tick -> perf_counter flash time

        # One clock drives every timed effect; the phase says which.
        self._phase = "idle"
        self._phase_at = time.perf_counter()
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
        self._clock = FrameTimer(self)   # shared with the card's
        self._clock.setInterval(FRAME_MS)
        self._clock.timeout.connect(self._tick)
        self._ring = self._ring_key = None   # see _paint_ring
        self._disc_parts = {}                  # see _paint_disc_cached
        self._ring_sink = None            # see set_ring_sink
        self._face_sink = None            # see set_face_sink
        self._push_timer = QTimer(self)   # coalesces a frame's changes
        self._push_timer.setSingleShot(True)
        self._push_timer.setInterval(0)
        self._push_timer.timeout.connect(self._push_face)

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
        # Breath: the label mists from one to the next, and so do the
        # readout's digits, each column on its own (per column: digit ->
        # [alpha from, to, perf_counter start]).
        self._label_from = self._label_to = 0
        self._label_mist = Blend(self, self.update, MIST_MS, EASE_BREATHE,
                                 1.0)
        self._mists = tuple({d: [1.0, 1.0, 0.0]}
                            for d in divmod(-self._strength_db, 10))
        self._over = 0.0                  # ring stretch, degrees
        self._over_anim = QVariantAnimation(self)
        self._over_anim.setDuration(560)
        self._over_anim.setEasingCurve(_spring_curve(2.2))
        self._over_anim.valueChanged.connect(self._set_over)

        self.setAccessibleName("Start isolating")
        self.setToolTip(
            "Press to start/stop isolation. Scroll to set the reduction "
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
            self._needle_pos.snap(lit_count(db) - 1)
            self._roll_digits()
            self.update()

    def _user_set_strength(self, db, nudge: bool = False) -> None:
        db = clamp_db(db)
        if db == self._strength_db:
            return
        old = self._strength_db
        self._strength_db = db
        if nudge:
            self._glide_needle(lit_count(db) - 1)
        else:
            self._needle_pos.snap(lit_count(db) - 1)
        if self._dragging or nudge:
            now = time.perf_counter()
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
        self._mist_number(animated and ambient_ok())

    # -- breath: misting digits ----------------------------------------------------
    def _mist_ms(self) -> float:
        """How long a readout digit takes to mist from one to the next."""
        return DRAG_MIST_MS if self._dragging else NUMBER_MIST_MS

    def _mist_alpha(self, entry, now: float) -> float:
        start, end, at = entry
        u = (now - at) * 1000.0 / self._mist_ms()
        return start + (end - start) * _breath(min(1.0, max(0.0, u)))

    def _mist_number(self, animated: bool) -> None:
        """Each digit that changes mists away as the new one surfaces;
        a digit that stays holds still."""
        digits = divmod(-self._strength_db, 10)
        if not animated:
            self._mists = tuple({d: [1.0, 1.0, 0.0]} for d in digits)
            return
        now = time.perf_counter()
        self._mists = tuple(self._mist_column(column, digit, now)
                            for column, digit in zip(self._mists, digits))
        if breathing():
            self._run_clock()

    def _mist_column(self, column: dict, digit: int, now: float) -> dict:
        """One readout column moving to `digit`."""
        entry = column.get(digit)
        if entry is not None and entry[1] > 0.0:
            return column                  # already there (or surfacing)
        mists = {}
        for d, e in column.items():
            alpha = self._mist_alpha(e, now)
            if alpha > 0.005:
                mists[d] = [alpha, 0.0, now]
        mists[digit] = [self._mist_alpha(entry, now) if entry else 0.0, 1.0,
                        now]
        return mists

    def _misting(self) -> bool:
        now = time.perf_counter()
        fade = self._mist_ms()
        return any((now - at) * 1000.0 < fade
                   for column in self._mists for _, _, at in column.values())

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

    def refresh_motion(self) -> None:
        """Reduce motion changed (animations.set_still): settle on each
        state's resting look now, or let the loops move again."""
        if ambient_ok():
            self._run_clock()
        else:
            self._clock.stop()
            self._mist_number(False)
            if self._phase == "live" and not self._ignited:
                self._ignite()
        self.update()

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
            self._charge_drop_at = time.perf_counter()
        elif phase == "live":
            self._charge_from, self._charge_drop_at = 0.0, None
        self._phase = phase
        self._phase_at = time.perf_counter()
        if phase == "stopping":
            self._drain_at = self._phase_at
        elif phase != "idle":
            self._drain_at = None
        if phase == "live":
            self._ignite_lit = lit_count(self._strength_db)
            self._ignited = False
            if not ambient_ok():
                self._ignite()
        label = LABEL_OF_PHASE[phase]
        self._label.set_target(label, self.isVisible())
        if label != self._label_to:
            # Breath: the old label mists away as the new one surfaces.
            mist = self._label_mist.value
            if label == self._label_from:      # back before it had gone
                self._label_from, self._label_to = self._label_to, label
                self._label_mist.snap(1.0 - mist)
            else:
                if mist >= 0.5:
                    self._label_from = self._label_to
                self._label_to = label
                self._label_mist.snap(0.0)
            self._label_mist.set_target(1.0, self.isVisible())
        self._run_clock()
        self.update()
        self.phase_changed.emit(phase)

    def phase(self) -> str:
        """idle | starting | live | stopping | error"""
        return self._phase

    def _ms(self) -> float:
        """Milliseconds into the phase (settled when motion is reduced)."""
        if not ambient_ok():
            return 1e9
        return (time.perf_counter() - self._phase_at) * 1000.0

    @staticmethod
    def _since(stamp) -> float:
        """Milliseconds since a perf_counter stamp (None: long ago)."""
        if stamp is None or not ambient_ok():
            return 1e9
        return (time.perf_counter() - stamp) * 1000.0

    def _ignite_end(self) -> float:
        """When the live sweep (breath: the bloom) closes, in ms into the
        live phase."""
        if breathing():
            return self._bloom_mid() * BLOOM_STEP + BLOOM_CLOSE
        return self._ignite_lit * IGNITE_STEP + IGNITE_TAIL

    def _bloom_mid(self) -> float:
        """Breath: the middle of the arc lit when isolating began."""
        return max(0.0, (self._ignite_lit - 1) / 2.0)

    def _sweep_ms(self):
        """(delay, duration) of the first show's ring sweep."""
        if breathing():
            return BREATH_SWEEP_DELAY_MS, BREATH_SWEEP_MS
        return SWEEP_DELAY_MS, SWEEP_MS

    def _ignite(self) -> None:
        if not self._ignited:
            self._ignited = True
            self.ignited.emit()

    # -- the clock ------------------------------------------------------------------
    def _run_clock(self) -> None:
        if ambient_ok() and not self._clock.isActive() and self._animating():
            self._clock.setInterval(FRAME_MS)
            self._clock.start()

    def _animating(self) -> bool:
        if self._phase in ("starting", "live", "stopping"):
            return True
        breath = breathing()
        drain = ((TICKS - 1) / 2.0 * SETTLE_STEP + SETTLE_MS if breath
                 else (TICKS - 1) * DRAIN_STEP + DRAIN_MS)
        if self._since(self._drain_at) < drain:
            return True
        error_ms = 2 * ERROR_PULSE_MS if breath else ERROR_FLASH_MS
        if self._phase == "error" and self._ms() < error_ms:
            return True
        if breath and (self._misting() or self._label_mist.running):
            return True
        if (self._charge_from > 0.01
                and self._since(self._charge_drop_at) < CHARGE_DROP_MS):
            return True
        if self._trail or self._nudging():
            return True
        return (self._since(self._pluck_at) < PLUCK_BIG_MS
                or self._since(self._bump_at) < BUMP_MS
                or self._sweep_moving())

    def _sweeping(self) -> bool:
        """The first show's sweep is due or drawing the ring (the ticks
        hide till it reaches them)."""
        return (self._sweep_at is not None
                and self._since(self._sweep_at) < self._sweep_ms()[1])

    def _sweep_moving(self) -> bool:
        """The sweep has begun (before, nothing moves: see showEvent)."""
        return self._sweeping() and self._since(self._sweep_at) >= 0.0

    def _tick(self) -> None:
        if any(len(column) > 1 for column in self._mists):
            now = time.perf_counter()   # drop digits that have misted out
            self._mists = tuple(
                {d: e for d, e in column.items()
                 if e[1] > 0.0 or self._mist_alpha(e, now) > 0.005}
                for column in self._mists)
        if self._trail:
            now = time.perf_counter()
            gone = TRAIL_MS / 1000.0
            self._trail = {i: s for i, s in self._trail.items()
                           if now - s < gone}
        if (self._phase == "live" and not self._ignited
                and self._ms() >= self._ignite_end()):
            self._ignite()
        if not self._animating():
            self._clock.stop()
        else:
            # Once the live sweep has settled only slow loops are left.
            closing = BREATH_SWELL_MS if breathing() else RIPPLE_MS
            settled = (self._phase == "live"
                       and not self._trail and not self._nudging()
                       and self._ms() > self._ignite_end() + closing
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
            if ambient_ok():
                delay = self._sweep_ms()[0]
                self._sweep_at = time.perf_counter() + delay / 1000.0
                # The clock starts with the sweep.
                QTimer.singleShot(delay, self._begin_sweep)
        self._run_clock()

    def _begin_sweep(self) -> None:
        """The delay is over: the sweep starts now. (Timers may fire a
        little before their due time; had the sweep been left due, the
        clock would not start and the ring would only draw on as other
        repaints came.) A timer whose sweep was put off since does
        nothing."""
        if self._sweep_at is not None:
            now = time.perf_counter()
            if self._sweep_at - now < SWEEP_EARLY_S:
                self._sweep_at = min(self._sweep_at, now)
        self._run_clock()

    def hold_sweep(self) -> None:
        """Put the first show's ring sweep off until sweep_on_in (the
        window times Home's entrance); it starts by itself after
        SWEEP_HOLD_MS if that never comes."""
        if self._sweep_at is not None and self._sweeping():
            self._sweep_at = time.perf_counter() + SWEEP_HOLD_MS / 1000.0
            QTimer.singleShot(SWEEP_HOLD_MS, self._begin_sweep)

    def sweep_on_in(self, delay_ms: int) -> None:
        """Start the first show's ring sweep `delay_ms` from now, if it
        has not started yet."""
        if (self._sweep_at is not None and self._sweeping()
                and not self._sweep_moving()):
            self._sweep_at = time.perf_counter() + delay_ms / 1000.0
            QTimer.singleShot(int(delay_ms), self._begin_sweep)

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
        if abs(self._over) < 0.01 or not ambient_ok():
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
            self._nudge_to(self._strength_db - steps * unit)  # up = stronger
        event.accept()

    # -- stepped changes (wheel / keys) ---------------------------------------------
    def _nudge_to(self, db) -> None:
        """A wheel or key step: the needle glides there, trailing."""
        target = clamp_db(db)
        if ambient_ok() and self.isVisible():
            self._nudge.set_target(1.0)
            self._nudge_timer.start(NUDGE_HOLD_MS)
            if target == self._strength_db and target != db:
                # Pushing past an end: the ring gives, then springs back.
                self._drag_dir = 1 if db < target else -1
                self._sync_ends()
                self._over_anim.stop()
                self._set_over(math.copysign(
                    OVERSHOOT_MAX * NUDGE_STRETCH, -1 if db > target else 1))
                self._spring_back()
            self._run_clock()
        self._user_set_strength(target, nudge=True)

    def _glide_needle(self, target: float) -> None:
        """Glide the needle to tick `target`, flashing each tick as the
        needle (and the lit edge) passes it."""
        start = self._needle_pos.value
        if not ambient_ok() or not self.isVisible() or start == target:
            self._needle_pos.snap(target)
            return
        self._needle_pos.set_target(target)
        now = time.perf_counter()
        span = target - start
        lo, hi = sorted((start, target))
        first = max(0, math.floor(lo + 0.5) + 1)   # ticks that change
        for j in range(first, min(TICKS - 1, math.floor(hi + 0.5)) + 1):
            # Tick j changes when the needle crosses j - 0.5; find when on
            # the glide's OutCubic curve that happens.
            frac = _clamp((j - 0.5 - start) / span)
            u = 1.0 - (1.0 - frac) ** (1.0 / 3.0)
            self._trail[j] = now + u * NUDGE_GLIDE_MS / 1000.0
        self._run_clock()

    def _end_nudge(self) -> None:
        self._nudge.set_target(0.0, duration_ms=NUDGE_FADE_MS)
        if not self._dragging:
            self._drag_dir = 0
            self._sync_ends()

    def _nudging(self) -> bool:
        return self._nudge.value > 0.001

    def _trail_glow(self, i: int, now: float) -> float:
        """0..1 flash of tick i in the step trail."""
        stamp = self._trail.get(i)
        if stamp is None:
            return 0.0
        u = (now - stamp) * 1000.0 / TRAIL_MS
        if u < 0.0 or u >= 1.0:
            return 0.0
        if u < TRAIL_PEAK:
            return _ease_out(u / TRAIL_PEAK)
        return 1.0 - _ease_in_out((u - TRAIL_PEAK) / (1.0 - TRAIL_PEAK))

    # -- keyboard ------------------------------------------------------------------------
    def keyPressEvent(self, event):  # noqa: N802 (Qt override)
        key = event.key()
        step = {Qt.Key.Key_Right: -1, Qt.Key.Key_Up: -1,
                Qt.Key.Key_Left: 1, Qt.Key.Key_Down: 1,
                Qt.Key.Key_PageUp: -5, Qt.Key.Key_PageDown: 5}.get(key)
        if step is not None:
            self._nudge_to(self._strength_db + step)
            event.accept()
        elif key == Qt.Key.Key_Home:
            self._nudge_to(ATTEN_GENTLE)
            event.accept()
        elif key == Qt.Key.Key_End:
            self._nudge_to(ATTEN_STRONG)
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
        if u < 0 or not ambient_ok():
            return base, 1.0
        ms = u % COMET_LAP_MS
        if ms < COMET_FLASH_MS:
            v = ms / COMET_FLASH_MS
            return mix_rgba(col["comet"], col["gold"], v), 1.0 + 0.05 * (1 - v)
        if ms < COMET_TAIL_MS:
            return mix_rgba(col["gold"], base, (ms - COMET_FLASH_MS)
                            / (COMET_TAIL_MS - COMET_FLASH_MS)), 1.0
        return base, 1.0

    def _lit_look(self, i: int, col: dict, t: float, live_alpha=None):
        """(colour, alpha factor, radial scale) of lit tick i (live_alpha:
        _live_alpha(t), when already worked out)."""
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
            if live_alpha is None:
                live_alpha = self._live_alpha(t)
            return colour, live_alpha, scale
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

    def _live_alpha(self, t: float) -> float:
        """Live: the lit ticks' alpha, which brightens together with the
        disc's charge (breath: which breathes with the cycle)."""
        if breathing():
            return keyframes(
                breath_pos(t - self._ignite_end(), BREATH_MS), TICKS_LIVE)
        return 0.78 + 0.22 * self._charge(t)

    def _bloomed(self, t: float, lit: int) -> bool:
        """Breath: the live bloom has reached each of the `lit` ticks."""
        if lit <= 0:
            return True
        mid = self._bloom_mid()
        far = max(mid, lit - 1 - mid)
        return t >= far * BLOOM_STEP + BLOOM_MS

    def _ring_pulse(self, t: float, lit: int):
        """The alpha all `lit` lit ticks share now (the idle breath, the
        live one once the bloom is over, or the live charge), which
        _ring_strokes(lift) leaves out of them; None when they don't
        share one."""
        phase = self._phase
        if breathing():
            if phase == "idle":
                return self._idle_breath()
            if phase == "live" and self._bloomed(t, lit):
                return self._live_alpha(t)
            return None
        if phase == "live":
            return self._live_alpha(t)
        return None

    def _idle_breath(self) -> float:
        """Breath: the lit ticks' alpha while idle (a slow swell)."""
        if self._phase != "idle" or not ambient_ok():
            return 1.0
        return keyframes(breath_pos(time.perf_counter() * 1000.0,
                                    IDLE_BREATH_MS), TICKS_IDLE)

    def _breath_look(self, i: int, lit: int, col: dict, t: float,
                     idle: float = None, live_alpha: float = None):
        """Breath: (colour, alpha, radial scale, glow 0..1) of tick i;
        `idle` is the idle breath's alpha (None: _idle_breath's), and
        live_alpha _live_alpha(t), when already worked out."""
        if i >= lit:
            return col["unlit"], 1.0, 1.0, 0.0
        phase = self._phase
        mid = (lit - 1) / 2.0
        inward = max(0.0, mid - abs(i - mid))   # 0 at the ends of the arc
        if phase == "starting":
            # Light gathers from the ends of the lit arc inward, each lap.
            flash = 0.0
            u = t - inward * GATHER_STEP
            if u >= 0 and ambient_ok():
                ph = (u % GATHER_MS) / GATHER_MS
                if ph < GATHER_FLASH:
                    flash = 1.0 - _breath(ph / GATHER_FLASH)
            return mix_rgba(col["dim"], col["comet"], flash), 1.0, 1.0, flash
        if phase == "live":
            # Blooms from the middle out, then breathes with the cycle.
            u = (t - abs(i - self._bloom_mid()) * BLOOM_STEP) / BLOOM_MS
            if u < 0:
                colour, scale, glow = col["gold"], 1.0, GLOW_IDLE
            elif u < BLOOM_PEAK:
                v = _soft(u / BLOOM_PEAK)
                colour = mix_rgba(col["gold"], col["flash"], v)
                scale, glow = 1.0 + 0.03 * v, GLOW_IDLE + (1 - GLOW_IDLE) * v
            elif u < 1:
                v = _soft((u - BLOOM_PEAK) / (1 - BLOOM_PEAK))
                colour = mix_rgba(col["flash"], col["accent"], v)
                scale, glow = 1.03 - 0.03 * v, 1.0 - (1 - GLOW_LIVE) * v
            else:
                colour, scale, glow = col["accent"], 1.0, GLOW_LIVE
            if live_alpha is None:
                live_alpha = self._live_alpha(t)
            return colour, live_alpha, scale, glow
        if phase == "error":
            alpha = 1.0
            if t < 2 * ERROR_PULSE_MS:
                dim = math.sin(math.pi * t / ERROR_PULSE_MS) ** 2
                alpha = 1.0 - 0.55 * dim
            return col["error"], alpha, 1.0, GLOW_IDLE
        # Idle / stopping: gold, breathing slowly once settled; stopping
        # settles the ends back first.
        colour, glow = col["gold"], GLOW_IDLE
        if self._drain_at is not None:
            d = self._since(self._drain_at) - inward * SETTLE_STEP
            if d < SETTLE_MS:
                v = _breath(max(0.0, d) / SETTLE_MS)
                colour = mix_rgba(col["accent"], col["gold"], v)
                glow = GLOW_LIVE + (GLOW_IDLE - GLOW_LIVE) * v
        if phase != "idle":
            return colour, 1.0, 1.0, glow
        return (colour, self._idle_breath() if idle is None else idle, 1.0,
                glow)

    def _sweep_behind(self, i: int) -> float:
        """First show: how far (degrees) the entrance sweep's edge has
        passed tick i; negative before it gets there."""
        u = self._since(self._sweep_at) / self._sweep_ms()[1]
        if u >= 1.0:
            return 1e9
        if u < 0:
            return -1e9
        if breathing():
            edge = -16.0 + 316.0 * _ease_out(u)
        else:
            # Over the whole sweep, the crest settling out past the end.
            edge = (-SWEEP_FADE_DEG + (ARC_SPAN + SWEEP_FADE_DEG
                    + SWEEP_CREST_DEG) * _sweep_ease(u))
        return edge + SWEEP_FADE_DEG - ARC_SPAN * i / (TICKS - 1)

    def _sweep_visibility(self, i: int) -> float:
        """First show: how much of tick i the entrance sweep has drawn."""
        if self._sweep_at is None:
            return 1.0
        return _clamp(self._sweep_behind(i) / SWEEP_FADE_DEG)

    def _sweep_crest(self, i: int) -> float:
        """First show (tactile): how bright the crest leading the sweep
        is on tick i, 0..1. It peaks as the tick is fully drawn and fades
        over the next few ticks."""
        if self._sweep_at is None or breathing():
            return 0.0
        a = self._sweep_behind(i)
        if a <= 0.0 or a >= SWEEP_FADE_DEG + SWEEP_CREST_DEG:
            return 0.0
        if a < SWEEP_FADE_DEG:
            return a / SWEEP_FADE_DEG
        return 1.0 - _ease_out((a - SWEEP_FADE_DEG) / SWEEP_CREST_DEG)

    def _swell_px(self, angle: float, head_angle: float) -> float:
        """Lift of the ticks around the pointer (or the needle while it
        is dragged or stepped)."""
        nudge = self._nudge.value
        amount = self._swell.value * (1.0 - nudge)
        lift = 0.0
        if amount > 0.01:
            centre = head_angle if self._dragging else self._swell_angle
            d = abs(((angle - centre) + 180.0) % 360.0 - 180.0)
            lift = amount * SWELL_PX * math.exp(-(d / SWELL_DEG) ** 2)
        if nudge > 0.01:
            d = abs(((angle - head_angle) + 180.0) % 360.0 - 180.0)
            lift = max(lift, nudge * SWELL_PX
                       * math.exp(-(d / SWELL_DEG) ** 2))
        return lift

    def _needle(self, t: float):
        """(alpha, glow, radial scale) of the head needle."""
        live = self._phase == "live"
        if live and not self._dragging and breathing():
            # Rises with the disc's swell, glowing as it arrives.
            u = (t - (self._ignite_end() - SWELL_LEAD)) / BREATH_NEEDLE_MS
            alpha = _soft(_clamp(u / 0.45))
            glow = _rise_fall(u, 0.45)
        elif live and not self._dragging:
            u = (t - (self._ignite_end() - 60)) / NEEDLE_IN_MS
            alpha = _ease_out(u / 0.4)
            glow = _rise_fall(u, 0.4)
        elif self._phase in ("idle", "live"):
            alpha = 1.0 if (self._dragging or live) else max(
                self._hot_blend.value, self._nudge.value)
            glow = 0.0
        else:
            return 0.0, 0.0, 1.0
        scale = 1.0
        if (self._dragging or self._nudging()) and self._pluck_at is not None:
            span = PLUCK_BIG_MS if self._pluck_big else PLUCK_MS
            hit = _rise_fall(self._since(self._pluck_at) / span, 0.38)
            scale += (0.1 if self._pluck_big else 0.045) * hit
            if self._pluck_big:
                glow = max(glow, hit)
        return alpha, glow, scale

    def _pop_scale(self, t: float) -> float:
        if self._phase != "live":
            return 1.0
        if breathing():   # a slow swell as the bloom closes, not a pop
            u = (t - (self._ignite_end() - SWELL_LEAD)) / BREATH_SWELL_MS
            if u <= 0 or u >= 1:
                return 1.0
            if u < 0.4:
                return 1.0 + 0.04 * _soft(u / 0.4)
            return 1.04 - 0.04 * _soft((u - 0.4) / 0.6)
        u = (t - self._ignite_end()) / POP_MS
        if u < 0 or u >= 1:
            return 1.0
        if u < 0.3:
            return 1.0 - 0.1 * _ease_out(u / 0.3)
        return 0.9 + 0.1 * _back((u - 0.3) / 0.7)

    def _charge(self, t: float) -> float:
        """Live: 0..1 glow of the disc around each later lattice ping
        (after live: the glow it was left with, fading out)."""
        if not ambient_ok():
            return 0.0
        if self._phase != "live":
            u = self._since(self._charge_drop_at) / CHARGE_DROP_MS
            if self._charge_from <= 0.0 or u >= 1.0:
                return 0.0
            return self._charge_from * (1.0 - _ease_out(u))
        if breathing():
            # Full as each breath's pulse leaves, gone by an eighth of the
            # way, gathering again over the last quarter.
            level = keyframes(breath_pos(t - self._ignite_end(), BREATH_MS),
                              CHARGE)
            return max(0.0, level) * min(1.0, t / CHARGE_RAMP_MS)
        rel = t - self._ignite_end()
        k = max(1, round(rel / PING_PERIOD_MS))
        d = rel - k * PING_PERIOD_MS
        if -CHARGE_LEAD_MS <= d < 0:
            return _ease_in(1.0 + d / CHARGE_LEAD_MS)
        if 0 <= d < CHARGE_FADE_MS:
            return 1.0 - _ease_out(d / CHARGE_FADE_MS)
        return 0.0

    def _shake_px(self, t: float) -> float:
        if self._phase == "error" and breathing():
            if t >= TREMBLE_MS:
                return 0.0
            return keyframes(t / TREMBLE_MS, TREMBLE)
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
        if breathing() and phase in ("live", "stopping"):
            if phase == "live":
                u = (t - (self._ignite_end() - BREATH_GLYPH_LEAD)) \
                    / BREATH_GLYPH_MS
                return mix_rgba(col["gold"], col["accent"],
                                _breath(_clamp(u)))
            return mix_rgba(col["accent"], col["gold"],
                            _breath(_clamp(t / BREATH_GLYPH_MS)))
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
        if self._face_sink is not None:
            self.update()                 # drawn by the Home scene
            return
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
        if self._ring_sink is not None:
            self._ring_sink(self._over, self._ring_strokes(col, t, True),
                            self.ring_breath(t))
        else:
            self._paint_ring(p, col, t)
        self._paint_core(p, col, t)
        self._paint_readout(p, col)
        p.end()

    # -- the ring drawn elsewhere ---------------------------------------------------
    def set_ring_sink(self, sink) -> None:
        """Hand the ring to `sink(over, strokes, breath)` instead of
        painting it (see ring_frame): the GPU sky behind the dial draws
        its ticks and needle under the disc. None paints them here again.
        """
        self._ring_sink = sink
        self.update()

    def set_face_sink(self, sink) -> None:
        """Hand the whole look to `sink(face_state())`, with the ring to
        the ring sink, instead of painting (the Home scene draws it: see
        widgets/home_scene.py): each repaint asked for becomes one push
        of both, at most one per pass of the event loop; sink(None) while
        the dial itself is hidden. None paints here again. Breathing themes
        only (face_state draws their dial)."""
        self._face_sink = sink
        self._push_timer.stop()
        if sink is None:
            super().update()
        else:
            self._push_face()

    def update(self, *args):
        """Repaint, or with a face sink push the next look to it."""
        if self._face_sink is None:
            super().update(*args)
        elif not self._push_timer.isActive():
            self._push_timer.start()

    def _push_face(self) -> None:
        self._push_timer.stop()
        sink = self._face_sink
        if sink is None:
            return
        if self.isHidden():               # (not its page: see mirror_text)
            sink(None)
            return
        t = self._ms()
        col = self._colours(current_theme())
        if self._ring_sink is not None:
            self._ring_sink(self._over, self._ring_strokes(col, t, True),
                            self.ring_breath(t))
        sink(self.face_state(col, t))

    def face_state(self, col=None, t=None) -> dict:
        """The dial at this moment but for its ring, as the Home scene
        draws it (assets/sky/HomeDial.qml's properties and disc.frag's
        uniforms): what _paint_core and _paint_readout paint for a
        breathing theme. Colours are QColors."""
        if col is None:
            col = self._colours(current_theme())
        if t is None:
            t = self._ms()
        live = self._phase == "live"
        press = max(0.0, min(1.0, self._press))
        scale = (1.0 - 0.07 * press) * self._pop_scale(t)
        hot = self._disc_hot.value
        accent = col["accent"]
        tint = QColor(accent if live else col["gold"])
        tint.setAlphaF(0.45)
        edge = QColor(accent)
        edge.setAlphaF(0.2)
        focus = QColor(col["focus"])
        if not (self._key_focus and self.hasFocus()):
            focus.setAlpha(0)
        k = min(self.width(), self.height()) / REF
        dpr = self.devicePixelRatioF()

        labels, dots = [], []
        mist = self._label_mist.value
        leaving = 1.0 - _clamp(mist / 0.6)
        arriving = _clamp((mist - 0.35) / 0.65)
        for index, alpha in ((self._label_from, leaving),
                             (self._label_to, arriving)):
            if alpha <= 0.01:
                continue
            if index == 1:
                dots = [list(look) for look in
                        self._dot_looks(col, t, 186.0, alpha)]
            else:
                labels.append([LABELS[index],
                               col["error"] if index == 3 else col["text"],
                               alpha])

        minus_x, digits, unit_x, bump = self._readout_breath_layout()
        gentle, strong = self._gentle_hot.value, self._strong_hot.value
        return {
            # The disc (disc.frag).
            "faceTop": col["pill"].lighter(132 + int(10 * hot)),
            "faceMid": col["pill"].lighter(100 + int(8 * hot)),
            "faceEdge": mix_rgba(edge, tint, hot),
            "accentRgb": accent, "rimRgb": col["focus"],
            "charge": min(1.0, self._charge(t)),
            "focusRgba": focus,
            "glyphRgba": self._glyph_colour(col, t),
            "stem": 3.0 * press - 1.5 * hot,
            "unit": 1.0 / max(1e-6, k * dpr * scale),
            # The rest (HomeDial.qml).
            "coreScale": scale, "shake": self._shake_px(t),
            "labelFont": self._heading(20, 114.0),
            "bigFont": self._heading(30, 104.0),
            "smallFont": self._small_font(),
            "labels": labels, "dots": dots,
            "digits": [[text, x, alpha, SMOKE_PX * smoke_spread(1.0 - alpha)]
                       for text, x, alpha in digits],
            "minusX": minus_x, "unitX": unit_x, "bump": bump,
            "textColour": col["text"], "captionColour": col["muted"],
            "gentleColour": mix_rgba(col["muted"], col["text"], gentle),
            "gentleX": 52.0 - 3.0 * gentle,
            "strongColour": mix_rgba(col["muted"], col["text"], strong),
            "strongX": 248.0 + 3.0 * strong,
        }

    def ring_frame(self):
        """(stretch in degrees, strokes, breath): the ring at this moment
        as the sink gets it, the strokes as _ring_strokes(lift_breath)
        gives them and the shared alpha for those it marks."""
        t = self._ms()
        return (self._over,
                self._ring_strokes(self._colours(current_theme()), t, True),
                self.ring_breath(t))

    def ring_breath(self, t: float = None) -> float:
        """The alpha the lit ticks share now (see _ring_pulse), for the
        strokes _ring_strokes(lift_breath) marks: all that moves in the
        ring while the dial's clock rests (the card sends it with each
        sky frame)."""
        if t is None:
            t = self._ms()
        pulse = self._ring_pulse(t, self._lit_now())
        return 1.0 if pulse is None else pulse

    def _lit_now(self) -> int:
        """How many ticks are lit (they follow the needle's glide)."""
        pos = max(-1.0, min(TICKS - 1.0, self._needle_pos.value))
        return max(0, min(TICKS, math.floor(pos + 0.5) + 1))

    def ring_animating(self) -> bool:
        """The dial's own clock runs (and hands the ring on each paint)."""
        return self._clock.isActive()

    def _paint_ring(self, p, col, t) -> None:
        """The ticks and the head needle, from images redrawn only when a
        stroke changes: these strokes are most of what the dial costs,
        and it repaints with every frame of what moves behind it. The
        alpha the lit ticks share (the breath, the live charge) is left
        out of them and drawn as the opacity of their own two images
        (glows, then ticks: neither overlaps its own kind), so a pulse
        redraws nothing. The rest (unlit ticks, the needle) goes on top."""
        w, h = self.width(), self.height()
        dpr = self.devicePixelRatioF()
        strokes = self._ring_strokes(col, t, True)
        pulse = self.ring_breath(t)
        layers = (
            (tuple(s for s in strokes if s[6] and s[5] % 2 == 0), pulse),
            (tuple(s for s in strokes if s[6] and s[5] % 2 == 1), pulse),
            (tuple(s for s in strokes if not s[6]), 1.0),
        )
        key = (w, h, dpr, self._over)
        if key != self._ring_key:
            self._ring_key = key
            self._ring = {}                # layer -> (strokes, image)
        p.save()
        p.resetTransform()
        for index, (group, opacity) in enumerate(layers):
            if not group:
                continue
            shown = self._ring.get(index)
            if shown is None or shown[0] != group:
                shown = (group, self._draw_ring(
                    w, h, dpr, group, shown[1] if shown else None))
                self._ring[index] = shown
            if opacity > 0.5 / 255:
                p.setOpacity(opacity)
                p.drawImage(QPointF(0, 0), shown[1])
        p.restore()

    def _draw_ring(self, w, h, dpr, strokes, image=None) -> QImage:
        """The strokes, painted as paintEvent would, into a transparent
        image the widget's size (`image` reused when it fits)."""
        size = (math.ceil(w * dpr), math.ceil(h * dpr))
        if (image is None or (image.width(), image.height()) != size
                or image.devicePixelRatio() != dpr):
            image = QImage(*size, QImage.Format.Format_ARGB32_Premultiplied)
            image.setDevicePixelRatio(dpr)
        image.fill(Qt.GlobalColor.transparent)
        k = min(w, h) / REF
        c = REF / 2
        p = QPainter(image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(w / 2, h / 2)
        p.scale(k, k)
        p.rotate(self._over)          # stretched past an end
        p.translate(-c, -c)
        for angle, r0, r1, rgba, width, _, _ in strokes:
            self._line(p, angle, r0, r1, QColor.fromRgba(rgba), width)
        p.end()
        return image

    def _ring_strokes(self, col, t, lift_breath: bool = False) -> tuple:
        """The ticks (lit ones show the strength) and the head needle, as
        the strokes that draw them, in order: (angle, r0, r1, rgba, width,
        slot, breathes). Slot 2i is tick i's glow and 2i + 1 the tick;
        2 x TICKS is the needle's glow and the one after it the needle.
        lift_breath leaves the alpha the lit ticks share (_ring_pulse: the
        breath, the live charge) out of the strokes it would only scale,
        marking them `breathes`: they hold still while it moves, and
        whoever draws them scales them by ring_breath."""
        # The needle (and the lit edge) follow its glide on wheel steps.
        pos = max(-1.0, min(TICKS - 1.0, self._needle_pos.value))
        lit = max(0, min(TICKS, math.floor(pos + 0.5) + 1))
        head_angle = ARC_START + ARC_SPAN * max(0.0, pos) / (TICKS - 1)
        now = time.perf_counter()
        breath = breathing()
        idle = self._idle_breath()
        pulse = self._ring_pulse(t, lit) if lift_breath else None
        live_alpha = self._live_alpha(t) if self._phase == "live" else None
        # Worked out once, not per tick: the entrance sweep (over after
        # the first show) and the lift around the pointer (rarely on).
        sweeping = self._sweep_at is not None and self._sweeping()
        swelling = (self._swell.value * (1.0 - self._nudge.value) > 0.01
                    or self._nudge.value > 0.01)
        strokes = []
        for i in range(TICKS):
            visible = self._sweep_visibility(i) if sweeping else 1.0
            if visible <= 0.0:
                continue
            angle, r_in, r_out = tick_geometry(i)
            glow = 0.0
            breathes = pulse is not None and i < lit
            if breath:
                colour, alpha, scale, glow = self._breath_look(
                    i, lit, col, t, 1.0 if breathes else idle, live_alpha)
                if breathes:
                    alpha = 1.0
            elif i < lit:
                colour, alpha, scale = self._lit_look(i, col, t, live_alpha)
                if breathes:
                    alpha = 1.0
            elif self._phase == "starting":
                colour, scale = self._comet_look(i, col["unlit"], col, t)
                alpha = 1.0
            else:
                colour, alpha, scale = col["unlit"], 1.0, 1.0
            crest = self._sweep_crest(i) if sweeping else 0.0
            if crest > 0.0:   # first show: the crest leading the sweep
                colour = mix_rgba(colour, col["comet"], 0.85 * crest)
                scale = max(scale, 1.0 + 0.04 * crest)
            lift = self._swell_px(angle, head_angle) if swelling else 0.0
            if glow > 0.01:           # breath: lit ticks glow softly
                halo = QColor(colour)
                halo.setAlphaF(GLOW_ALPHA * glow * alpha * visible)
                strokes.append((angle, (r_in + lift - 1.5) * scale,
                                (r_out + lift + 1.5) * scale, halo.rgba(),
                                10.0, 2 * i, breathes))
            flash = self._trail_glow(i, now) if self._trail else 0.0
            if flash > 0.0:   # passed by a stepped needle: a comet flash
                tone = col["flash"] if self._phase == "live" else col["comet"]
                colour = mix_rgba(colour, tone, 0.85 * flash)
                if breathes:   # max() does not scale: the pulse goes in
                    alpha, breathes = pulse, False
                alpha = max(alpha, flash)
                scale = max(scale, 1.0 + 0.05 * flash)
            colour = QColor(colour)
            colour.setAlphaF(colour.alphaF() * alpha * visible)
            strokes.append((angle, (r_in + lift) * scale,
                            (r_out + lift) * scale, colour.rgba(), 4.0,
                            2 * i + 1, breathes))

        # The head needle: white over the last lit tick.
        if lit > 0:
            alpha, glow, scale = self._needle(t)
            alpha *= self._sweep_visibility(lit - 1)
            if alpha > 0.01:
                # Between ticks (mid-glide) its length blends theirs.
                below = max(0, min(TICKS - 1, math.floor(pos)))
                above = min(TICKS - 1, below + 1)
                mix = _clamp(pos - below)
                r_in = (tick_geometry(below)[1] * (1 - mix)
                        + tick_geometry(above)[1] * mix)
                r_out = R_OUT
                lift = self._swell_px(head_angle, head_angle)
                r0, r1 = (r_in + lift) * scale, (r_out + lift) * scale
                halo = QColor(col["white"])
                halo.setAlphaF(alpha * (0.12 + 0.4 * glow))
                strokes.append((head_angle, r0, r1, halo.rgba(),
                                8.0 + 8.0 * glow, 2 * TICKS, False))
                needle = QColor(col["text"])
                needle.setAlphaF(alpha)
                strokes.append((head_angle, r0, r1, needle.rgba(), 5.0,
                                2 * TICKS + 1, False))
        return tuple(strokes)

    def _paint_core(self, p, col, t) -> None:
        """Ripple, disc, charge glow, power glyph and the rolling label."""
        c = REF / 2
        live = self._phase == "live"
        breath = breathing()

        # The ripple leaving the disc as the live sweep closes (breath:
        # the sky's halos do this, see widgets/sky.py).
        if live and not breath:
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
        hot = self._disc_hot.value
        paint = self._paint_disc_breath if breath else self._paint_disc
        if scale == 1.0 and self._shake_px(t) == 0.0:
            self._paint_disc_cached(p, col, charge, hot, paint)
        else:                     # pressed, popping or shaking: as it moves
            paint(p, col, charge, hot)
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

        if breath:
            self._paint_label_breath(p, col, t)
        else:
            self._paint_label(p, col, t)
        p.restore()

    def _paint_disc_cached(self, p, col, charge, hot, paint) -> None:
        """The disc at rest (no press, pop or shake), from an image per
        part (see DISC_PARTS), each redrawn only when it changes. The
        parts the charge lights are drawn at full charge and shown at the
        charge as their opacity, so a pulse redraws nothing."""
        w, h = self.width(), self.height()
        dpr = self.devicePixelRatioF()
        k = min(w, h) / REF
        c = REF / 2
        tones = tuple(colour.rgba() for colour in col.values())
        shown = self._disc_parts
        p.save()
        p.resetTransform()
        for part, reach in DISC_PARTS:
            face = part == "face"
            if not face and charge <= 0.01:
                continue
            key = (paint.__name__, w, h, dpr, tones) + (
                (self._phase == "live", hot) if face else ())
            entry = shown.get(part)
            if entry is None or entry[0] != key:
                # Device pixels around the part, whole ones, so the image
                # lands on the pixels it was drawn for.
                half = reach * k + 2.0
                x0 = math.floor((w / 2 - half) * dpr)
                y0 = math.floor((h / 2 - half) * dpr)
                size = math.ceil(2 * half * dpr) + 2
                image = QImage(size, size,
                               QImage.Format.Format_ARGB32_Premultiplied)
                image.setDevicePixelRatio(dpr)
                image.fill(Qt.GlobalColor.transparent)
                q = QPainter(image)
                q.setRenderHint(QPainter.RenderHint.Antialiasing)
                q.translate(w / 2 - x0 / dpr, h / 2 - y0 / dpr)
                q.scale(k, k)
                q.translate(-c, -c)
                paint(q, col, 1.0, hot, (part,))
                q.end()
                entry = (key, image, QPointF(x0 / dpr, y0 / dpr))
                shown[part] = entry
            p.setOpacity(1.0 if face else min(1.0, charge))
            p.drawImage(entry[2], entry[1])
        p.restore()

    def _paint_disc(self, p, col, charge, hot,
                    parts=("glow", "face", "inner", "rim")) -> None:
        """The disc, and its charge before each ping (only `parts`)."""
        c = REF / 2
        live = self._phase == "live"
        if charge > 0.01 and "glow" in parts:   # soft light outside the rim
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
        if "face" in parts:
            tint = QColor(col["accent"] if live else col["gold"])
            tint.setAlphaF(0.45)
            p.setPen(QPen(mix_rgba(col["groove"], tint, hot), 2.0))
            p.setBrush(col["pill"].lighter(100 + int(8 * hot)))
            p.drawEllipse(QPointF(c, c), DISC_R, DISC_R)
        if charge > 0.01 and "inner" in parts:   # glow inside the rim
            inner = QRadialGradient(QPointF(c, c), DISC_R)
            edge, clear = QColor(col["accent"]), QColor(col["accent"])
            edge.setAlphaF(0.3 * charge)
            clear.setAlphaF(0.0)
            inner.setColorAt(0.62, clear)
            inner.setColorAt(1.0, edge)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(inner)
            p.drawEllipse(QPointF(c, c), DISC_R - 1, DISC_R - 1)
        if charge > 0.01 and "rim" in parts:     # and the rim itself
            rim = QColor(col["accent"])
            rim.setAlphaF(0.9 * charge)
            p.setPen(QPen(rim, 2.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(c, c), DISC_R - 0.5, DISC_R - 0.5)

    def _paint_disc_breath(self, p, col, charge, hot,
                           parts=("glow", "face", "inner", "rim")) -> None:
        """Breath: a deeper disc whose glow (inside and out) and rim
        gather before each pulse and fade with it (only `parts`)."""
        c = REF / 2
        centre = QPointF(c, c)
        live = self._phase == "live"
        accent = col["accent"]
        p.setPen(Qt.PenStyle.NoPen)
        if charge > 0.01 and "glow" in parts:   # light around the disc
            glow = QRadialGradient(centre, DISC_R + 34)
            glow.setColorAt(DISC_R / (DISC_R + 34),
                            self._tone(accent, 0.26 * charge))
            glow.setColorAt(1.0, self._tone(accent, 0.0))
            p.setBrush(glow)
            p.drawEllipse(centre, DISC_R + 34, DISC_R + 34)
        if "face" in parts:
            tint = QColor(accent if live else col["gold"])
            tint.setAlphaF(0.45)
            edge = QColor(accent)
            edge.setAlphaF(0.2)
            face = QRadialGradient(QPointF(c, c - 0.1 * DISC_R), DISC_R)
            face.setColorAt(0.0, col["pill"].lighter(132 + int(10 * hot)))
            face.setColorAt(0.7, col["pill"].lighter(100 + int(8 * hot)))
            p.setPen(QPen(mix_rgba(edge, tint, hot), 1.5))
            p.setBrush(face)
            p.drawEllipse(centre, DISC_R, DISC_R)
        p.setPen(Qt.PenStyle.NoPen)
        if charge > 0.01 and "inner" in parts:   # glow inside the disc
            inner = QRadialGradient(centre, DISC_R)
            inner.setColorAt(0.5, self._tone(accent, 0.0))
            inner.setColorAt(1.0, self._tone(accent, 0.34 * charge))
            p.setBrush(inner)
            p.drawEllipse(centre, DISC_R - 0.75, DISC_R - 0.75)
        if charge > 0.01 and "rim" in parts:     # and the rim's band
            band = QRadialGradient(centre, DISC_R)
            band.setColorAt((DISC_R - 7) / DISC_R,
                            self._tone(col["focus"], 0.0))
            band.setColorAt((DISC_R - 1) / DISC_R,
                            self._tone(col["focus"], 0.8 * charge))
            band.setColorAt(1.0, self._tone(col["focus"], 0.8 * charge))
            p.setBrush(band)
            p.drawEllipse(centre, DISC_R, DISC_R)

    @staticmethod
    def _tone(colour: QColor, alpha: float) -> QColor:
        c = QColor(colour)
        c.setAlphaF(max(0.0, min(1.0, alpha)))
        return c

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

    @staticmethod
    def _heading(size: int, letter_spacing: float = 100.0) -> QFont:
        """Breath: the lighter, widely tracked heading face."""
        font = QFont(heading_family())
        font.setPixelSize(size)
        font.setWeight(QFont.Weight.DemiBold)
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing,
                              letter_spacing)
        return font

    def _misted_text(self, p, text, cx, baseline, font, colour,
                     alpha: float, right: float = None) -> None:
        """Text that mists in and out: as it fades it also softens (drawn
        a few times, slightly spread), the CSS blur's stand-in. Centred on
        cx, or right-aligned to `right`."""
        if alpha <= 0.01:
            return
        width = QFontMetricsF(font).horizontalAdvance(text)
        x = right - width if right is not None else cx - width / 2
        p.setFont(font)
        blur = 1.0 - alpha
        if blur < 0.05:
            p.setPen(self._tone(colour, colour.alphaF() * alpha))
            p.drawText(QPointF(x, baseline), text)
            return
        spread = 3.5 * blur
        p.setPen(self._tone(colour, colour.alphaF() * alpha
                            * (1.0 - 0.6 * blur)))
        p.drawText(QPointF(x, baseline), text)
        p.setPen(self._tone(colour, colour.alphaF() * alpha * 0.1 * blur))
        for k in range(8):
            a = k * math.pi / 4
            p.drawText(QPointF(x + spread * math.cos(a),
                               baseline + spread * math.sin(a)), text)

    def _paint_label_breath(self, p, col, t) -> None:
        """Breath: the old label mists away as the new one surfaces."""
        c = REF / 2
        head = self._heading(20, 114.0)
        mist = self._label_mist.value
        # The old one is mostly gone before the new one surfaces, so the
        # two never read on top of each other.
        leaving = 1.0 - _clamp(mist / 0.6)
        arriving = _clamp((mist - 0.35) / 0.65)
        for index, alpha in ((self._label_from, leaving),
                             (self._label_to, arriving)):
            if alpha <= 0.01:
                continue
            if index == 1:
                self._paint_dots(p, col, t, 186.0, alpha)
            else:
                colour = col["error"] if index == 3 else col["text"]
                self._misted_text(p, LABELS[index], c, 193.0, head, colour,
                                  alpha)

    def _paint_dots(self, p, col, t, cy, fade: float = 1.0) -> None:
        """The "..." label (see _dot_looks)."""
        p.setPen(Qt.PenStyle.NoPen)
        for x, y, r, colour, glow_r, glow in self._dot_looks(col, t, cy,
                                                              fade):
            if glow_r > 0.0:   # its glow at the top of the breath
                p.setBrush(glow)
                p.drawEllipse(QPointF(x, y), glow_r, glow_r)
            p.setBrush(colour)
            p.drawEllipse(QPointF(x, y), r, r)

    def _dot_looks(self, col, t, cy, fade: float = 1.0) -> list:
        """The "..." label's dots: lit in step with the comet while
        starting, settling right to left while stopping. (Breath: they
        breathe a beat apart, then settle.) As (x, y, r, colour, glow r
        (0: none), glow colour) each."""
        c = REF / 2
        breath = breathing()
        looks = []
        for j in range(3):
            colour, alpha, lift, scale = QColor(col["text"]), 0.35, 0.0, 1.0
            glow_r, glow = 0.0, QColor(0, 0, 0, 0)
            if breath and self._phase == "starting" and ambient_ok():
                colour, alpha, scale = QColor(col["gold"]), 0.25, 0.8
                u = t - j * DOT_BREATH_STEP
                if u >= 0:
                    ph = breath_pos(u, GATHER_MS)
                    v = (_breath(ph / 0.35) if ph < 0.35
                         else 1.0 - _breath((ph - 0.35) / 0.65))
                    alpha, scale = 0.25 + 0.75 * v, 0.8 + 0.4 * v
                    if v > 0.01:
                        glow = self._tone(col["gold"], 0.3 * v * fade)
                        glow_r = 6.0 * scale
            elif breath and self._phase == "stopping":
                q = _breath(_clamp((t - j * DOT_SETTLE_STEP) / DOT_SETTLE_MS))
                colour = mix_rgba(col["accent"], col["gold"], q)
                alpha, scale = 1.0 - 0.75 * q, 1.0 - 0.3 * q
            elif self._phase == "starting" and ambient_ok():
                colour, alpha = QColor(col["gold"]), 0.3
                u = t - j * DOT_STEP
                if u >= 0:
                    ms = u % COMET_LAP_MS
                    if ms < DOT_LIFT_MS:
                        v = ms / DOT_LIFT_MS
                        lift, scale = -4.0 * (1 - v), 1.25 - 0.25 * v
                        if ms < DOT_FLASH_MS:
                            colour = mix_rgba(col["comet"], col["gold"],
                                              ms / DOT_FLASH_MS)
                            alpha = 1.0
                        else:
                            alpha = 1.0 - 0.7 * ((ms - DOT_FLASH_MS)
                                                 / (DOT_LIFT_MS - DOT_FLASH_MS))
            elif self._phase == "stopping":
                q = _ease_in((t - (2 - j) * 110) / DOTS_OUT_MS)
                colour = mix_rgba(col["accent"], col["gold"], q)
                alpha, lift, scale = 1.0 - 0.75 * q, 3.0 * q, 1.0 - 0.3 * q
            colour.setAlphaF(colour.alphaF() * alpha * fade)
            looks.append((c + (j - 1) * 13.0, cy + lift, 3.0 * scale,
                          colour, glow_r, glow))
        return looks

    def _paint_readout(self, p, col) -> None:
        """"-50 dB" with rolling digits, its caption and the end labels."""
        if breathing():
            self._paint_readout_breath(p, col)
        else:
            self._paint_digits(p, col)
        c = REF / 2
        small = self._small_font()
        self._centered_text(p, "reduction strength", c, 294.0, small,
                            col["muted"])
        for label, x, blend, shift in (
                ("gentle", 52.0, self._gentle_hot, -3.0),
                ("strong", 248.0, self._strong_hot, 3.0)):
            tone = mix_rgba(col["muted"], col["text"], blend.value)
            self._centered_text(p, label, x + shift * blend.value, 278.0,
                                small, tone)

    def _small_font(self) -> QFont:
        """The caption's and the end labels' face."""
        small = QFont(self.font())
        small.setPixelSize(12)
        return small

    def _readout_breath_layout(self):
        """Breath: (the minus's x, [(digit, x, alpha)] for each digit
        shown, misting ones too, "dB"'s x, the bump's scale)."""
        c = REF / 2
        metrics = QFontMetricsF(self._heading(30, 104.0))
        minus_w = metrics.horizontalAdvance("-")
        digit_w = max(metrics.horizontalAdvance(str(d)) for d in range(10))
        unit_w = metrics.horizontalAdvance("dB")
        gap = 7.0
        minus_x = c - (minus_w + 2 * digit_w + gap + unit_w) / 2
        x = minus_x + minus_w
        now = time.perf_counter()
        digits = []
        for column in self._mists:
            for digit, entry in sorted(column.items()):
                text = str(digit)
                left = x + (digit_w - metrics.horizontalAdvance(text)) / 2
                digits.append((text, left, self._mist_alpha(entry, now)))
            x += digit_w
        bump = _rise_fall(self._since(self._bump_at) / BUMP_MS, 0.4)
        return minus_x, digits, x + gap, 1.0 + 0.04 * bump

    def _paint_readout_breath(self, p, col) -> None:
        """Breath: each digit that changes dissolves like smoke as the
        next condenses in its place (no roll, no drift)."""
        c = REF / 2
        big = self._heading(30, 104.0)
        baseline = 276.0
        minus_x, digits, unit_x, bump = self._readout_breath_layout()
        p.save()
        if bump > 1.0:
            p.translate(c, baseline - 11)
            p.scale(bump, bump)
            p.translate(-c, -(baseline - 11))
        p.setFont(big)
        p.setPen(col["text"])
        p.drawText(QPointF(minus_x, baseline), "-")
        for text, left, alpha in digits:
            self._smoked_text(p, text, left, baseline, big, col["text"],
                              alpha)
        p.setFont(big)
        p.setPen(col["text"])
        p.drawText(QPointF(unit_x, baseline), "dB")
        p.restore()

    def _smoked_text(self, p, text, x, baseline, font, colour,
                     alpha: float) -> None:
        """Text that dissolves like smoke as it fades (and condenses as it
        returns) in place: see smoke_wisps."""
        if alpha <= 0.01:
            return
        p.setFont(font)
        base = colour.alphaF() * alpha
        smoke = 1.0 - alpha
        if smoke < 0.03:
            p.setPen(self._tone(colour, base))
            p.drawText(QPointF(x, baseline), text)
            return
        core, wisps = smoke_wisps(smoke, SMOKE_PX)
        p.setPen(self._tone(colour, base * core))
        p.drawText(QPointF(x, baseline), text)
        for weight, dx, dy in wisps:
            p.setPen(self._tone(colour, base * weight))
            p.drawText(QPointF(x + dx, baseline + dy), text)

    def _paint_digits(self, p, col) -> None:
        """"-50 dB" with odometer digits."""
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
