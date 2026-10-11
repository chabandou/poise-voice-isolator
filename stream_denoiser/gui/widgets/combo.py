"""
Poise Voice Isolator - Animated Dropdown (QComboBox)

QComboBox with a properly dark popup and Apple-style open/close motion:

- The popup's outer container is an internal Qt class the app stylesheet
  cannot reach, so it stays default-white (the white bars framing every
  popup). It is styled here in code: its own tiny sheet (card colour,
  hairline border, rounded corners over a translucent window) plus the
  pill palette as the fallback where translucency is unavailable.
- Rows are painted by PopupItemDelegate: a soft accent wash fading out to
  the right on hover (same shape as the sidebar/Settings highlights) and
  a diamond marking the current choice, so hover never looks like
  selection.
- Opening fades the popup in while it settles 8px from the combo edge
  (direction-aware: rises when opening below, falls when flipped
  above), ~160ms OutCubic. Closing fades out fast, then hides.
- Reduced motion, offscreen platform, or any failure degrades to the
  stock instant popup. Rapid re-clicks retarget cleanly.

Usage: drop in wherever QComboBox was used; objectName-driven QSS
("device-combo" / "settings-combo") keeps working unchanged.
"""
from PyQt6.QtWidgets import (
    QComboBox, QListView, QStyledItemDelegate, QWidget,
)
from PyQt6.QtCore import (
    QEasingCurve, QPoint, QPropertyAnimation,
    QParallelAnimationGroup, QSize, Qt,
)
from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtGui import (
    QColor, QLinearGradient, QPainter, QPainterPath, QPalette,
)

from ..scaling import sp
from ..themes import current as current_theme


OPEN_MS = 160
CLOSE_MS = 110
SLIDE_PX = 8
POPUP_GAP = -6  # slight overlap: popup tucks under the button edge
POPUP_PAD = 6   # padding between the border and the rows (design px)
POPUP_RADIUS = 12
ROW_RADIUS = 8


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
    popup views on any selector, so spacing and row states live here in
    paint code (like the rest of the app's widgets).

    Highlight (hover / keyboard) is a rounded wash fading to the right;
    the current choice carries a small diamond in the secondary colour.
    """

    ROW_H = 40
    WASH_ALPHA = 0.20

    def __init__(self, parent=None, combo=None):
        super().__init__(parent)
        self._combo = combo

    def sizeHint(self, option, index):  # noqa: N802 (Qt override)
        hint = super().sizeHint(option, index)
        # Fixed row height: the popup is sized from it, and font-driven
        # variation would make the list height (and scrolling) unstable.
        hint.setHeight(sp(self.ROW_H))
        return hint

    def _is_current(self, index) -> bool:
        try:
            return (self._combo is not None
                    and index.row() == self._combo.currentIndex())
        except Exception:
            return False

    def paint(self, painter, option, index):  # noqa: N802 (Qt override)
        from PyQt6.QtWidgets import QStyle
        palette = current_theme()
        lit = bool(option.state & (QStyle.StateFlag.State_Selected
                                   | QStyle.StateFlag.State_MouseOver))

        painter.save()
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            row = QRectF(option.rect).adjusted(0, sp(2), 0, -sp(2))

            if lit:
                accent = QColor(palette["accent"])
                wash = QLinearGradient(row.left(), 0,
                                       row.left() + row.width() * 0.92, 0)
                start = QColor(accent)
                start.setAlphaF(self.WASH_ALPHA)
                end = QColor(accent)
                end.setAlphaF(0.0)
                wash.setColorAt(0.0, start)
                wash.setColorAt(1.0, end)
                shape = QPainterPath()
                shape.addRoundedRect(row, sp(ROW_RADIUS), sp(ROW_RADIUS))
                painter.fillPath(shape, wash)

            # Current choice: diamond in the secondary colour.
            pad_h = sp(14)
            if self._is_current(index):
                d = sp(4)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(palette["secondary"]))
                painter.translate(QPointF(row.left() + pad_h, row.center().y()))
                painter.rotate(45)
                painter.drawRoundedRect(QRectF(-d, -d, 2 * d, 2 * d), 1.5, 1.5)
                painter.resetTransform()

            # Label, always indented past the marker slot so rows align.
            text_left = pad_h + sp(18)
            text_rect = row.adjusted(text_left, 0, -sp(12), 0).toRect()
            text = index.data(Qt.ItemDataRole.DisplayRole) or ""
            elided = option.fontMetrics.elidedText(
                str(text), Qt.TextElideMode.ElideRight, text_rect.width())
            painter.setPen(QColor(palette["text"]))
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                elided)
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
            view.setItemDelegate(PopupItemDelegate(view, combo=self))
            self.setView(view)
        except Exception:
            pass
        self._prepare_popup_container()

    # -- popup container -------------------------------------------------
    @staticmethod
    def _popup_window(combo: "AnimatedComboBox"):
        try:
            view = combo.view()
            win = view.window() if view is not None else None
            return win
        except Exception:
            return None

    def _prepare_popup_container(self) -> None:
        """One-time window setup (before the popup is first shown).

        Rounded corners need a translucent window, and a translucent
        popup must not get the system's rectangular drop shadow.
        """
        try:
            win = self._popup_window(self)
            if win is None:
                return
            win.setObjectName("poise-popup")
            win.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
            win.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            # Qt's up/down scroller strips are unstyleable (plain white
            # bars) and steal row height; collapse them and let the list
            # use a regular, themed scrollbar when it must scroll.
            view = self.view()
            for child in win.findChildren(
                    QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly):
                if child is not view:
                    child.setFixedHeight(0)
            if view is not None:
                view.setVerticalScrollBarPolicy(
                    Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        except Exception:
            pass

    def _paint_popup_container(self) -> None:
        """Style the unstyled popup frame (white bars) per theme.

        Learned empirically:
        - stylesheets do not cascade into top-level popup windows, so the
          container gets its OWN stylesheet here (scoped by objectName so
          it never leaks to the list or scrollbars inside);
        - the pill palette stays as the fallback fill for platforms that
          ignore translucency (square corners, but never white);
        - the frame must be a StyledPanel for the QSS border to paint.
        """
        try:
            from PyQt6.QtWidgets import QFrame
            win = self._popup_window(self)
            if win is None:
                return
            palette = current_theme()
            if isinstance(win, QFrame):
                try:
                    win.setFrameShape(QFrame.Shape.StyledPanel)
                    win.setLineWidth(0)
                except Exception:
                    pass
            try:
                win.setStyleSheet(
                    "QFrame#poise-popup {"
                    f" background-color: {palette['card']};"
                    f" border: 1px solid rgba({palette['border_rgb']},"
                    f" {palette['border_alpha']});"
                    f" border-radius: {sp(POPUP_RADIUS)}px; }}"
                    "QListView { background: transparent; border: none;"
                    " padding: 0px; outline: none; }")
            except Exception:
                pass
            try:
                pal = win.palette()
                pal.setColor(QPalette.ColorRole.Window,
                             QColor(palette["pill"]))
                win.setPalette(pal)
                win.setAutoFillBackground(False)
            except Exception:
                pass
            try:
                layout = win.layout()
                if layout is not None:
                    pad = sp(POPUP_PAD)
                    layout.setContentsMargins(pad, pad, pad, pad)
            except Exception:
                pass
        except Exception:
            pass

    def _fit_popup(self) -> None:
        """Size the popup to its rows plus padding and border.

        Qt sizes the container for its own (unpadded) layout, so after
        the padding/border are applied the height is recomputed here.
        """
        try:
            win = self._popup_window(self)
            view = self.view()
            if win is None or view is None:
                return
            rows = min(self.count(), max(1, self.maxVisibleItems()))
            rows_h = sum(view.sizeHintForRow(i) for i in range(rows))
            chrome = 2 * (sp(POPUP_PAD) + 1)
            win.resize(max(win.width(), self.width()), rows_h + chrome)
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
        self._paint_popup_container()
        super().showPopup()
        try:
            self._paint_popup_container()
            self._fit_popup()
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
