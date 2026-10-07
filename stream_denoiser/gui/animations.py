"""
Poise Voice Isolator - Apple-style animation helpers.

Small, dependency-free micro-interaction toolkit for Qt Widgets:

- fade / staggered entrance (opacity only — safe inside layouts)
- Hyprland-style directional page transitions for QStackedWidget
  (snapshot slide-out + slide-in, no cascade)
- press-fade filter for standard QPushButtons (no layout churn)
- looping pulse (status dot / live indicator)
- shared Apple-like timings + easings

QSS cannot animate, so all motion lives here in code. Every helper
respects reduced motion via POISE_NO_ANIM=1 / POISE_REDUCE_MOTION=1
and degrades to an instant state change.

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

import os

from PyQt6.QtCore import (
    QEasingCurve,
    QObject,
    QPropertyAnimation,
    Qt,
    QTimer,
)
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

    def _sample_dx(t: float) -> float:
        return (3.0 * ax * t + 2.0 * bx) * t + cx

    def fn(progress: float) -> float:
        if progress <= 0.0:
            return 0.0
        if progress >= 1.0:
            return 1.0
        # Newton iterations.
        t = progress
        for _ in range(8):
            err = _sample_x(t) - progress
            if abs(err) < 1e-6:
                return _sample_y(t)
            d = _sample_dx(t)
            if abs(d) < 1e-6:
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


def motion_ok() -> bool:
    """False when the user asked for reduced motion (env override)."""
    return not (
        os.environ.get("POISE_NO_ANIM") == "1"
        or os.environ.get("POISE_REDUCE_MOTION") == "1"
    )


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
    stack.setCurrentIndex(index)
    new_page = stack.currentWidget()
    if new_page is None:
        return
    if not motion_ok():
        return
    try:
        height = stack.height()
        travel = int(round(height * WS_TRAVEL))
        if height <= 0 or travel <= 0:
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
                 "target": target}
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
