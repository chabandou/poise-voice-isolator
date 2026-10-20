"""
Poise Voice Isolator - Apple-style animation helpers.

Small, dependency-free micro-interaction toolkit for Qt Widgets:

- fade / staggered entrance (opacity only — safe inside layouts)
- Hyprland-style directional page transitions for QStackedWidget
  (snapshot slide-out + slide-in, no cascade)
- press-fade filter for standard QPushButtons (no layout churn)
- looping pulse (status dot / live indicator)
- Blend: an eased 0..1 state value (hover / checked / lit) for painted widgets
- QssHoverFade: crossfades QSS :hover colours on stock buttons and fields
- crossfade_from: fades a snapshot of the old look away (theme switches)
- TextSwap: fades a label's old text out and the new one in (status lines)
- shared Apple-like timings + easings

QSS cannot animate, so all motion lives here in code. Every helper
respects reduced motion via POISE_NO_ANIM=1 / POISE_REDUCE_MOTION=1
and degrades to an instant state change. Reduce motion in Settings holds
only the ambient motion still (ambient_ok).

Safety rules (learned the hard way):
- NEVER put a QGraphicsOpacityEffect on a QScrollArea, a QStackedWidget
  page, or any scrollable/viewport widget: it corrupts painting (blank
  pages + "QPainter not active" spam). Only fade simple leaf widgets
  (QFrame cards, labels, snapshot overlays) and remove the effect when
  the fade completes so no permanent effect lingers to slow repaints.
- NEVER nest fades: at most one animation owns a widget's effect at a
  time (tracked via widget._apple_fade); a new fade stops the old one.
- Delayed starts carry a generation counter so a stale timer from a
  previous page visit can never blank a widget out from under the user.

Page transitions mirror the compositor (see ~/.config/hypr/looknfeel.conf):
    animation = workspaces, 1, 5, overshot, slidefadevert 30%
    bezier = overshot, 0.05, 0.9, 0.1, 1.05
i.e. vertical slide over 30% of the height + fade, 500ms (speed =
deciseconds per the Hyprland wiki), on the overshot spring curve.

Usage:
    from .animations import fade_in, stagger_in, slide_stack
    fade_in(card)
    slide_stack(self.stack, index)
"""

import math
import os
import time
import weakref

from PyQt6 import sip
from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPointF,
    QPropertyAnimation,
    Qt,
    QTimer,
    QVariantAnimation,
    pyqtSignal,
)
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractButton,
    QGraphicsOpacityEffect,
    QStackedWidget,
    QWidget,
)

# -- Apple-like motion tokens -------------------------------------------------
# Human Interface Guidelines feel: fast (120-250ms), ease-out, subtle.
# OutCubic for entrances/fades, OutBack (low overshoot) for pops/springs,
# InOutSine for infinite breathing loops.
D_IN = 120          # press down / hover
D_OUT = 180         # release / fade
D_PAGE = 200        # page cross-fade
D_POP = 280         # success pop
D_BREATHE = 1600    # glow breathing loop

EASE_OUT = QEasingCurve.Type.OutCubic
EASE_SPRING = QEasingCurve.Type.OutBack
EASE_BREATHE = QEasingCurve.Type.InOutSine

PRESS_OPACITY = 0.62  # QPushButton dip while held

# -- Hyprland workspace transition ---------------------------------------------
# Mirrors ~/.config/hypr/looknfeel.conf:
#     animation = workspaces, 1, 5, overshot, slidefadevert 30%
#     bezier = overshot, 0.05, 0.9, 0.1, 1.05
# Hyprland SPEED is deciseconds (1ds = 100ms), so speed 5 == 500ms, and the
# 30% in slidefadevert is the travel distance as a fraction of the height.
WS_BEZIER = (0.05, 0.9, 0.1, 1.05)  # overshot spring curve
WS_MS = 5 * 100                     # speed 5 -> 500ms
WS_TRAVEL = 0.30                    # slidefadevert 30% of stack height


def cubic_bezier_fn(x1: float, y1: float, x2: float, y2: float):
    """CSS/Hyprland cubic-bezier easing as a plain progress->value function.

    Pure Python (no Qt) so it stays unit-testable. Solves x(t) = progress
    with Newton iterations + bisection fallback, then returns y(t).
    Overshooting curves (y > 1) are preserved — callers clamp if needed.
    """
    cx = 3.0 * x1
    bx = 3.0 * (x2 - x1) - cx
    ax = 1.0 - cx - bx
    cy = 3.0 * y1
    by = 3.0 * (y2 - y1) - cy
    ay = 1.0 - cy - by

    def _sample_x(t: float) -> float:
        return ((ax * t + bx) * t + cx) * t

    def _sample_y(t: float) -> float:
        return ((ay * t + by) * t + cy) * t

    ax3, bx2 = 3.0 * ax, 2.0 * bx

    def fn(progress: float) -> float:
        if progress <= 0.0:
            return 0.0
        if progress >= 1.0:
            return 1.0
        # Newton iterations (the samples written out: the night sky asks
        # for over a hundred of these a frame; same sums, same results).
        t = progress
        for _ in range(8):
            err = ((ax * t + bx) * t + cx) * t - progress
            if -1e-6 < err < 1e-6:
                return ((ay * t + by) * t + cy) * t
            d = (ax3 * t + bx2) * t + cx
            if -1e-6 < d < 1e-6:
                break
            t -= err / d
        # Bisection fallback.
        lo, hi, t = 0.0, 1.0, progress
        while lo < hi:
            x = _sample_x(t)
            if abs(x - progress) < 1e-6:
                return _sample_y(t)
            if progress > x:
                lo = t
            else:
                hi = t
            t = (hi - lo) * 0.5 + lo
        return _sample_y(t)

    return fn


_WS_CURVE = None
_WS_FADE_CURVE = None


def _hypr_curve(clamp: bool = False) -> QEasingCurve:
    """The compositor's overshot curve as a QEasingCurve (cached).

    With clamp=True the output is pinned to [0, 1] for opacity tracks
    (an overshooting opacity goes negative and flashes).
    """
    global _WS_CURVE, _WS_FADE_CURVE
    if not clamp and _WS_CURVE is not None:
        return _WS_CURVE
    if clamp and _WS_FADE_CURVE is not None:
        return _WS_FADE_CURVE
    x1, y1, x2, y2 = WS_BEZIER
    try:
        fn = cubic_bezier_fn(x1, y1, x2, y2)
        if clamp:
            raw = fn

            def fn(p: float) -> float:  # noqa: F811 (intentional wrap)
                return max(0.0, min(1.0, raw(p)))

        curve = QEasingCurve(QEasingCurve.Type.Linear)
        curve.setCustomType(fn)
        # Sanity-check the binding actually honors custom functions.
        if abs(curve.valueForProgress(0.0)) > 1e-6:
            raise ValueError("custom easing not honored")
    except Exception:
        curve = QEasingCurve(EASE_OUT)
    if clamp:
        _WS_FADE_CURVE = curve
    else:
        _WS_CURVE = curve
    return curve


def _reduced_by_env() -> bool:
    return (os.environ.get("POISE_NO_ANIM") == "1"
            or os.environ.get("POISE_REDUCE_MOTION") == "1")


# Read once: the flags are set before Poise starts, and its animations
# ask well over a thousand times a second. LIVE_ENV reads them on every
# call instead (the tests switch them while running; see conftest).
_REDUCED_BY_ENV = _reduced_by_env()
LIVE_ENV = False


def motion_ok() -> bool:
    """False when the user asked for reduced motion (env override)."""
    if LIVE_ENV:
        return not _reduced_by_env()
    return not _REDUCED_BY_ENV


# The Settings page's "Reduce motion" (see set_still).
_still = False


def set_still(still: bool) -> None:
    """Hold the ambient motion still (the Settings page's Reduce motion):
    see ambient_ok. Widgets with their own clocks catch up through
    refresh_motion()."""
    global _still
    _still = bool(still)


def ambient_ok() -> bool:
    """False when ambient motion holds still: reduced motion, or Reduce
    motion in Settings. Ambient is what moves on its own (the night sky,
    the dial's breathing, glows, sweeps and pulses, the live halo) and
    keeps a clock running; short feedback on a hover or click checks
    motion_ok and stays."""
    return motion_ok() and not _still


# -- one clock for the ambient loops -------------------------------------------
# While another app is in front, Poise is at most glanced at: its steady
# loops run this many times slower. Transitions (a frame every
# TRANSITION_MAX_MS or sooner) answer the user, a wheel turn on the dial
# or Start from the tray, and keep their pace.
BACKGROUND_PACE = 2
TRANSITION_MAX_MS = 20


class _FrameClock(QObject):
    """The one timer behind every FrameTimer. It runs at the shortest
    interval any running FrameTimer asks for and, on each tick, fires
    those that are due, together: what they repaint is painted in one
    pass. (With a timer each, the dial was painted once for its own
    clock and again for the card's behind it.) While the application is
    not the active one, steady loops slow by BACKGROUND_PACE."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = {}                 # id -> FrameTimer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._pace = 1
        state_changed = getattr(parent, "applicationStateChanged", None)
        if state_changed is not None:
            state_changed.connect(self._on_state)
            self._on_state(parent.applicationState())

    def _on_state(self, state) -> None:
        pace = (1 if state == Qt.ApplicationState.ApplicationActive
                else BACKGROUND_PACE)
        if pace != self._pace:
            self._pace = pace
            for frame_timer in self._running.values():
                if not sip.isdeleted(frame_timer):
                    frame_timer._due = time.monotonic()   # re-paced next tick
            self._retime()

    def interval_of(self, frame_timer) -> int:
        """`frame_timer`'s interval at the current pace."""
        interval = frame_timer.interval()
        if interval > TRANSITION_MAX_MS:
            interval *= self._pace
        return interval

    def add(self, frame_timer) -> None:
        self._running[id(frame_timer)] = frame_timer
        self._retime()

    def remove(self, key: int) -> None:
        if self._running.pop(key, None) is not None:
            self._retime()

    def _retime(self) -> None:
        intervals = [self.interval_of(t) for t in self._running.values()
                     if not sip.isdeleted(t)]
        if not intervals:
            self._timer.stop()
            return
        interval = min(intervals)
        if self._timer.interval() != interval:
            self._timer.setInterval(interval)
        if not self._timer.isActive():
            self._timer.start()

    def _tick(self) -> None:
        now = time.monotonic()
        # Due within half a tick counts: a 33 ms loop on a 16 ms clock
        # fires every other tick, not every third.
        slack = self._timer.interval() / 2000.0
        for key, frame_timer in list(self._running.items()):
            if key not in self._running:
                continue                    # stopped by one fired before
            if sip.isdeleted(frame_timer):  # went with its widget
                self.remove(key)
                continue
            if now < frame_timer._due - slack:
                continue
            frame_timer._due = now + self.interval_of(frame_timer) / 1000.0
            frame_timer.timeout.emit()


_frame_clock = None


class FrameTimer(QObject):
    """A QTimer for an ambient loop (start, stop, setInterval, timeout),
    on the clock it shares with every other: loops that run at once fire
    on the same ticks."""

    timeout = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._interval = 0
        self._active = False
        self._due = 0.0

    def interval(self) -> int:
        return self._interval

    def setInterval(self, msec: int) -> None:  # noqa: N802 (QTimer API)
        self._interval = max(1, int(msec))
        if self._active:
            _clock()._retime()

    def isActive(self) -> bool:  # noqa: N802 (QTimer API)
        return self._active

    def start(self, msec: int = None) -> None:
        if msec is not None:
            self._interval = max(1, int(msec))
        self._active = True
        clock = _clock()
        self._due = time.monotonic() + clock.interval_of(self) / 1000.0
        clock.add(self)

    def stop(self) -> None:
        if self._active:
            self._active = False
            _clock().remove(id(self))


def _clock() -> _FrameClock:
    """The shared clock, owned by the application so it goes with it (a
    timer left over after the application is gone crashes on exit)."""
    global _frame_clock
    if _frame_clock is None or sip.isdeleted(_frame_clock):
        from PyQt6.QtCore import QCoreApplication
        _frame_clock = _FrameClock(QCoreApplication.instance())
    return _frame_clock


# -- native views and snapshots ------------------------------------------------
# A native window (the GPU sky's) is not in a widget's grab() and draws
# over any overlay: what the transitions below snapshot or cover holds
# it as a still for as long as they run (hold_native / release_native).
_natives = weakref.WeakSet()


def register_native(widget: QWidget) -> None:
    """`widget` can hold a native view of its own (see hold_natives)."""
    _natives.add(widget)


def hold_natives(roots, reason: str):
    """Hold, as stills, the native views in or under `roots` (widgets);
    returns release(), which lets them go (once)."""
    held = []
    for host in list(_natives):
        if sip.isdeleted(host):
            continue
        if any(root is not None and not sip.isdeleted(root)
               and (root is host or root.isAncestorOf(host))
               for root in roots):
            host.hold_native(reason)
            held.append(host)

    def release() -> None:
        while held:
            host = held.pop()
            if not sip.isdeleted(host):
                host.release_native(reason)

    return release


def _keep(widget: QWidget, anim: QObject) -> QObject:
    """Hold a reference so Qt doesn't GC a running animation.

    NOTE: never compare QAbstractAnimation.state() to a raw int — in
    PyQt6 State is an enum and `Running == 2` is False, which used to
    prune (and garbage-collect) still-running animations mid-flight,
    stranding widgets at opacity 0. Just append and prune on finished.
    """
    try:
        alive = getattr(widget, "_apple_anims", None)
        if alive is None:
            alive = []
            widget._apple_anims = alive  # type: ignore[attr-defined]
        alive.append(anim)
        if len(alive) > 32:
            del alive[:-32]
        try:
            anim.finished.connect(  # type: ignore[attr-defined]
                lambda: alive.remove(anim) if anim in alive else None)
        except Exception:
            pass
    except Exception:
        pass
    return anim


def _opacity(widget: QWidget) -> QGraphicsOpacityEffect:
    eff = widget.graphicsEffect()
    if isinstance(eff, QGraphicsOpacityEffect):
        return eff
    eff = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(eff)
    return eff


def cancel_fade(widget: QWidget, reset_opacity: float = 1.0) -> None:
    """Stop any in-flight entrance fade and void pending delayed starts."""
    try:
        anim = getattr(widget, "_apple_fade", None)
        if anim is not None:
            try:
                anim.stop()
            except Exception:
                pass
            widget._apple_fade = None  # type: ignore[attr-defined]
        # Bump the generation so stale singleShot starts abort.
        widget._apple_fade_gen = int(  # type: ignore[attr-defined]
            getattr(widget, "_apple_fade_gen", 0) or 0) + 1
        eff = widget.graphicsEffect()
        if isinstance(eff, QGraphicsOpacityEffect):
            try:
                eff.setOpacity(reset_opacity)
            except Exception:
                pass
    except Exception:
        pass


# -- entrances ----------------------------------------------------------------
def fade_in(widget: QWidget, delay_ms: int = 0, duration_ms: int = D_OUT,
            start: float = 0.0, end: float = 1.0,
            cleanup: bool = True) -> QPropertyAnimation | None:
    """Fade a (simple leaf) widget in — opacity only, layout-safe.

    The start opacity is applied synchronously so there is no
    appear-then-vanish flicker, and the effect is removed once the
    fade completes (cleanup=True) so repaints stay on the fast path.
    A new fade supersedes any previous one on the same widget.
    """
    try:
        eff = _opacity(widget)
    except Exception:
        return None
    cancel_fade(widget)
    try:
        gen = int(getattr(widget, "_apple_fade_gen", 0) or 0)
    except Exception:
        gen = 0
    if not motion_ok():
        try:
            eff.setOpacity(end)
        except Exception:
            pass
        if cleanup and end >= 1.0:
            clear_fade(widget)
        return None
    try:
        eff.setOpacity(start)
    except Exception:
        pass

    def _start() -> None:
        try:
            if int(getattr(widget, "_apple_fade_gen", 0) or 0) != gen:
                return  # superseded by a newer fade/page visit
            if widget.graphicsEffect() is not eff:
                return  # effect replaced (e.g. pulse took over); don't fight
            anim = QPropertyAnimation(eff, b"opacity", widget)
            anim.setDuration(max(1, int(duration_ms)))
            anim.setStartValue(start)
            anim.setEndValue(end)
            anim.setEasingCurve(EASE_OUT)
            widget._apple_fade = anim  # type: ignore[attr-defined]

            def _done() -> None:
                try:
                    if getattr(widget, "_apple_fade", None) is anim:
                        widget._apple_fade = None  # type: ignore[attr-defined]
                except Exception:
                    pass
                if cleanup and end >= 1.0:
                    try:
                        if widget.graphicsEffect() is eff:
                            widget.setGraphicsEffect(None)
                    except Exception:
                        pass

            try:
                anim.finished.connect(_done)
            except Exception:
                pass
            _keep(widget, anim)
            anim.start()
        except Exception:
            pass

    if delay_ms > 0:
        QTimer.singleShot(int(delay_ms), _start)
        return None
    _start()
    try:
        return getattr(widget, "_apple_fade", None)
    except Exception:
        return None


def rise_in(widget: QWidget, delay_ms: int = 0, duration_ms: int = 520,
            rise: float = 14.0) -> None:
    """Entrance: fade in while rising `rise` px into place. The offset is
    drawn (an effect), so the layout never moves; same safety rules as
    fade_in, and the effect is removed once the widget has landed."""
    if not motion_ok():
        return
    try:
        cancel_fade(widget)
        gen = int(getattr(widget, "_apple_fade_gen", 0) or 0)
        eff = _RollEffect(widget)
        eff.setOpacity(0.0)
        eff.set_dy(rise)
        widget.setGraphicsEffect(eff)
    except Exception:
        return

    def _start() -> None:
        try:
            if widget.graphicsEffect() is not eff:
                return  # someone else's effect now
            if int(getattr(widget, "_apple_fade_gen", 0) or 0) != gen:
                widget.setGraphicsEffect(None)   # superseded: land at once
                return
            anim = QVariantAnimation(widget)
            anim.setDuration(max(1, int(duration_ms)))
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(EASE_OUT)

            def _step(v) -> None:
                eff.setOpacity(float(v))
                eff.set_dy(rise * (1.0 - float(v)))

            def _done() -> None:
                try:
                    if getattr(widget, "_apple_fade", None) is anim:
                        widget._apple_fade = None  # type: ignore[attr-defined]
                    if widget.graphicsEffect() is eff:
                        widget.setGraphicsEffect(None)
                except RuntimeError:
                    pass

            anim.valueChanged.connect(_step)
            anim.finished.connect(_done)
            widget._apple_fade = anim  # type: ignore[attr-defined]
            _keep(widget, anim)
            anim.start()
        except Exception:
            pass

    if delay_ms > 0:
        QTimer.singleShot(int(delay_ms), _start)
    else:
        _start()


def flash_colour(label: QWidget, colour: str, duration_ms: int = 1500,
                 hold: float = 0.35) -> None:
    """Draw attention to a label: its text takes `colour`, holds it for
    the first `hold` of the time, then fades back to its own colour. A
    widget-local sheet carries the colour while it runs and is dropped
    at the end (the label must not have a local sheet of its own)."""
    if not motion_ok():
        return
    try:
        from PyQt6.QtGui import QPalette
        old = getattr(label, "_flash_anim", None)
        if old is not None:          # re-flash: keep the true resting colour
            old.stop()
            base = label._flash_base  # type: ignore[attr-defined]
        else:
            base = label.palette().color(QPalette.ColorRole.WindowText)
            label._flash_base = base  # type: ignore[attr-defined]
        target = QColor(colour)
        anim = QVariantAnimation(label)
        anim.setDuration(max(1, int(duration_ms)))
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)

        def _step(v) -> None:
            t = max(0.0, (float(v) - hold) / (1.0 - hold))
            label.setStyleSheet(f"color: {mix_rgba(target, base, t).name()};")

        def _done() -> None:
            try:
                label.setStyleSheet("")
                label._flash_anim = None  # type: ignore[attr-defined]
            except RuntimeError:
                pass

        anim.valueChanged.connect(_step)
        anim.finished.connect(_done)
        label._flash_anim = anim  # type: ignore[attr-defined]
        _step(0.0)
        anim.start()
    except Exception:
        pass


def stagger_in(widgets, base_delay_ms: int = 0, step_ms: int = 55,
               duration_ms: int = 220) -> None:
    """Apple-style staggered card entrance: fade cascade, no layout shift."""
    for i, w in enumerate(widgets):
        try:
            fade_in(w, delay_ms=base_delay_ms + i * step_ms,
                    duration_ms=duration_ms)
        except Exception:
            continue


def clear_fade(widget: QWidget) -> None:
    """Remove a fade effect (restores the fast paint path)."""
    try:
        cancel_fade(widget)
        eff = widget.graphicsEffect()
        if isinstance(eff, QGraphicsOpacityEffect):
            widget.setGraphicsEffect(None)
    except Exception:
        pass


def _drop_overlay(overlay) -> None:
    """Detach a snapshot overlay synchronously and schedule its deletion.

    hide() + setParent(None) take effect immediately (no reliance on the
    event loop's deferred-delete pass), so a cancelled/finished slide can
    never leave a frozen snapshot on screen; deleteLater() then frees it.
    """
    try:
        if overlay is None:
            return
        try:
            overlay.hide()
        except Exception:
            pass
        try:
            overlay.setParent(None)
        except Exception:
            pass
        try:
            overlay.deleteLater()
        except Exception:
            pass
    except Exception:
        pass


def _cancel_slide(stack: QStackedWidget) -> None:
    """Tear down an in-flight page slide (stop anims, drop overlay, snap)."""
    try:
        state = getattr(stack, "_apple_slide", None)
        if not state:
            return
        stack._apple_slide = None  # type: ignore[attr-defined]
        try:
            group = state.get("group")
            if group is not None:
                group.stop()
        except Exception:
            pass
        _drop_overlay(state.get("overlay"))
        release = state.get("release")
        if release is not None:
            release()
        # Snap the (already current) page back onto the stack geometry so
        # a retargeted slide starts from a clean pose.
        try:
            page = state.get("page")
            if page is not None:
                page.setGeometry(stack.contentsRect())
        except Exception:
            pass
    except Exception:
        pass


def slide_stack(stack: QStackedWidget, index: int,
                duration_ms: int = WS_MS) -> None:
    """Hyprland-workspace page switch: old slides out + fades, new slides in.

    Direction follows the sidebar order: clicking a section *below* the
    current one travels up (new page enters from the bottom), clicking
    above travels down — like moving between workspaces. Travel covers
    WS_TRAVEL of the stack height on the overshot spring curve; the
    outgoing snapshot also fades out (slidefadevert). The incoming page
    itself is never faded (opacity effects on scrollareas corrupt
    painting) — it just slides.

    Falls back to an instant switch under reduced motion, on degenerate
    geometry, or if the snapshot fails. Safe to spam-click: a new call
    retargets from the current page.
    """
    if index == stack.currentIndex():
        return
    _cancel_slide(stack)
    old = stack.currentIndex()
    old_page = stack.currentWidget()
    if not motion_ok():
        stack.setCurrentIndex(index)
        return
    # Native views on either page slide as stills (the snapshot cannot
    # see them, and they would draw over it).
    release = hold_natives([old_page, stack.widget(index)], "slide")
    stack.setCurrentIndex(index)
    new_page = stack.currentWidget()
    if new_page is None:
        release()
        return
    try:
        height = stack.height()
        travel = int(round(height * WS_TRAVEL))
        if height <= 0 or travel <= 0:
            release()
            return
        # Content travel direction: down the sidebar list == up on screen.
        shift = -travel if index > old else travel

        from PyQt6.QtCore import QPoint, QParallelAnimationGroup, QRect
        from PyQt6.QtWidgets import QLabel

        target = stack.contentsRect()
        tx, ty = target.x(), target.y()

        overlay = None
        # Overlay frame: root-relative when floating over the stack's
        # parent (normal case), stack-relative otherwise. Mixing these
        # up parks the snapshot at x=0 — on top of the sidebar.
        obase = QPoint(tx, ty)
        orect = QRect(tx, ty, target.width(), target.height())
        try:
            pix = old_page.grab() if old_page is not None else None
        except Exception:
            pix = None
        if pix is not None and not pix.isNull():
            try:
                parent = stack.parentWidget()
                if parent is None or parent is stack:
                    parent = stack
                else:
                    sgeo = stack.geometry()
                    obase = QPoint(sgeo.x(), sgeo.y())
                    orect = sgeo
                overlay = QLabel(parent)
                overlay.setPixmap(pix)
                overlay.setAttribute(
                    Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                overlay.setGeometry(orect)
                overlay.show()
                overlay.raise_()
            except Exception:
                overlay = None

        group = QParallelAnimationGroup(stack)
        curve = _hypr_curve()
        fade_curve = _hypr_curve(clamp=True)

        if overlay is not None:
            try:
                from PyQt6.QtWidgets import QGraphicsOpacityEffect
                eff = QGraphicsOpacityEffect(overlay)
                overlay.setGraphicsEffect(eff)
                # Slide the old snapshot out along the travel direction
                # (overlay frame, NOT the page frame — see above).
                pos_anim = QPropertyAnimation(overlay, b"pos", stack)
                pos_anim.setDuration(max(1, int(duration_ms)))
                pos_anim.setStartValue(QPoint(obase.x(), obase.y()))
                pos_anim.setEndValue(QPoint(obase.x(), obase.y() + shift))
                pos_anim.setEasingCurve(curve)
                group.addAnimation(pos_anim)
                # ...while it fades out (plain QLabel: effect-safe).
                fade_anim = QPropertyAnimation(eff, b"opacity", stack)
                fade_anim.setDuration(max(1, int(duration_ms)))
                fade_anim.setStartValue(1.0)
                fade_anim.setEndValue(0.0)
                fade_anim.setEasingCurve(fade_curve)
                group.addAnimation(fade_anim)
            except Exception:
                _drop_overlay(overlay)
                overlay = None

        # The new page slides in from the side the content comes from.
        # (No fade here — opacity effects on scrollareas break painting.)
        try:
            new_page.setGeometry(target)
            in_anim = QPropertyAnimation(new_page, b"pos", stack)
            in_anim.setDuration(max(1, int(duration_ms)))
            in_anim.setStartValue(QPoint(tx, ty - shift))
            in_anim.setEndValue(QPoint(tx, ty))
            in_anim.setEasingCurve(curve)
            group.addAnimation(in_anim)
        except Exception:
            pass

        if group.animationCount() == 0:
            _drop_overlay(overlay)
            return

        state = {"group": group, "overlay": overlay, "page": new_page,
                 "target": target, "release": release}
        stack._apple_slide = state  # type: ignore[attr-defined]

        def _done() -> None:
            try:
                if getattr(stack, "_apple_slide", None) is not state:
                    return
                stack._apple_slide = None  # type: ignore[attr-defined]
                try:
                    new_page.setGeometry(target)
                except Exception:
                    pass
                _drop_overlay(overlay)
                release()
            except Exception:
                pass

        try:
            group.finished.connect(_done)
        except Exception:
            pass
        _keep(stack, group)
        group.start()
    except Exception:
        try:
            _cancel_slide(stack)
        except Exception:
            pass
        release()


# Backwards-compatible alias (old name from the cascade era).
crossfade_stack = slide_stack


# -- press feedback for stock buttons ------------------------------------------
class _PressFadeFilter(QObject):
    """Opacity dip while a QPushButton is held. Layout-safe (no scaling).

    The effect is removed once the button is released so buttons repaint
    on the fast path at rest.
    """

    def __init__(self, button: QAbstractButton,
                 pressed_opacity: float = PRESS_OPACITY,
                 duration_ms: int = D_IN):
        super().__init__(button)
        self._btn = button
        self._pressed_opacity = pressed_opacity
        self._duration = duration_ms
        self._anim: QPropertyAnimation | None = None

    def _tween(self, target: float) -> None:
        try:
            # No-op guard: a plain hover-leave at rest must not install
            # (and 120ms later tear down) an opacity effect — routing the
            # label/icon subtree through an effect pixmap and back is what
            # makes the label color flicker. Only animate real changes.
            eff = self._btn.graphicsEffect()
            if not isinstance(eff, QGraphicsOpacityEffect):
                if target >= 1.0:
                    return  # at rest: install nothing
                eff = _opacity(self._btn)
            elif abs(eff.opacity() - target) < 0.005:
                return  # already there
            if not motion_ok():
                eff.setOpacity(target if target < 1.0 else 1.0)
                if target >= 1.0:
                    try:
                        if self._btn.graphicsEffect() is eff:
                            self._btn.setGraphicsEffect(None)
                    except Exception:
                        pass
                return
            if self._anim is not None:
                try:
                    self._anim.stop()
                except Exception:
                    pass
            self._anim = QPropertyAnimation(eff, b"opacity", self._btn)
            self._anim.setDuration(self._duration)
            self._anim.setStartValue(eff.opacity())
            self._anim.setEndValue(target)
            self._anim.setEasingCurve(EASE_OUT)
            if target >= 1.0:
                def _done(btn=self._btn, eff=eff) -> None:
                    try:
                        if btn.graphicsEffect() is eff:
                            btn.setGraphicsEffect(None)
                    except Exception:
                        pass

                try:
                    self._anim.finished.connect(_done)
                except Exception:
                    pass
            _keep(self._btn, self._anim)
            self._anim.start()
        except Exception:
            pass

    def eventFilter(self, watched: QObject, event) -> bool:
        try:
            from PyQt6.QtCore import QEvent
            if watched is self._btn:
                if event.type() == QEvent.Type.MouseButtonPress:
                    if self._btn.isEnabled():
                        self._tween(self._pressed_opacity)
                elif event.type() in (QEvent.Type.MouseButtonRelease,
                                      QEvent.Type.Leave):
                    self._tween(1.0)
        except Exception:
            pass
        return False


def install_press_fade(button: QAbstractButton,
                       pressed_opacity: float = PRESS_OPACITY) -> QObject:
    """Attach press-dip feedback. Returns the filter (parented to button)."""
    filt = _PressFadeFilter(button, pressed_opacity=pressed_opacity)
    button.installEventFilter(filt)
    return filt


# -- looping pulse (status / live dot) -----------------------------------------
class _PulseHelper(QObject):
    """Drives a 0..1 breathing value on any QObject float property."""

    def __init__(self, target: QObject, prop: bytes,
                 duration_ms: int = D_BREATHE):
        super().__init__(target)
        self._anim = QPropertyAnimation(target, prop, target)
        self._anim.setDuration(max(1, duration_ms))
        self._anim.setStartValue(0.0)
        self._anim.setKeyValueAt(0.5, 1.0)
        self._anim.setEndValue(0.0)
        self._anim.setEasingCurve(EASE_BREATHE)
        self._anim.setLoopCount(-1)

    def start(self) -> None:
        if motion_ok():
            self._anim.start()

    def stop(self) -> None:
        try:
            self._anim.stop()
        except Exception:
            pass


def pulse_property(target: QObject, prop: bytes,
                   duration_ms: int = D_BREATHE) -> _PulseHelper:
    """Loop a 0..1 float property (e.g. b'breathe'). Caller sets initial 0."""
    helper = _PulseHelper(target, prop, duration_ms=duration_ms)
    # Keep alive on the target.
    try:
        keep = getattr(target, "_apple_helpers", None)
        if keep is None:
            keep = []
            target._apple_helpers = keep  # type: ignore[attr-defined]
        keep.append(helper)
    except Exception:
        pass
    helper.start()
    return helper


# -- springy float tween (for custom-painted widgets) ---------------------------
def tween_float(target: QObject, prop: bytes, end: float,
                duration_ms: int = D_OUT,
                easing=EASE_OUT,
                start: float | None = None) -> QPropertyAnimation | None:
    """Animate a pyqtProperty float on a custom widget."""
    if not motion_ok():
        try:
            # prop may be bytes (plain) or QByteArray (has .data()).
            if isinstance(prop, bytes):
                name = prop.decode()
            else:
                name = prop.data().decode()
            target.setProperty(name, end)
        except Exception:
            pass
        return None
    try:
        anim = QPropertyAnimation(target, prop, target)
        anim.setDuration(max(1, duration_ms))
        anim.setEndValue(end)
        if start is not None:
            anim.setStartValue(start)
        anim.setEasingCurve(easing)
        _keep(target, anim)  # type: ignore[arg-type]
        anim.start()
        return anim
    except Exception:
        return None


# -- eased state blends --------------------------------------------------------
# -- easing for painted, clock-driven motion (t clamped to 0..1) ---------------
def _unit(t: float) -> float:
    return max(0.0, min(1.0, float(t)))


def ease_out(t: float) -> float:
    """Cubic ease-out."""
    t = _unit(t)
    return 1.0 - (1.0 - t) ** 3


def ease_in(t: float) -> float:
    """Quadratic ease-in."""
    t = _unit(t)
    return t * t


def ease_in_out(t: float) -> float:
    """Smoothstep."""
    t = _unit(t)
    return 3 * t * t - 2 * t * t * t


def ease_back(t: float, overshoot: float = 1.7) -> float:
    """Out-back: past 1, then settles (a spring)."""
    t = _unit(t) - 1.0
    return t * t * ((overshoot + 1.0) * t + overshoot) + 1.0


def rise_fall(u: float, peak: float) -> float:
    """0 -> 1 at `peak` -> 0 at 1, linear (0 outside 0..1)."""
    if u <= 0.0 or u >= 1.0:
        return 0.0
    return u / peak if u < peak else 1.0 - (u - peak) / (1.0 - peak)


def mix_rgba(a: QColor, b: QColor, t: float) -> QColor:
    """Linear blend of two colours including alpha (t clamped to 0..1)."""
    t = max(0.0, min(1.0, t))
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
        int(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


class Blend(QObject):
    """An eased 0..1 value that glides toward a target.

    One per animated visual state of a painted widget (hover, checked,
    lit...). The owner repaints in `on_change`. Under reduced motion every
    change snaps, so end states are always reached.
    """

    def __init__(self, owner: QObject, on_change, duration_ms: int = D_OUT,
                 easing=EASE_OUT, value: float = 0.0):
        super().__init__(owner)
        self._on_change = on_change
        self._value = float(value)
        self._target = float(value)
        self._duration = int(duration_ms)
        self._easing = easing
        self._anim = QVariantAnimation(self)
        self._anim.setEasingCurve(easing)
        self._anim.valueChanged.connect(self._step)

    @property
    def value(self) -> float:
        return self._value

    @property
    def target(self) -> float:
        return self._target

    @property
    def running(self) -> bool:
        return self._anim.state() == QVariantAnimation.State.Running

    def _step(self, v) -> None:
        self._value = float(v)
        self._on_change()

    def set_target(self, target: float, animated: bool = True,
                   duration_ms: int | None = None, easing=None) -> None:
        """Glide to `target` (`duration_ms` / `easing` override the
        defaults for this glide only, e.g. a slower way out)."""
        target = float(target)
        if target == self._target:
            return
        self._target = target
        if (not animated or not motion_ok()
                or abs(self._value - target) < 1e-4):
            self.snap(target)
            return
        start = self._value
        self._anim.stop()
        # Reconfiguring a stopped animation re-emits its value at the old
        # current time (a new duration moves that time's progress, e.g.
        # 240 of 380 ms -> 0.7), which would jump the glide's start.
        self._anim.blockSignals(True)
        self._anim.setEasingCurve(self._easing if easing is None else easing)
        self._anim.setDuration(max(1, int(duration_ms or self._duration)))
        self._anim.setStartValue(start)
        self._anim.setEndValue(target)
        self._anim.blockSignals(False)
        self._anim.start()

    def snap(self, value: float) -> None:
        """Jump to `value` (no animation)."""
        self._anim.stop()
        self._value = self._target = float(value)
        self._on_change()


class QssHoverFade(QObject):
    """Crossfade QSS :hover colours (QSS itself cannot transition).

    `colors()` returns {css-property: (rest QColor, hover QColor)} and is
    evaluated on every run, so theme switches stay live. While fading, a
    widget-local sheet (which always beats the app sheet) carries the
    in-between colour; once settled the local sheet is removed and the
    plain QSS rest/:hover rules apply, identical by construction.
    """

    def __init__(self, widget: QWidget, selector: str, colors,
                 duration_ms: int = D_OUT):
        super().__init__(widget)
        self._w = widget
        self._selector = selector
        self._colors = colors
        self._blend = Blend(self, self._apply, duration_ms)
        widget.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt override)
        try:
            if obj is self._w:
                kind = event.type()
                if kind == QEvent.Type.Enter and self._w.isEnabled():
                    self._begin(1.0)
                elif kind == QEvent.Type.Leave:
                    self._begin(0.0)
                elif (kind == QEvent.Type.EnabledChange
                        and not self._w.isEnabled()):
                    self._blend.snap(0.0)
        except Exception:
            pass
        return False

    def _begin(self, target: float) -> None:
        # Pin the current look before Qt flips :hover on this very event;
        # otherwise one frame paints at the wrong colour.
        self._apply(force=True)
        self._blend.set_target(target)

    def _css(self, t: float) -> str:
        parts = []
        for prop, (rest, hover) in self._colors().items():
            c = mix_rgba(rest, hover, t)
            parts.append(f"{prop}: rgba({c.red()}, {c.green()}, "
                         f"{c.blue()}, {c.alphaF():.3f});")
        return f"{self._selector} {{ {' '.join(parts)} }}"

    def _apply(self, force: bool = False) -> None:
        try:
            t, target = self._blend.value, self._blend.target
            settled = ((t <= 0.001 and target == 0.0)
                       or (t >= 0.999 and target == 1.0))
            if settled and not force:
                if self._w.styleSheet():
                    self._w.setStyleSheet("")
                return
            self._w.setStyleSheet(self._css(t))
        except Exception:
            pass


def _hover_specs():
    """(class name, objectName) -> palette -> {property: (rest, hover)}."""
    from .themes import ACCENT_WASH_ALPHA

    def slate(alpha):
        c = QColor(148, 163, 184)
        c.setAlphaF(alpha)
        return c

    def wash(p, alpha):
        c = QColor(p["accent"])
        c.setAlphaF(alpha)
        return c

    return {
        ("QPushButton", "ghost"): lambda p: {
            "border-color": (slate(0.18), QColor(p["secondary"]))},
        ("QPushButton", "icon-btn"): lambda p: {
            "background-color": (wash(p, 0.0),
                                 wash(p, ACCENT_WASH_ALPHA))},
        ("QPushButton", "primary"): lambda p: {
            "background-color": (QColor(p["accent"]),
                                 QColor(p["accent_light"]))},
        ("QComboBox", "device-combo"): lambda p: {
            "border-color": (slate(0.25), QColor(p["secondary"]))},
    }


def install_hover_fades(root: QWidget) -> int:
    """Attach hover crossfades to the stock buttons/fields under `root`.

    Idempotent; returns how many widgets were wired. Call again after
    building new widgets (e.g. a dialog).
    """
    from PyQt6.QtWidgets import QComboBox, QPushButton
    from .themes import current

    specs = _hover_specs()
    wired = 0
    for cls in (QPushButton, QComboBox):
        for w in root.findChildren(cls):
            spec = specs.get((cls.__name__, w.objectName()))
            if spec is None or getattr(w, "_hover_fade", None) is not None:
                continue
            w._hover_fade = QssHoverFade(
                w, f"{cls.__name__}#{w.objectName()}",
                lambda spec=spec: spec(current()))
            wired += 1
    return wired


def crossfade_from(widget: QWidget, snapshot, duration_ms: int = 260,
                   on_done=None):
    """Fade a snapshot of the previous look away to reveal the new one.

    `snapshot` is a QPixmap grabbed before the change. The overlay is a
    plain label (safe to fade; see the module's safety rules) and is
    detached synchronously when done; on_done() runs then (or at once,
    with no fade).
    """
    done = on_done or (lambda: None)
    try:
        if not motion_ok() or snapshot is None or snapshot.isNull():
            done()
            return None
        from PyQt6.QtWidgets import QLabel
        overlay = QLabel(widget)
        overlay.setPixmap(snapshot)
        overlay.setGeometry(widget.rect())
        overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        overlay.show()
        overlay.raise_()
        effect = QGraphicsOpacityEffect(overlay)
        overlay.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", overlay)
        anim.setDuration(duration_ms)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(EASE_OUT)
        anim.finished.connect(lambda: _drop_overlay(overlay))
        anim.finished.connect(done)
        overlay._anim = anim
        anim.start()
        return overlay
    except Exception:
        done()
        return None


class _RollEffect(QGraphicsOpacityEffect):
    """Opacity plus a vertical offset, drawn (not laid out): TextSwap's
    roll. The bounding rect grows with the offset so nothing clips."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dy = 0.0

    def set_dy(self, dy: float) -> None:
        self._dy = float(dy)
        self.updateBoundingRect()
        self.update()

    def boundingRectFor(self, rect):  # noqa: N802 (Qt override)
        pad = abs(self._dy) + 1.0
        return super().boundingRectFor(rect).adjusted(0, -pad, 0, pad)

    def draw(self, painter):
        painter.save()
        painter.translate(0, self._dy)
        super().draw(painter)
        painter.restore()


_SMOKE_SPREAD = cubic_bezier_fn(0.3, 0.6, 0.2, 1.0)
# Smoke's two rings of faint copies: (radius as a fraction of the reach,
# copies, alpha weight, twist in radians at full smoke).
_SMOKE_RINGS = ((0.45, 6, 0.2, 0.6), (1.0, 10, 0.11, 1.4))


def smoke_wisps(smoke: float, reach: float):
    """Text dissolving like smoke, the stand-in for a CSS blur: at `smoke`
    0..1 (0 sharp), the sharp copy's alpha factor and [(alpha factor, dx,
    dy)] of the faint copies around it. They spread up to `reach` px in
    place, their rings curling round as they thin; nothing moves."""
    spread = reach * _SMOKE_SPREAD(smoke)
    wisps = []
    for radius, count, weight, twist in _SMOKE_RINGS:
        spin = twist * smoke
        for k in range(count):
            a = spin + 2.0 * math.pi * k / count
            wisps.append((weight * smoke, spread * radius * math.cos(a),
                          spread * radius * math.sin(a)))
    return (1.0 - smoke) ** 2, wisps


class _SmokeEffect(QGraphicsOpacityEffect):
    """Opacity that dissolves like smoke as it falls (smoke_wisps): TextSwap
    with `smoke`. Drawn in place, so the layout never moves; the bounding
    rect grows by the reach so the wisps never clip."""

    def __init__(self, parent=None, reach: float = 6.0):
        super().__init__(parent)
        self._reach = float(reach)

    def boundingRectFor(self, rect):  # noqa: N802 (Qt override)
        pad = self._reach + 1.0
        return super().boundingRectFor(rect).adjusted(-pad, -pad, pad, pad)

    def draw(self, painter):
        alpha = float(self.opacity())
        smoke = 1.0 - alpha
        if smoke < 0.03:
            super().draw(painter)
            return
        pixmap, offset = self.sourcePixmap(
            Qt.CoordinateSystem.LogicalCoordinates)
        core, wisps = smoke_wisps(smoke, self._reach)
        painter.save()
        base = painter.opacity() * alpha
        painter.setOpacity(base * core)
        painter.drawPixmap(offset, pixmap)
        for weight, dx, dy in wisps:
            painter.setOpacity(base * weight)
            painter.drawPixmap(QPointF(offset) + QPointF(dx, dy), pixmap)
        painter.restore()


class TextSwap(QObject):
    """Change a label's text with a quick fade out, then fade in.

    Opacity only (layout-safe), and the effect is removed once settled.
    With `rise` (px) the text also rolls: the old one leaves upward and
    the new one rises into place, still without touching the layout.
    With `smoke` (px) it instead dissolves in place like smoke and the
    new text condenses out of it (smoke_wisps); smoke wins over rise.
    Updates coalesce: text that arrives while the old text is fading out
    replaces the pending one, so a burst of status messages shows only the
    newest instead of flashing through each. Hidden labels and reduced
    motion change instantly.

    The swap owns the label's effect while busy; a label that already has
    another effect (e.g. a pulse) is changed instantly instead of nesting
    fades. `settled` fires once the shown text is final and unfaded, so a
    caller can start such a pulse only after the swap.
    """

    settled = pyqtSignal()

    OUT_MS = 90
    IN_MS = 170

    def __init__(self, label, out_ms: int = OUT_MS, in_ms: int = IN_MS,
                 rise: float = 0.0, smoke: float = 0.0):
        super().__init__(label)
        self._label = label
        self._rise = float(rise)
        self._smoke = float(smoke)
        self._out_ms, self._in_ms = out_ms, in_ms
        self._easing = EASE_OUT
        self._text = label.text()
        self._eff = None
        self._anim = None
        self._phase = None   # None | "out" | "in"
        self._apply = None   # pending styling for the new text

    def set_timing(self, out_ms: int, in_ms: int, rise: float = None,
                   easing=EASE_OUT, smoke: float = None) -> None:
        """Change the swap's pace (e.g. a theme with a slower rhythm);
        applies from the next swap."""
        self._out_ms, self._in_ms = out_ms, in_ms
        self._easing = easing
        if rise is not None and (rise > 0) == (self._rise > 0):
            self._rise = float(rise)   # (a roll stays a roll)
        if smoke is not None:
            self._smoke = float(smoke)

    @property
    def busy(self) -> bool:
        return self._phase is not None

    def text(self) -> str:
        """The text being shown, or about to be once the fade-out ends."""
        return self._text

    def set_text(self, text: str, on_apply=None) -> None:
        """Swap to text. on_apply() runs as the new text appears (e.g. to
        restyle it), not while the old text is still fading out."""
        if text == self._text:
            if on_apply is not None and self._phase != "out":
                on_apply()
            elif on_apply is not None:
                self._apply = on_apply
            return
        self._text = text
        self._apply = on_apply
        label = self._label
        foreign = (label.graphicsEffect() is not None
                   and label.graphicsEffect() is not self._eff)
        if not motion_ok() or not label.isVisible() or foreign:
            self._settle()
            return
        if self._phase == "out":
            return   # the pending text is picked up when the fade-out ends
        self._run("out", self._opacity(), 0.0, self._out_ms)

    def _opacity(self) -> float:
        try:
            return float(self._eff.opacity()) if self._eff is not None else 1.0
        except RuntimeError:
            return 1.0

    def _run(self, phase: str, start: float, end: float, ms: int) -> None:
        if self._anim is not None:
            self._anim.stop()
        if self._eff is None or self._label.graphicsEffect() is not self._eff:
            if self._smoke:
                self._eff = _SmokeEffect(self._label, self._smoke)
            elif self._rise:
                self._eff = _RollEffect(self._label)
            else:
                self._eff = QGraphicsOpacityEffect(self._label)
            self._label.setGraphicsEffect(self._eff)
        self._eff.setOpacity(start)
        self._phase = phase
        self._roll(start)
        anim = QPropertyAnimation(self._eff, b"opacity", self)
        anim.setDuration(max(1, int(ms * abs(start - end))) if phase == "out"
                         else ms)
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.setEasingCurve(self._easing)
        if isinstance(self._eff, _RollEffect):
            anim.valueChanged.connect(self._roll)
        anim.finished.connect(self._step)
        self._anim = anim
        anim.start()

    def _roll(self, opacity) -> None:
        """Offset in step with the fade: up and out, then up into place."""
        if not isinstance(self._eff, _RollEffect):
            return
        away = self._rise * (1.0 - float(opacity))
        self._eff.set_dy(-away if self._phase == "out" else away)

    def _show_text(self) -> None:
        apply, self._apply = self._apply, None
        if apply is not None:
            apply()
        self._label.setText(self._text)

    def _step(self) -> None:
        if self._phase == "out":
            self._show_text()
            self._run("in", 0.0, 1.0, self._in_ms)
        else:
            self._settle()

    def _settle(self) -> None:
        """Show the latest text at full opacity and drop the effect."""
        if self._anim is not None:
            self._anim.stop()
            self._anim = None
        self._show_text()
        if self._eff is not None:
            try:
                if self._label.graphicsEffect() is self._eff:
                    self._label.setGraphicsEffect(None)
            except RuntimeError:
                pass
            self._eff = None
        self._phase = None
        self.settled.emit()
