"""
Poise Voice Isolator - Card Dropdown (QComboBox)

A QComboBox whose list opens as a stack of option cards, the same cards
Settings uses for the models: a name over a blurb, the current choice in
a gold-edged tint with a diamond. Qt's own popup cannot be styled that
far (its container is private, and QSS ::item never reaches it), so
showPopup()/hidePopup() open CardPopup instead. The combo keeps its
model, current index and signals, so callers use it as a QComboBox.

Rows: DisplayRole is the closed combo's text; TITLE_ROLE and BLURB_ROLE
(both optional) give the card's name and blurb.

Motion (all painted, so it looks the same on every platform):
- opening fades the panel (cards and all) in while it rises SLIDE_PX
  into place and grows from START_SCALE, out of the edge nearest the
  button. Widgets can't be scaled, so the entrance paints a snapshot
  of the finished panel; the live panel takes over at rest, on the
  same pixels;
- closing plays the opening backwards at the same speed (fades, sinks
  and shrinks toward the button), in a click-through ghost window
  holding a snapshot, so the real popup closes at once and Qt's
  click-outside handling (replaying the click) stays intact;
- the chevron turns over as the list opens and back as it closes;
- the button's gold ring glides in on hover and stays while open.
Reduced motion (POISE_NO_ANIM / POISE_REDUCE_MOTION) snaps.

Flicker guards (each one was a visible flash, measured on Windows):
- the cards are kept between opens and only rebuilt when the list
  changes: cards queued for deletion still painted, at full opacity, in
  a reopen's first frame;
- a shown window takes ~35-70 ms to reach the screen (a repaint of a
  visible one, ~1 frame). So the fade's clock starts only once the
  popup is exposed, after a short hold at zero (else its quick first
  half is never seen and the panel pops in), and the ghost is shown,
  empty, while the list opens, so closing only repaints it (else a
  frame shows neither);
- the popup paints itself empty before hiding (a translucent window
  reshows its last frame);
- a pick plays Settings' switch (the gold edge, tint and diamond glide
  from the old card to the new one, SWITCH_MS) and closes only once it
  lands; anything that closes the list mid-switch snaps the cards to
  the new choice first (mid-glide, the snapshot showed the old one);
- Windows' own show/hide transitions are off for the popup and ghost;
- the ring is painted, not a QSS :hover rule: the popup takes the mouse,
  so the button loses hover while open, and Qt only gives it back on
  the next mouse move after the popup closes (the ring dropped out on
  every click). The ring follows open-or-hovered, and on close counts
  the pointer as over the button until it really leaves.

The wheel scrolls the page, not the choice (see wheelEvent).
"""
import math
import time

from PyQt6.QtWidgets import (
    QApplication, QComboBox, QScrollArea, QStyle, QStyleOptionComboBox,
    QVBoxLayout, QWidget,
)
from PyQt6.QtCore import (
    QEasingCurve, QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt,
    QTimer, QVariantAnimation,
)
from PyQt6.QtGui import (
    QColor, QCursor, QFont, QFontMetrics, QPainter, QPainterPath, QPen,
    QPixmap, QRegion,
)

from ..animations import Blend, mix_rgba, motion_ok
from ..scaling import sp, ui_scale
from ..themes import current as current_theme


TITLE_ROLE = Qt.ItemDataRole.UserRole + 1   # card name (else the text)
BLURB_ROLE = Qt.ItemDataRole.UserRole + 2   # line(s) under the name

OPEN_MS = 220       # panel fade + rise
SWITCH_MS = 200     # a pick's glide between cards (as on Settings' cards)
SWITCH_HOLD_MS = 90  # the new choice rests on screen before closing
OPEN_HOLD_MS = 16   # held at zero once exposed: a frame to reach screen
CLOSE_MS = OPEN_MS  # the close is the opening played backwards
SLIDE_PX = 10       # panel rise (design px)
START_SCALE = 0.95  # panel grows from this as it opens
POPUP_GAP = 6       # between the button and the panel (design px)
PANEL_PAD = 10      # panel border to cards (design px)
PANEL_RADIUS = 16
CARD_SPACING = 8
CARD_RADIUS = 12
SHADOW = 18         # soft shadow room around the panel (design px)
MAX_VISIBLE = 5     # cards shown before the list scrolls
# Theme fills: panel behind the cards, and the cards' rest fill (the same
# pair as Settings' model cards).
PANEL_FILL = "card"
CARD_FILL = "pill"

_RISE = QEasingCurve(QEasingCurve.Type.OutCubic)
_FADE = QEasingCurve(QEasingCurve.Type.OutQuad)


def _entrance_frame(t: float):
    """(opacity, scale, lift px) at linear entrance progress t: the open
    runs t 0->1, the close the same frames 1->0."""
    t = max(0.0, min(1.0, t))
    rise = _RISE.valueForProgress(t)
    return (_FADE.valueForProgress(t),
            START_SCALE + (1.0 - START_SCALE) * rise,
            (1.0 - rise) * sp(SLIDE_PX))


def _no_system_transitions(widget: QWidget) -> None:
    """Turn off DWM's show/hide animation for a top-level window: it
    fades popups on its own schedule, against ours."""
    import sys
    if sys.platform != "win32":
        return
    try:
        import ctypes
        DWMWA_TRANSITIONS_FORCEDISABLED = 3
        on = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(int(widget.winId())),
            DWMWA_TRANSITIONS_FORCEDISABLED, ctypes.byref(on),
            ctypes.sizeof(on))
    except Exception:
        pass


def _border_rest() -> QColor:
    color = QColor(148, 163, 184)
    color.setAlphaF(0.18)
    return color


# -- cards --------------------------------------------------------------------
class _OptionCard(QWidget):
    """One choice, painted like Settings' model cards: name over blurb,
    border and fill gliding between rest, active (hover/keys) and the
    current choice, which also carries the diamond."""

    PAD_L, PAD_R, PAD_V = 20, 52, 13   # right: room for the diamond
    NAME_PX, BLURB_PX = 20, 14
    MIN_H = 62
    BLURB_LINES = 2

    def __init__(self, popup: "CardPopup", row: int, title: str, blurb: str,
                 current: bool):
        super().__init__()
        self._popup = popup
        self.row = row
        self.title = title
        self.blurb = blurb
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._hover = Blend(self, self.update, 150)
        self._check = Blend(self, self.update, SWITCH_MS,
                            value=1.0 if current else 0.0)

        self._name_font = QFont()
        self._name_font.setFamilies(_heading_families())
        self._name_font.setPixelSize(sp(self.NAME_PX))
        self._name_font.setWeight(QFont.Weight.Bold)
        self._blurb_font = QFont()
        self._blurb_font.setFamilies(["Segoe UI", "Inter"])
        self._blurb_font.setPixelSize(sp(self.BLURB_PX))

    # -- size ------------------------------------------------------------
    def _text_width(self, width: int) -> int:
        return max(sp(40), width - sp(self.PAD_L) - sp(self.PAD_R))

    def _blurb_height(self, width: int) -> int:
        if not self.blurb:
            return 0
        fm = QFontMetrics(self._blurb_font)
        box = fm.boundingRect(
            QRect(0, 0, self._text_width(width), 10000),
            int(Qt.TextFlag.TextWordWrap), self.blurb)
        return min(box.height(), fm.lineSpacing() * self.BLURB_LINES)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 (Qt override)
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 (Qt override)
        name_h = QFontMetrics(self._name_font).height()
        blurb_h = self._blurb_height(width)
        gap = sp(2) if blurb_h else 0
        return max(sp(self.MIN_H), 2 * sp(self.PAD_V) + name_h + gap + blurb_h)

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt override)
        width = max(self.width(), sp(300))
        return QSize(width, self.heightForWidth(width))

    # -- state -----------------------------------------------------------
    def set_active(self, active: bool, animated: bool = True) -> None:
        if animated and motion_ok():
            self._hover.set_target(1.0 if active else 0.0)
        else:
            self._hover.snap(1.0 if active else 0.0)

    def set_current(self, current: bool, animated: bool = True) -> None:
        value = 1.0 if current else 0.0
        if animated and motion_ok() and self.isVisible():
            self._check.set_target(value)
        else:
            # snap(), not set_target(animated=False): that returns early
            # when a glide is already heading there, leaving it running.
            self._check.snap(value)

    # -- input -----------------------------------------------------------
    def enterEvent(self, event):  # noqa: N802 (Qt override)
        if not self._popup.switching:
            self._popup.set_active(self.row, ensure_visible=False)
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802 (Qt override)
        # Unhovered: the highlight goes (unless keys moved it elsewhere).
        if not self._popup.switching and self._popup.active_row == self.row:
            self._popup.set_active(None, ensure_visible=False)
        super().leaveEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802 (Qt override)
        # Keys may have moved the highlight while the pointer rested here.
        if (not self._popup.switching
                and self._popup.active_row != self.row):
            self._popup.set_active(self.row, ensure_visible=False)
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):  # noqa: N802 (Qt override)
        event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802 (Qt override)
        if (event.button() == Qt.MouseButton.LeftButton
                and self.rect().contains(event.position().toPoint())):
            self._popup.choose(self.row)
        event.accept()

    # -- paint -----------------------------------------------------------
    def paintEvent(self, event):  # noqa: N802 (Qt override)
        # Cards fade with the panel (its opacity is painted, not an effect).
        opacity = self._popup.panel.opacity
        if opacity <= 0.001:
            return
        palette = current_theme()
        hover, check = self._hover.value, self._check.value
        secondary = QColor(palette["secondary"])
        w, h = self.width(), self.height()

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setOpacity(opacity)

        rect = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
        radius = float(sp(CARD_RADIUS))
        base = QColor(palette[CARD_FILL])
        # Active rows lift a touch toward the gold tint; the current one
        # takes the full tint (as on Settings' cards).
        tint = mix_rgba(base, secondary, 0.08)
        fill = mix_rgba(base, tint, max(check, 0.45 * hover))
        hover_edge = QColor(secondary)
        hover_edge.setAlphaF(0.6)
        edge = mix_rgba(mix_rgba(_border_rest(), hover_edge, hover),
                        secondary, check)
        p.setPen(QPen(edge, 1.0))
        p.setBrush(fill)
        p.drawRoundedRect(rect, radius, radius)

        left = sp(self.PAD_L)
        text_w = self._text_width(w)
        name_h = QFontMetrics(self._name_font).height()
        blurb_h = self._blurb_height(w)
        gap = sp(2) if blurb_h else 0
        top = (h - (name_h + gap + blurb_h)) / 2.0

        p.setFont(self._name_font)
        p.setPen(QColor(palette["text"]))
        name = QFontMetrics(self._name_font).elidedText(
            self.title, Qt.TextElideMode.ElideRight, text_w)
        p.drawText(QRectF(left, top, text_w, name_h),
                   int(Qt.AlignmentFlag.AlignLeft
                       | Qt.AlignmentFlag.AlignVCenter), name)
        if blurb_h:
            p.setFont(self._blurb_font)
            p.setPen(QColor(palette["muted"]))
            p.drawText(QRectF(left, top + name_h + gap, text_w, blurb_h),
                       int(Qt.AlignmentFlag.AlignLeft
                           | Qt.AlignmentFlag.AlignTop
                           | Qt.TextFlag.TextWordWrap), self.blurb)

        if check > 0.01:
            marker = QColor(secondary)
            marker.setAlphaF(check)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(marker)
            d = sp(7) * (0.6 + 0.4 * check)
            p.translate(QPointF(w - sp(28), h / 2.0))
            p.rotate(45)
            p.drawRoundedRect(QRectF(-d, -d, 2 * d, 2 * d), 2, 2)
        p.end()


def _heading_families():
    try:
        from ..fonts import heading_family
        return [heading_family(), "Segoe UI", "Inter"]
    except Exception:
        return ["Segoe UI", "Inter"]


# -- panel --------------------------------------------------------------------
class _Panel(QWidget):
    """The popup's card surface; its children are the scroll area and
    the scroll hint. Opacity is painted (the entrance drives it)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.opacity = 1.0

    def paintEvent(self, event):  # noqa: N802 (Qt override)
        if self.opacity <= 0.001:
            return
        palette = current_theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self.opacity)
        border = QColor(*(int(v) for v in palette["border_rgb"].split(",")))
        border.setAlphaF(float(palette["border_alpha"]))
        p.setPen(QPen(border, 1.0))
        p.setBrush(QColor(palette[PANEL_FILL]))
        radius = float(sp(PANEL_RADIUS))
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1.0,
                                 self.height() - 1.0), radius, radius)
        p.end()


class _ScrollHint(QWidget):
    """A slim painted scroll thumb along the panel's right edge (the
    real scrollbar stays hidden: it can't fade with the panel). The
    wheel, keys and touchpad scroll the list."""

    def __init__(self, scroll: QScrollArea, panel: _Panel):
        super().__init__(panel)
        self._scroll = scroll
        self._panel = panel
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        bar = scroll.verticalScrollBar()
        bar.valueChanged.connect(self.update)
        bar.rangeChanged.connect(lambda *_: self.update())

    def paintEvent(self, event):  # noqa: N802 (Qt override)
        bar = self._scroll.verticalScrollBar()
        span = bar.maximum() - bar.minimum()
        if span <= 0 or self._panel.opacity <= 0.001:
            return
        track = self.height()
        page = bar.pageStep()
        thumb = max(sp(24), track * page / float(span + page))
        y = (track - thumb) * (bar.value() - bar.minimum()) / float(span)
        color = QColor(148, 163, 184)
        color.setAlphaF(0.35)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self._panel.opacity)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        r = self.width() / 2.0
        p.drawRoundedRect(QRectF(0, y, self.width(), thumb), r, r)
        p.end()


class _Ghost(QWidget):
    """Click-through stand-in for the closing popup: shown empty over
    it while the list opens (arm), then given a snapshot of the popup at
    rest to play the entrance backwards (fade_out), then emptied and
    hidden. One per combo, reused."""

    def __init__(self):
        super().__init__(None, Qt.WindowType.ToolTip
                         | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint
                         | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._pixmap = None
        self._t = 1.0           # entrance progress (linear), run down to 0
        self._anchor = QPointF()
        _no_system_transitions(self)
        # Linear clock: the entrance's own curves are applied in paint.
        anim = QVariantAnimation(self)
        anim.valueChanged.connect(self._step)
        anim.finished.connect(self._finish)
        self._anim = anim

    @property
    def fading(self) -> bool:
        return self._pixmap is not None

    def arm(self, geometry: QRect) -> None:
        """Be on screen (empty) before the popup closes."""
        self._anim.stop()
        self._pixmap = None
        self.setGeometry(geometry)
        if self.isVisible():
            self.repaint()
        else:
            self.show()

    def fade_out(self, pixmap, geometry: QRect, anchor: QPointF,
                 progress: float = 1.0) -> None:
        """Play the entrance backwards from `progress` (linear; less
        than 1 when closed mid-entrance) down to 0. `anchor` is the
        panel edge nearest the button, in this window's coordinates."""
        self._anim.stop()
        self._pixmap = pixmap
        self._anchor = QPointF(anchor)
        self._t = progress = max(0.0, min(1.0, progress))
        self._anim.setDuration(max(1, round(CLOSE_MS * progress)))
        self._anim.setStartValue(progress)
        self._anim.setEndValue(0.0)
        if self.geometry() != geometry:
            self.setGeometry(geometry)
        if not self.isVisible():
            self.show()     # not armed in time: late, but still fades
        # On screen in the same frame the popup empties itself.
        self.repaint()
        self._anim.start()

    def _finish(self) -> None:
        self._pixmap = None
        self.repaint()      # leave an empty last frame (see the popup)
        self.hide()

    def _step(self, value) -> None:
        self._t = float(value)
        self.update()

    def paintEvent(self, event):  # noqa: N802 (Qt override)
        if self._pixmap is None:
            return
        opacity, scale, lift = _entrance_frame(self._t)
        if opacity <= 0.001:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setOpacity(opacity)
        a = self._anchor
        p.translate(a.x(), a.y() + lift)
        p.scale(scale, scale)
        p.translate(-a.x(), -a.y())
        p.drawPixmap(QPointF(0, 0), self._pixmap)
        p.end()


# -- popup --------------------------------------------------------------------
class CardPopup(QWidget):
    """The open list: a top-level popup holding the panel, with room
    around it for the soft shadow and the entrance's rise."""

    def __init__(self, combo: "AnimatedComboBox"):
        super().__init__(combo, Qt.WindowType.Popup
                         | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self._combo = combo
        self.setObjectName("poise-card-popup")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # Nothing from the window's sheet may paint behind the cards.
        self.setStyleSheet(
            "QWidget#poise-card-popup, QScrollArea, QScrollArea > QWidget,"
            " QWidget#poise-card-list { background: transparent;"
            " border: none; }")
        self._cards = []
        self._stale = True      # rebuild the cards on the next open
        self.active_row = None
        self._opened_above = False
        self._anim = None
        self._await_expose = False   # entrance waits for the first frame
        self._still = None      # finished-panel snapshot drawn while entering
        self._switch = None     # QTimer closing the list after a pick's glide
        self._progress = 0.0    # linear entrance progress (1 at rest)
        self._frame = None      # (opacity, rise) of the entrance frame

        self._panel = _Panel(self)
        self._scroll = QScrollArea(self._panel)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.viewport().setAutoFillBackground(False)
        self._list = QWidget()
        self._list.setObjectName("poise-card-list")
        self._list.setAutoFillBackground(False)
        self._list_layout = QVBoxLayout(self._list)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(sp(CARD_SPACING))
        self._scroll.setWidget(self._list)
        self._hint = _ScrollHint(self._scroll, self._panel)
        _no_system_transitions(self)
        # Start empty: nothing to show before the first frame is painted.
        self._panel.opacity = 0.0
        self._rest = QPoint(0, 0)

    def mark_stale(self) -> None:
        """The combo's rows changed: rebuild the cards on the next open."""
        self._stale = True

    # -- content ---------------------------------------------------------
    @property
    def cards(self):
        return list(self._cards)

    @property
    def panel(self) -> QWidget:
        return self._panel

    def _rebuild(self) -> None:
        for card in self._cards:
            self._list_layout.removeWidget(card)
            # Hidden and detached now: a card waiting on deleteLater still
            # paints (at full strength) in the next open's first frame.
            card.hide()
            card.setParent(None)
            card.deleteLater()
        self._cards = []
        self._stale = False
        combo = self._combo
        current = combo.currentIndex()
        for row in range(combo.count()):
            text = combo.itemText(row)
            title = combo.itemData(row, TITLE_ROLE) or text
            blurb = combo.itemData(row, BLURB_ROLE) or ""
            card = _OptionCard(self, row, str(title), str(blurb),
                               row == current)
            self._cards.append(card)
            self._list_layout.addWidget(card)
        self.active_row = None

    def _layout_for(self, width: int, max_height: int) -> int:
        """Size cards for the panel width; return the panel height."""
        pad = sp(PANEL_PAD)
        inner = width - 2 * pad
        spacing = sp(CARD_SPACING)
        heights = [card.heightForWidth(inner) for card in self._cards]
        full = sum(heights) + spacing * max(0, len(heights) - 1)
        shown = heights[:MAX_VISIBLE]
        cap = sum(shown) + spacing * max(0, len(shown) - 1)
        if len(heights) > MAX_VISIBLE:
            # Show a sliver of the next card so the list reads as more.
            cap += spacing + min(heights[MAX_VISIBLE], sp(28))
        list_h = min(full, cap, max(sp(60), max_height - 2 * pad))
        return list_h + 2 * pad

    def _apply_geometry(self, panel_rect: QRect) -> None:
        """panel_rect is global; the window adds shadow room around it."""
        m = sp(SHADOW)
        self.setGeometry(panel_rect.adjusted(-m, -m, m, m))
        self._rest = QPoint(m, m)
        self._panel.setGeometry(QRect(self._rest, panel_rect.size()))
        pad = sp(PANEL_PAD)
        self._scroll.setGeometry(
            pad, pad, panel_rect.width() - 2 * pad,
            panel_rect.height() - 2 * pad)
        self._hint.setGeometry(panel_rect.width() - pad + sp(3), pad + sp(4),
                               sp(4), panel_rect.height() - 2 * pad - sp(8))
        self._hint.raise_()

    def _place(self) -> None:
        """Hang under the combo; flip above when there's no room below,
        and shrink (scrolling) when neither side fits everything."""
        combo = self._combo
        top_left = combo.mapToGlobal(QPoint(0, 0))
        width = combo.width()
        gap = sp(POPUP_GAP)
        below_y = top_left.y() + combo.height() + gap
        above_bottom = top_left.y() - gap
        avail = None
        try:
            screen = (QApplication.screenAt(combo.mapToGlobal(
                combo.rect().center())) or QApplication.primaryScreen())
            avail = screen.availableGeometry() if screen else None
        except Exception:
            avail = None
        if avail is None:
            height = self._layout_for(width, 10 ** 6)
            self._opened_above = False
            self._apply_geometry(QRect(top_left.x(), below_y, width, height))
            return
        margin = sp(8)
        room_below = avail.bottom() - margin - below_y
        room_above = above_bottom - avail.top() - margin
        natural = self._layout_for(width, 10 ** 6)
        if natural <= room_below or room_below >= room_above:
            height = min(natural, self._layout_for(width, room_below))
            y = below_y
            self._opened_above = False
        else:
            height = min(natural, self._layout_for(width, room_above))
            y = above_bottom - height
            self._opened_above = True
        x = max(avail.left() + margin,
                min(top_left.x(), avail.right() - margin - width))
        self._apply_geometry(QRect(x, y, width, height))

    # -- open / close ------------------------------------------------------
    def open(self) -> None:
        self._stop_anim()
        if self._stale or len(self._cards) != self._combo.count():
            self._rebuild()
        current = self._combo.currentIndex()
        for card in self._cards:
            card.set_current(card.row == current, animated=False)
        self.active_row = None
        self.set_active(current if 0 <= current < len(self._cards) else None,
                        ensure_visible=False, animated=False)
        self._place()
        animate = motion_ok()
        self._set_progress(0.0 if animate else None)
        if animate:
            self._combo._arm_ghost(self.geometry())
        self._await_expose = animate
        self.show()
        self.raise_()
        self.setFocus(Qt.FocusReason.PopupFocusReason)
        # Lay the cards out now, not in a posted event after the first
        # frame (they'd paint at stale sizes, then jump).
        self._list_layout.activate()
        if 0 <= current < len(self._cards):
            self._scroll.ensureWidgetVisible(
                self._cards[current], 0, sp(CARD_SPACING))
        if animate:
            self._snapshot_panel()
            # The clock starts from the first exposed frame (paintEvent);
            # this fallback covers a platform that never says so.
            QTimer.singleShot(120, self._start_entrance)

    def _snapshot_panel(self) -> None:
        """The panel as it will look at rest; the entrance scales it."""
        self._panel.opacity = 1.0
        try:
            # render(), not grab(): a child's grab fills its background,
            # which squares off the panel's round corners.
            dpr = self.devicePixelRatioF()
            size = self._panel.size()
            still = QPixmap(round(size.width() * dpr),
                            round(size.height() * dpr))
            still.setDevicePixelRatio(dpr)
            still.fill(Qt.GlobalColor.transparent)
            self._panel.render(still, QPoint(), QRegion(),
                               QWidget.RenderFlag.DrawChildren)
            self._still = still
        except Exception:
            self._still = None
        self._panel.opacity = 0.0

    def _start_entrance(self) -> None:
        """Panel (cards and all) fades in and rises into place. Held at
        zero for OPEN_HOLD_MS first: the window is only now reaching the
        screen."""
        if not self._await_expose or not self.isVisible():
            return
        self._await_expose = False
        self._combo._turn_chevron(True)
        total = OPEN_HOLD_MS + OPEN_MS
        fade = QEasingCurve(QEasingCurve.Type.OutQuad)
        anim = QVariantAnimation(self)
        anim.setDuration(total)
        anim.setStartValue(0.0)
        anim.setEndValue(float(total))
        anim.valueChanged.connect(
            lambda v: self._set_progress(
                max(0.0, (float(v) - OPEN_HOLD_MS) / OPEN_MS), fade))
        anim.finished.connect(lambda: self._set_progress(None))
        self._anim = anim
        anim.start()

    def _set_progress(self, t, fade=None) -> None:
        """Entrance frame at linear progress `t` (None: at rest). The
        rise and growth ease out cubically; the fade more gently
        (`fade`). While the snapshot is drawn the live panel stays
        empty, at rest."""
        self._panel.move(self._rest)
        if t is None:
            self._anim, self._still, self._frame = None, None, None
            self._panel.opacity = 1.0
            self._progress = 1.0
        else:
            t = min(1.0, t)
            self._progress = t
            opacity = fade.valueForProgress(t) if fade else t
            if self._still is not None:
                self._frame = (opacity, _RISE.valueForProgress(t))
                self._panel.opacity = 0.0
            else:
                self._frame = None
                self._panel.opacity = opacity
        self._panel.update()
        for card in self._cards:
            card.update()
        self._hint.update()
        self.update()

    @property
    def shown_opacity(self) -> float:
        """How opaque the list looks now (snapshot or live panel)."""
        if self._frame is not None:
            return self._frame[0]
        return self._panel.opacity

    def _stop_anim(self) -> None:
        self._await_expose = False
        if self._anim is not None:
            anim, self._anim = self._anim, None
            anim.stop()
            self._set_progress(None)

    def closeEvent(self, event):  # noqa: N802 (Qt override)
        """Every close (choice, Escape, a click outside) leaves a fading
        snapshot behind and hides the real popup at once."""
        if self._switch is not None:
            # Closed mid-switch: show the new choice, not the glide.
            self._switch.stop()
            self._switch = None
            self._snap_to(self._combo.currentIndex())
        if motion_ok() and self.isVisible() and self.shown_opacity > 0.05:
            try:
                # The ghost replays the entrance backwards from where it
                # is now (mid-entrance too: no jump), from a snapshot of
                # the popup at rest.
                progress = self._progress
                if self._anim is not None:
                    anim, self._anim = self._anim, None
                    anim.stop()
                self._set_progress(None)
                rest = QRectF(self._panel.geometry())
                anchor = QPointF(rest.center().x(),
                                 rest.bottom() if self._opened_above
                                 else rest.top())
                self._combo._ghost_out(self.grab(), self.geometry(),
                                       anchor, progress)
            except Exception:
                pass
        else:
            self._combo._disarm_ghost()
        self._await_expose = False
        if self._anim is not None:
            anim, self._anim = self._anim, None
            anim.stop()
        # Leave an empty last frame: a translucent window shows its last
        # frame for a moment when it is shown again.
        self._still, self._frame = None, None
        self._panel.opacity = 0.0
        if self.isVisible():
            self.repaint()
        super().closeEvent(event)

    def hideEvent(self, event):  # noqa: N802 (Qt override)
        super().hideEvent(event)
        self._combo._popup_closed()

    # -- choosing ----------------------------------------------------------
    def set_active(self, row, ensure_visible: bool = True,
                   animated: bool = True) -> None:
        if row == self.active_row:
            return
        for card in self._cards:
            card.set_active(card.row == row, animated=animated)
        self.active_row = row
        if ensure_visible and row is not None and 0 <= row < len(self._cards):
            self._scroll.ensureWidgetVisible(
                self._cards[row], 0, sp(CARD_SPACING))

    @property
    def switching(self) -> bool:
        """A pick's glide is playing (the list closes when it lands)."""
        return self._switch is not None

    def _snap_to(self, row: int) -> None:
        for card in self._cards:
            card.set_current(card.row == row, animated=False)
            card.set_active(card.row == row, animated=False)
        self.active_row = row

    def choose(self, row: int) -> None:
        """Pick `row`: the choice applies now; the cards play Settings'
        switch, then the list closes. Re-picking the current choice, or
        reduced motion, closes at once."""
        if self.switching:
            return
        changed = row != self._combo.currentIndex()
        self._combo._choose(row)
        if not changed or not motion_ok():
            self._snap_to(row)
            self.close()
            return
        self.set_active(row, ensure_visible=False)
        for card in self._cards:
            card.set_current(card.row == row)
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(self._switch_landed)
        self._switch = timer
        timer.start(SWITCH_MS + SWITCH_HOLD_MS)

    def _switch_landed(self) -> None:
        self._switch = None
        if self.isVisible():
            self.close()

    def keyPressEvent(self, event):  # noqa: N802 (Qt override)
        key = event.key()
        count = len(self._cards)
        row = self.active_row
        if self.switching and key not in (
                Qt.Key.Key_Escape, Qt.Key.Key_Tab, Qt.Key.Key_Backtab,
                Qt.Key.Key_F4):
            return              # let the pick's glide finish
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Up) and count:
            step = 1 if key == Qt.Key.Key_Down else -1
            start = self._combo.currentIndex() if row is None else row
            self.set_active(max(0, min(count - 1, start + step)))
        elif key in (Qt.Key.Key_Home, Qt.Key.Key_PageUp) and count:
            self.set_active(0)
        elif key in (Qt.Key.Key_End, Qt.Key.Key_PageDown) and count:
            self.set_active(count - 1)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            if row is not None:
                self.choose(row)
            else:
                self.close()
        elif key in (Qt.Key.Key_Escape, Qt.Key.Key_Tab, Qt.Key.Key_Backtab,
                     Qt.Key.Key_F4):
            self.close()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):  # noqa: N802 (Qt override)
        """Presses here are outside every card: the shadow margin, the
        panel padding, or (Qt routes them to a popup) anywhere else."""
        pos = event.position().toPoint()
        if self._panel.geometry().contains(pos):
            event.accept()      # panel padding: stay open
            return
        # A press on the combo itself only closes (it must not reopen).
        on_combo = self._combo.rect().contains(
            self._combo.mapFromGlobal(event.globalPosition().toPoint()))
        self.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay, on_combo)
        self.close()

    # -- paint: the soft shadow under the panel ----------------------------
    def paintEvent(self, event):  # noqa: N802 (Qt override)
        if self._await_expose:
            handle = self.windowHandle()
            if handle is not None and handle.isExposed():
                QTimer.singleShot(0, self._start_entrance)
        rect = QRectF(self._panel.geometry())
        if self._frame is not None and self._still is not None:
            opacity, rise = self._frame
            scale = START_SCALE + (1.0 - START_SCALE) * rise
            # Grow out of the edge nearest the button while rising.
            anchor_y = rect.bottom() if self._opened_above else rect.top()
            anchor = QPointF(rect.center().x(), anchor_y)
            lift = (1.0 - rise) * sp(SLIDE_PX)
            rect = QRectF(anchor.x() + (rect.left() - anchor.x()) * scale,
                          anchor.y() + (rect.top() - anchor.y()) * scale + lift,
                          rect.width() * scale, rect.height() * scale)
        else:
            opacity, scale = self._panel.opacity, 1.0
        if opacity <= 0.001:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        shadow = rect.translated(0, sp(4))
        radius = float(sp(PANEL_RADIUS)) * scale
        steps = max(4, sp(SHADOW) - sp(4))
        for i in range(steps, 0, -1):
            spread = float(i)
            falloff = (1.0 - i / float(steps + 1)) ** 2
            color = QColor(0, 0, 0)
            color.setAlphaF(0.045 * falloff * opacity)
            path = QPainterPath()
            path.addRoundedRect(
                shadow.adjusted(-spread, -spread, spread, spread),
                radius + spread, radius + spread)
            p.fillPath(path, color)
        if self._frame is not None and self._still is not None:
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.setOpacity(opacity)
            p.drawPixmap(rect, self._still, QRectF(self._still.rect()))
        p.end()


# -- the combo ----------------------------------------------------------------
class AnimatedComboBox(QComboBox):
    """QComboBox that opens CardPopup and paints its ring and a turning
    chevron. Disabled (locked while running), the chevron turns into a
    padlock; jiggle() shakes it and flashes the ring, for a click on the
    locked box (its owner catches those: a disabled widget gets none)."""

    RING_MS = 150
    LOCK_MS = 260
    JIGGLE_MS = 560

    def __init__(self, parent=None):
        super().__init__(parent)
        self._popup = None
        self._ghost = None
        self._chevron = Blend(self, self.update, OPEN_MS)
        self._ring = Blend(self, self.update, self.RING_MS)
        self._lock = Blend(self, self.update, self.LOCK_MS)
        self._jiggle_at = None
        self._jiggle_timer = QTimer(self)
        self._jiggle_timer.setInterval(16)
        self._jiggle_timer.timeout.connect(self._jiggle_frame)
        self._hovered = False
        # After a close, Qt sends no Enter until the mouse moves (and so
        # no Leave either): poll the pointer until it has left.
        self._hover_watch = QTimer(self)
        self._hover_watch.setInterval(50)
        self._hover_watch.timeout.connect(self._check_pointer)
        self.setProperty("open", False)
        # No wheel focus: see wheelEvent.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # A list that changes under an open popup would go stale.
        model = self.model()
        for signal in (model.modelReset, model.rowsInserted,
                       model.rowsRemoved, model.dataChanged):
            signal.connect(self._rows_changed)

    def wheelEvent(self, event):  # noqa: N802 (Qt override)
        """Let the wheel scroll the page. A stock QComboBox swallows it
        under the pointer (stopping the scroll and silently switching the
        output device); choosing happens via click or keys instead. The
        open popup's list still scrolls on its own."""
        event.ignore()

    # -- popup -----------------------------------------------------------
    def popup(self):
        """The card popup (None until first opened)."""
        return self._popup

    def is_open(self) -> bool:
        return self._popup is not None and self._popup.isVisible()

    def showPopup(self):  # noqa: N802 (Qt override)
        if not self.isEnabled() or self.count() == 0 or self.is_open():
            return
        if self._popup is None:
            self._popup = CardPopup(self)
        self._popup.open()
        # The chevron turns with the entrance (CardPopup starts both),
        # which waits for the popup to reach the screen.
        self._set_open(True, turn=not motion_ok())

    def hidePopup(self):  # noqa: N802 (Qt override)
        if self.is_open():
            self._popup.close()

    def _arm_ghost(self, geometry: QRect) -> None:
        if self._ghost is None:
            self._ghost = _Ghost()
        self._ghost.arm(geometry)

    def _ghost_out(self, pixmap, geometry: QRect, anchor: QPointF,
                   progress: float = 1.0) -> None:
        if self._ghost is None:
            self._ghost = _Ghost()
        self._ghost.fade_out(pixmap, geometry, anchor, progress)

    def _disarm_ghost(self) -> None:
        if self._ghost is not None and not self._ghost.fading:
            self._ghost.hide()

    def _rows_changed(self, *args) -> None:
        if self._popup is None:
            return
        self._popup.mark_stale()
        if self._popup.isVisible():
            self._popup.close()

    def _choose(self, row: int) -> None:
        self.setCurrentIndex(row)
        self.activated.emit(row)
        self.textActivated.emit(self.itemText(row))

    def _popup_closed(self) -> None:
        if self._pointer_inside():
            self._hovered = True
            self._hover_watch.start()
        self._set_open(False)

    def _set_open(self, is_open: bool, turn: bool = True) -> None:
        self.setProperty("open", is_open)
        if turn:
            self._turn_chevron(is_open)
        self._sync_ring()
        self.update()

    # -- the ring (open or hovered) ----------------------------------------
    def _pointer_inside(self) -> bool:
        try:
            return self.isVisible() and self.rect().contains(
                self.mapFromGlobal(QCursor.pos()))
        except Exception:
            return False

    def _check_pointer(self) -> None:
        if not self._pointer_inside():
            self._hover_watch.stop()
            self._hovered = False
            self._sync_ring()

    def _sync_ring(self) -> None:
        lit = self.isEnabled() and (self.is_open() or self._hovered)
        self._ring.set_target(1.0 if lit else 0.0,
                              animated=(motion_ok() and self.isVisible()
                                        and self.isEnabled()))

    def enterEvent(self, event):  # noqa: N802 (Qt override)
        # A running watch keeps going until the pointer has really left:
        # an Enter synthesized as a popup closes need not get its Leave.
        self._hovered = True
        self._sync_ring()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802 (Qt override)
        # Also sent when the popup takes the mouse: open keeps it lit.
        self._hover_watch.stop()
        self._hovered = False
        self._sync_ring()
        super().leaveEvent(event)

    def changeEvent(self, event):  # noqa: N802 (Qt override)
        super().changeEvent(event)
        if event.type() == QEvent.Type.EnabledChange:
            self._sync_ring()
            self._lock.set_target(0.0 if self.isEnabled() else 1.0,
                                  animated=motion_ok() and self.isVisible())

    # -- the padlock (disabled) --------------------------------------------
    def jiggle(self) -> None:
        """Shake the padlock and flash the ring: "locked while running"."""
        if not motion_ok():
            return
        self._jiggle_at = time.monotonic()
        self._jiggle_timer.start()

    def _jiggle_ms(self):
        if self._jiggle_at is None:
            return None
        t = (time.monotonic() - self._jiggle_at) * 1000.0
        return t if t < self.JIGGLE_MS else None

    def _jiggle_frame(self) -> None:
        if self._jiggle_ms() is None:
            self._jiggle_timer.stop()
            self._jiggle_at = None
        self.update()

    def hideEvent(self, event):  # noqa: N802 (Qt override)
        self._hover_watch.stop()
        self._hovered = False
        self._ring.snap(0.0)
        super().hideEvent(event)

    def _turn_chevron(self, is_open: bool) -> None:
        self._chevron.set_target(1.0 if is_open else 0.0,
                                 animated=motion_ok() and self.isVisible())

    # -- paint: the ring and the chevron ----------------------------------
    def _paint_ring(self) -> None:
        """Gold over the QSS rest border (same box: 1px, 10px radius)."""
        lit = self._ring.value
        jiggle = self._jiggle_ms()
        if jiggle is not None:   # a locked click flashes it
            lit = max(lit, 1.0 - jiggle / self.JIGGLE_MS)
        if lit <= 0.01:
            return
        color = QColor(current_theme()["secondary"])
        color.setAlphaF(lit)
        width = float(sp(1))
        half = width / 2.0
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(color, width))
        p.setBrush(Qt.BrushStyle.NoBrush)
        radius = sp(10) - half
        p.drawRoundedRect(QRectF(self.rect()).adjusted(half, half, -half, -half),
                          radius, radius)
        p.end()

    def paintEvent(self, event):  # noqa: N802 (Qt override)
        super().paintEvent(event)
        self._paint_ring()
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        area = self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox, opt,
            QStyle.SubControl.SC_ComboBoxArrow, self)
        if area.isEmpty():
            return
        palette = current_theme()
        t = self._chevron.value
        locked = self._lock.value
        color = mix_rgba(QColor(palette["muted"]),
                         QColor(palette["secondary"]), t)
        if not self.isEnabled():
            color.setAlphaF(color.alphaF() * 0.45)
        u = ui_scale()
        half_w, half_h = 5.0 * u, 2.5 * u   # 12x8 glyph
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(QRectF(area).center())
        pen = QPen(color, max(1.5, sp(2)))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        if locked < 0.99:                   # the chevron shrinks away...
            p.save()
            p.rotate(180.0 * t)
            p.scale(1.0 - 0.5 * locked, 1.0 - 0.5 * locked)
            color.setAlphaF(color.alphaF() * (1.0 - locked))
            pen.setColor(color)
            p.setPen(pen)
            path = QPainterPath()
            path.moveTo(-half_w, -half_h)
            path.lineTo(0, half_h)
            path.lineTo(half_w, -half_h)
            p.drawPath(path)
            p.restore()
        if locked > 0.01:                   # ...as the padlock grows in
            jiggle = self._jiggle_ms()
            if jiggle is not None:
                v = jiggle / self.JIGGLE_MS
                p.rotate(14.0 * math.sin(v * math.pi * 5.0) * (1.0 - v))
            size = 0.5 + 0.5 * locked
            p.scale(size, size)
            gold = QColor(palette["secondary"])
            gold.setAlphaF(0.85 * locked)
            pen.setColor(gold)
            pen.setWidthF(max(1.4, 1.6 * u))
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(-5 * u, -1 * u, 10 * u, 7.5 * u),
                              1.5 * u, 1.5 * u)
            shackle = QPainterPath()
            shackle.moveTo(-3.2 * u, -1 * u)
            shackle.lineTo(-3.2 * u, -3.5 * u)
            shackle.arcTo(QRectF(-3.2 * u, -6.7 * u, 6.4 * u, 6.4 * u),
                          180.0, -180.0)
            shackle.lineTo(3.2 * u, -1 * u)
            p.drawPath(shackle)
        p.end()
