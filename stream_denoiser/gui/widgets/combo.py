"""
Poise Voice Isolator - Animated Dropdown (QComboBox)

QComboBox with a properly dark popup and Apple-style open/close motion:

- The popup's outer container is an internal Qt class no QSS selector
  can reach, so it stays default-white (the white bars framing every
  popup). It is painted dark here in code via palette — no fragile
  class-name selectors, no cascade risk to the styled list inside.
- Opening fades the popup in while it settles 8px from the combo edge
  (direction-aware: rises when opening below, falls when flipped
  above), ~160ms OutCubic. Closing fades out fast, then hides.
- Reduced motion, offscreen platform, or any failure degrades to the
  stock instant popup. Rapid re-clicks retarget cleanly.

Usage: drop in wherever QComboBox was used; objectName-driven QSS
("device-combo" / "settings-combo") keeps working unchanged.
"""
from PyQt6.QtWidgets import QComboBox, QListView, QStyledItemDelegate
from PyQt6.QtCore import (
    QEasingCurve, QPoint, QPropertyAnimation,
    QParallelAnimationGroup, QSize, Qt,
)
from PyQt6.QtGui import QColor, QPalette, QPen

from ..scaling import sp
from ..themes import current as current_theme


OPEN_MS = 160
CLOSE_MS = 110
SLIDE_PX = 8
POPUP_GAP = -6  # slight overlap: popup tucks under the button edge


def _supports_window_fade() -> bool:
    """windowOpacity only where the platform honors it (not offscreen)."""
    try:
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        return app is not None and app.platformName() != "offscreen"
    except Exception:
        return False


class PopupItemDelegate(QStyledItemDelegate):
    """Paints dropdown rows directly: QSS ::item rules don't reach combo
    popup views on any selector, so spacing, dividers, and row states
    live here in paint code (like the rest of the app's widgets)."""

    ROW_H = 40
    DIVIDER_ALPHA = 0.20  # stats-like divider, quieter

    def sizeHint(self, option, index):  # noqa: N802 (Qt override)
        hint = super().sizeHint(option, index)
        hint.setHeight(max(hint.height(), sp(self.ROW_H)))
        return hint

    def paint(self, painter, option, index):  # noqa: N802 (Qt override)
        from PyQt6.QtWidgets import QStyle
        palette = current_theme()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        painter.save()
        try:
            rect = option.rect
            if selected:
                painter.fillRect(rect, QColor(palette["accent"]))
                text_color = QColor(palette["bg"])
            else:
                if hovered:
                    wash = QColor(palette["accent"])
                    wash.setAlphaF(0.12)
                    painter.fillRect(rect, wash)
                text_color = QColor(palette["text"])

            # Label with breathing room, elided to the row.
            pad_h, pad_v = sp(12), sp(6)
            text_rect = rect.adjusted(pad_h, pad_v, -pad_h, -pad_v)
            text = index.data(Qt.ItemDataRole.DisplayRole) or ""
            elided = option.fontMetrics.elidedText(
                str(text), Qt.TextElideMode.ElideRight, text_rect.width())
            painter.setPen(text_color)
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                elided)

            # Hairline divider under every row but the last.
            try:
                model = index.model()
                last = model is not None and index.row() >= model.rowCount() - 1
            except Exception:
                last = True
            if not last:
                try:
                    r, g, b = (int(c) for c in
                               palette["divider_rgb"].split(","))
                except Exception:
                    r, g, b = (148, 163, 184)
                div = QColor(r, g, b)
                div.setAlphaF(self.DIVIDER_ALPHA)
                painter.setPen(QPen(div, 1))
                y = rect.bottom()
                painter.drawLine(rect.left() + pad_h, y,
                                 rect.right() - pad_h, y)
        finally:
            painter.restore()


class AnimatedComboBox(QComboBox):
    """QComboBox with dark container paint + fade/slide popup motion."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pop_anim = None
        # Own the popup view from construction so the row delegate (and
        # hover tracking) is in place before the first open.
        try:
            view = QListView(self)
            view.setMouseTracking(True)
            view.setUniformItemSizes(False)
            view.setItemDelegate(PopupItemDelegate(view))
            self.setView(view)
        except Exception:
            pass

    # -- popup container -------------------------------------------------
    @staticmethod
    def _popup_window(combo: "AnimatedComboBox"):
        try:
            view = combo.view()
            win = view.window() if view is not None else None
            return win
        except Exception:
            return None

    def _paint_popup_container(self) -> None:
        """Kill the unstyled popup frame (white bars) and paint it dark.

        Three things the naive approaches miss, all learned empirically:
        - stylesheets do not cascade into top-level popup windows, so the
          container gets its OWN tiny stylesheet here (an objectName +
          app-sheet rule demonstrably never matches it);
        - the container also ignores palette auto-fill, so that alone
          is not enough either;
        - NoFrame removes the native panel border that QSS can't reach.
        """
        try:
            from PyQt6.QtWidgets import QFrame
            win = self._popup_window(self)
            if win is None:
                return
            if isinstance(win, QFrame):
                try:
                    win.setFrameShape(QFrame.Shape.NoFrame)
                    win.setLineWidth(0)
                except Exception:
                    pass
            try:
                pill = current_theme()["pill"]
                win.setStyleSheet(
                    f"background-color: {pill}; border: none;")
            except Exception:
                pass
            try:
                pal = win.palette()
                pal.setColor(QPalette.ColorRole.Window,
                             QColor(current_theme()["pill"]))
                win.setPalette(pal)
                win.setAutoFillBackground(True)
            except Exception:
                pass
        except Exception:
            pass

    # -- motion ------------------------------------------------------------
    def _stop_pop_anim(self) -> None:
        try:
            if self._pop_anim is not None:
                try:
                    self._pop_anim.stop()
                except Exception:
                    pass
                self._pop_anim = None
            win = self._popup_window(self)
            if win is not None and win.isVisible():
                try:
                    win.setWindowOpacity(1.0)
                except Exception:
                    pass
        except Exception:
            pass

    def _place_popup(self) -> None:
        """Pin the popup directly under the button (menu-style).

        Qt's default parks the popup over the button, centered on the
        selected row. Dropdowns should hang below instead; flip above
        only when there is no room. Horizontal placement is left to Qt.
        Runs always (positioning, not motion).
        """
        try:
            from PyQt6.QtWidgets import QApplication
            win = self._popup_window(self)
            if win is None:
                return
            top = self.mapToGlobal(self.rect().topLeft()).y()
            bottom = self.mapToGlobal(self.rect().bottomLeft()).y()
            size = win.size()
            try:
                screen = QApplication.screenAt(
                    self.mapToGlobal(self.rect().center()))
                if screen is None:
                    screen = QApplication.primaryScreen()
                avail = screen.availableGeometry() if screen else None
            except Exception:
                avail = None
            x = win.pos().x()
            below_y = bottom + 1 + POPUP_GAP
            if avail is None or below_y + size.height() <= avail.bottom() + 1:
                win.move(x, below_y)
                return
            above_y = top - size.height() - POPUP_GAP
            if above_y >= avail.top():
                win.move(x, above_y)
            # Else the screen fits neither: keep Qt's position.
        except Exception:
            pass

    def _motion_ok(self) -> bool:
        try:
            from ..animations import motion_ok
            return bool(motion_ok()) and _supports_window_fade()
        except Exception:
            return False

    def showPopup(self):  # noqa: N802 (Qt override)
        self._stop_pop_anim()
        super().showPopup()
        try:
            self._paint_popup_container()
            self._place_popup()
            if not self._motion_ok():
                return
            win = self._popup_window(self)
            if win is None or not win.isVisible():
                return
            rest = win.pos()
            # Settle from the combo edge: rise when opening below it,
            # fall when Qt flipped the popup above it.
            try:
                combo_bottom = self.mapToGlobal(
                    QPoint(0, self.height())).y()
                below = win.pos().y() >= combo_bottom - 4
            except Exception:
                below = True
            start = QPoint(rest.x(), rest.y() + (SLIDE_PX if below else -SLIDE_PX))

            group = QParallelAnimationGroup(self)
            curve = QEasingCurve(QEasingCurve.Type.OutCubic)

            try:
                win.setWindowOpacity(0.0)
                fade = QPropertyAnimation(win, b"windowOpacity", self)
                fade.setDuration(OPEN_MS)
                fade.setStartValue(0.0)
                fade.setEndValue(1.0)
                fade.setEasingCurve(curve)
                group.addAnimation(fade)
            except Exception:
                pass
            try:
                slide = QPropertyAnimation(win, b"pos", self)
                slide.setDuration(OPEN_MS)
                slide.setStartValue(start)
                slide.setEndValue(rest)
                slide.setEasingCurve(curve)
                group.addAnimation(slide)
            except Exception:
                pass
            if group.animationCount() == 0:
                try:
                    win.setWindowOpacity(1.0)
                except Exception:
                    pass
                return

            state = {"group": group, "win": win}
            self._pop_anim = group

            def _done() -> None:
                try:
                    if self._pop_anim is not group:
                        return
                    self._pop_anim = None
                    try:
                        # Re-pin: correct anything that drifted mid-flight.
                        self._place_popup()
                        if win.isVisible():
                            win.setWindowOpacity(1.0)
                    except Exception:
                        pass
                except Exception:
                    pass

            try:
                group.finished.connect(_done)
            except Exception:
                pass
            group.start()
        except Exception:
            pass

    def hidePopup(self):  # noqa: N802 (Qt override)
        try:
            win = self._popup_window(self)
            if (self._motion_ok() and win is not None
                    and win.isVisible()):
                self._stop_pop_anim()
                try:
                    start_opacity = 1.0
                    try:
                        start_opacity = float(win.windowOpacity())
                    except Exception:
                        pass
                    fade = QPropertyAnimation(win, b"windowOpacity", self)
                    fade.setDuration(CLOSE_MS)
                    fade.setStartValue(start_opacity)
                    fade.setEndValue(0.0)
                    fade.setEasingCurve(
                        QEasingCurve.Type.OutCubic)
                    self._pop_anim = fade

                    def _done_close() -> None:
                        try:
                            if self._pop_anim is not fade:
                                return
                            self._pop_anim = None
                        except Exception:
                            pass
                        try:
                            super(AnimatedComboBox, self).hidePopup()
                        except Exception:
                            pass
                        try:
                            if win.isVisible():
                                win.setWindowOpacity(1.0)
                        except Exception:
                            pass

                    try:
                        fade.finished.connect(_done_close)
                    except Exception:
                        pass
                    fade.start()
                    return
                except Exception:
                    pass
        except Exception:
            pass
        try:
            self._stop_pop_anim()
        except Exception:
            pass
        super().hidePopup()
