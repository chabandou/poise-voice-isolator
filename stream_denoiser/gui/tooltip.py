"""
Poise Voice Isolator - Animated Tooltips

App-wide tooltip manager: intercepting QEvent.ToolTip before Qt's native
tip singleton lets every tooltip fade/rise in and fade out, screen-aware
positioned, on the themed QLabel#poise-tip style. Native tips are
suppressed wherever this manager sees the event (tray icons keep the
native path and its matching QToolTip rule).

Behavior mirrors the native semantics: a short hover delay, hide on
press/key/wheel/focus change, when the cursor leaves, or when hovering
something without tip text. Reduced motion (or any failure) degrades to
instant show/hide.
"""
from PyQt6.QtCore import (
    QEasingCurve, QObject, QPoint, QPropertyAnimation,
    QParallelAnimationGroup, Qt, QTimer, QEvent,
)
from PyQt6.QtWidgets import QApplication, QLabel

SHOW_DELAY_MS = 450
IN_MS = 140
OUT_MS = 120
MAX_W = 360

_manager = None


class TipManager(QObject):
    """Owns one floating tip label; installed as an app event filter."""

    def __init__(self, app: QApplication, parent=None,
                 show_delay_ms: int = SHOW_DELAY_MS):
        super().__init__(app)
        self._app = app
        self._show_delay_ms = show_delay_ms
        self._pending_text = ""
        self._show_timer = QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.timeout.connect(self._show)
        self._anim = None

        from .scaling import sp
        tip = QLabel(parent)
        tip.setObjectName("poise-tip")
        tip.setWindowFlags(Qt.WindowType.ToolTip)
        tip.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        tip.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        tip.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        tip.setWordWrap(True)
        tip.setMaximumWidth(sp(MAX_W))
        tip.hide()
        self._tip = tip
        app.installEventFilter(self)

    # -- event filter -------------------------------------------------------
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        try:
            kind = event.type()
            if kind == QEvent.Type.ToolTip:
                try:
                    from PyQt6.QtWidgets import QWidget as _W
                    text = watched.toolTip() if isinstance(
                        watched, _W) else ""
                except Exception:
                    text = ""
                if text:
                    self._arm(text)
                    try:
                        event.accept()
                    except Exception:
                        pass
                    return True
                self._hide_tip()
                return False
            if kind in (QEvent.Type.MouseButtonPress,
                        QEvent.Type.KeyPress,
                        QEvent.Type.Wheel,
                        QEvent.Type.FocusOut,
                        QEvent.Type.WindowDeactivate,
                        QEvent.Type.Leave):
                self._hide_tip(cancel_armed=True)
        except Exception:
            pass
        return False

    # -- show / hide ----------------------------------------------------------
    def _arm(self, text: str) -> None:
        self._hide_tip(cancel_armed=True)
        self._pending_text = text
        self._show_timer.start(self._show_delay_ms)

    def _stop_anim(self) -> None:
        try:
            if self._anim is not None:
                try:
                    self._anim.stop()
                except Exception:
                    pass
                self._anim = None
        except Exception:
            pass

    def _motion_ok(self) -> bool:
        try:
            from .animations import motion_ok
            return bool(motion_ok())
        except Exception:
            return False

    def _place(self) -> QPoint:
        from PyQt6.QtGui import QCursor
        pos = QCursor.pos()
        try:
            screen = self._app.screenAt(pos)
            if screen is None:
                screen = self._app.primaryScreen()
            avail = screen.availableGeometry() if screen else None
        except Exception:
            avail = None
        self._tip.adjustSize()
        size = self._tip.sizeHint()
        x, y = pos.x() + 14, pos.y() + 20
        if avail is not None:
            if x + size.width() > avail.right():
                x = max(avail.left(), avail.right() - size.width())
            if y + size.height() > avail.bottom():
                y = pos.y() - size.height() - 10
            x = max(avail.left(), x)
            y = max(avail.top(), y)
        return QPoint(x, y)

    def _show(self) -> None:
        text = self._pending_text
        self._pending_text = ""
        if not text:
            return
        try:
            self._stop_anim()
            self._tip.setText(text)
            target = self._place()
            self._tip.move(target)
            if not self._motion_ok():
                self._tip.setWindowOpacity(1.0)
                self._tip.show()
                return
            self._tip.setWindowOpacity(0.0)
            self._tip.show()
            group = QParallelAnimationGroup(self)
            curve = QEasingCurve(QEasingCurve.Type.OutCubic)
            fade = QPropertyAnimation(self._tip, b"windowOpacity", self)
            fade.setDuration(IN_MS)
            fade.setStartValue(0.0)
            fade.setEndValue(1.0)
            fade.setEasingCurve(curve)
            group.addAnimation(fade)
            rise = QPropertyAnimation(self._tip, b"pos", self)
            rise.setDuration(IN_MS)
            rise.setStartValue(QPoint(target.x(), target.y() + 6))
            rise.setEndValue(target)
            rise.setEasingCurve(curve)
            group.addAnimation(rise)
            self._anim = group
            group.start()
        except Exception:
            pass

    def _hide_tip(self, cancel_armed: bool = False) -> None:
        try:
            if cancel_armed:
                try:
                    self._show_timer.stop()
                except Exception:
                    pass
                self._pending_text = ""
            self._stop_anim()
            try:
                visible = self._tip.isVisible()
            except Exception:
                return
            if not visible:
                return
            if not self._motion_ok():
                self._tip.hide()
                return

            def _done() -> None:
                try:
                    if self._anim is not None:
                        return
                    self._tip.hide()
                    try:
                        self._tip.setWindowOpacity(1.0)
                    except Exception:
                        pass
                except Exception:
                    pass

            fade = QPropertyAnimation(self._tip, b"windowOpacity", self)
            fade.setDuration(OUT_MS)
            try:
                fade.setStartValue(float(self._tip.windowOpacity()))
            except Exception:
                fade.setStartValue(1.0)
            fade.setEndValue(0.0)
            fade.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._anim = fade
            try:
                fade.finished.connect(
                    lambda: (setattr(self, "_anim", None), _done()))
            except Exception:
                pass
            fade.start()
        except Exception:
            pass


def install_tooltips(app: QApplication, parent=None) -> TipManager:
    """Install the app-wide animated tooltip manager (singleton)."""
    global _manager
    if _manager is None:
        _manager = TipManager(app, parent)
    return _manager
