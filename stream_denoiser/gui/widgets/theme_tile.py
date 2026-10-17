"""
Poise Voice Isolator - Theme Tile Widget

Theme picker tile: a miniature of the theme itself. The tile is filled with
the theme's background, carries the Poise wave in the theme's accent and
the theme name in its text colour. The selected tile gets an outline in
the *current* theme's secondary colour, set off from the tile by a small
gap.
"""
from PyQt6.QtWidgets import QAbstractButton, QSizePolicy
from PyQt6.QtCore import (
    QByteArray, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt,
    pyqtProperty,
)
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PyQt6.QtSvg import QSvgRenderer

from ..fonts import heading_family
from ..scaling import sp
from .. import themes as theme_store

WAVE_PATH = ("M3 12C3.00015 8.14286 4.28571 3 6.85714 3C10.7143 2.9999 "
             "13.2857 21 17.1429 21C19.7143 21 21 15.8571 21 12 "
             "M3 12H5 M19 12H21 M15.5 12H16.5 M7.5 12H8.5")

RING_WIDTH = 2    # selection outline (design px)
RING_GAP = 3      # gap between outline and tile
TILE_RADIUS = 12


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
    )


class ThemeTile(QAbstractButton):
    """Checkable miniature of a theme (background, wave, name)."""

    def __init__(self, theme_id: str, parent=None):
        super().__init__(parent)
        palette = theme_store.get_theme(theme_id)
        self.theme_id = theme_id
        self._bg = QColor(palette["bg"])
        self._edge = QColor(palette["groove"])
        self._accent = QColor(palette["accent"])
        self._text = QColor(palette["text"])
        self._name = palette["label"]
        self._logo = QSvgRenderer(QByteArray((
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
            f'fill="none" stroke="{palette["accent"]}" stroke-width="1.9" '
            'stroke-linecap="round" stroke-linejoin="round">'
            f'<path d="{WAVE_PATH}"/></svg>').encode()))

        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        try:
            from ..cursors import apply_link_cursor
            apply_link_cursor(self)
        except Exception:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)
        self.setMinimumSize(self.minimumSizeHint())
        self.setFixedHeight(self.sizeHint().height())

        # Tactile state (paint-time only, layout-safe).
        self._press = 0.0   # 1 while held -> squash to ~0.97
        self._hover = 0.0   # 1 on hover -> edge picks up the accent
        self._select = 1.0  # 0 -> 1 spring pop on selection
        self._selT = 0.0    # 0 <-> 1 eased selection blend (outline)
        self._press_anim = None
        self._hover_anim = None
        self._select_anim = None
        self._sel_anim = None
        self.toggled.connect(self._on_toggled)

    def sizeHint(self):  # noqa: N802 (Qt override)
        return QSize(sp(104), sp(84))

    def minimumSizeHint(self):  # noqa: N802 (Qt override)
        return QSize(sp(84), sp(84))

    # -- animated properties ------------------------------------------------
    def _get_press(self) -> float:
        return self._press

    def _set_press(self, v: float) -> None:
        self._press = float(v)
        self.update()

    press = pyqtProperty(float, _get_press, _set_press)

    def _get_hover(self) -> float:
        return self._hover

    def _set_hover(self, v: float) -> None:
        self._hover = float(v)
        self.update()

    hover = pyqtProperty(float, _get_hover, _set_hover)

    def _get_select(self) -> float:
        return self._select

    def _set_select(self, v: float) -> None:
        self._select = float(v)
        self.update()

    select = pyqtProperty(float, _get_select, _set_select)

    def _get_selT(self) -> float:  # noqa: N802 (Qt-style name)
        return self._selT

    def _set_selT(self, v: float) -> None:  # noqa: N802 (Qt-style name)
        self._selT = float(v)
        self.update()

    selT = pyqtProperty(float, _get_selT, _set_selT)

    def _tween(self, prop: bytes, end: float, ms: int,
               curve=QEasingCurve.Type.OutCubic) -> None:
        try:
            from ..animations import motion_ok
            if not motion_ok():
                # NOTE: prop is plain bytes (QPropertyAnimation accepts
                # that); bytes has no .data(), so decode directly.
                name = prop.decode() if isinstance(prop, bytes) else str(prop)
                self.setProperty(name, end)
                self.update()
                return
        except Exception:
            pass
        try:
            anim = QPropertyAnimation(self, prop, self)
            anim.setDuration(ms)
            anim.setEndValue(end)
            anim.setEasingCurve(curve)
            if prop == b"press":
                old, self._press_anim = self._press_anim, anim
            elif prop == b"hover":
                old, self._hover_anim = self._hover_anim, anim
            elif prop == b"selT":
                old, self._sel_anim = self._sel_anim, anim
            else:
                old, self._select_anim = self._select_anim, anim
            if old is not None:
                try:
                    old.stop()
                except Exception:
                    pass
            anim.start()
        except Exception:
            pass

    def _on_toggled(self, checked: bool) -> None:
        # Outline blend (fade in/out in both directions).
        self._tween(b"selT", 1.0 if checked else 0.0, 200)
        if not checked:
            return
        # Selection pop: squash then spring back (OutBack overshoot).
        try:
            from ..animations import motion_ok
            if not motion_ok():
                return
        except Exception:
            pass
        try:
            if self._select_anim is not None:
                try:
                    self._select_anim.stop()
                except Exception:
                    pass
            self._select = 0.0
            self._select_anim = QPropertyAnimation(self, b"select", self)
            self._select_anim.setDuration(280)
            self._select_anim.setStartValue(0.0)
            self._select_anim.setEndValue(1.0)
            curve = QEasingCurve(QEasingCurve.Type.OutBack)
            curve.setAmplitude(1.4)
            self._select_anim.setEasingCurve(curve)
            self._select_anim.start()
        except Exception:
            self._select = 1.0

    def mousePressEvent(self, event):  # noqa: N802 (Qt override)
        self._tween(b"press", 1.0, 110)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802 (Qt override)
        self._tween(b"press", 0.0, 200, QEasingCurve.Type.OutBack)
        super().mouseReleaseEvent(event)

    def enterEvent(self, event):  # noqa: N802 (Qt override)
        self._tween(b"hover", 1.0, 150)
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802 (Qt override)
        self._tween(b"hover", 0.0, 150)
        super().leaveEvent(event)

    def paintEvent(self, event):  # noqa: N802 (Qt override)
        w, h = self.width(), self.height()
        inset = float(sp(RING_WIDTH + RING_GAP))
        radius = float(sp(TILE_RADIUS))

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Tactile scale around the centre (paint-time only). Capped at
        # full size so the outline, which sits on the widget edge, can
        # never be pushed past the bounds and clipped flat.
        press = max(0.0, min(1.0, self._press))
        hover = max(0.0, min(1.0, self._hover))
        select = max(0.0, min(1.0, self._select))
        sel = max(0.0, min(1.0, self._selT))
        scale = min((1.0 - 0.03 * press) * (0.94 + 0.06 * select), 1.0)
        cx, cy = w / 2.0, h / 2.0
        p.translate(cx, cy)
        p.scale(scale, scale)
        p.translate(-cx, -cy)

        # Tile body: the theme's own background with a hairline edge that
        # warms toward the theme accent on hover.
        edge = _mix(self._edge, self._accent, 0.6 * hover)
        body = QRectF(inset, inset, w - 2 * inset, h - 2 * inset)
        p.setPen(QPen(edge, max(1.0, float(sp(1)))))
        p.setBrush(self._bg)
        p.drawRoundedRect(body, radius, radius)

        # Wave mark (top-left) in the theme accent.
        pad = float(sp(9))
        mark = float(sp(26))
        self._logo.render(p, QRectF(body.left() + pad, body.top() + pad,
                                    mark, mark))

        # Name (bottom-left) in the theme's text colour.
        font = QFont(heading_family())
        font.setWeight(QFont.Weight.Bold)
        # Long names must fit narrow tiles: step the
        # size down until the label fits the text box.
        avail = body.width() - 2 * pad
        size = sp(15)
        font.setPixelSize(size)
        while size > sp(10) and QFontMetricsF(font).horizontalAdvance(
                self._name) > avail:
            size -= 1
            font.setPixelSize(size)
        p.setFont(font)
        p.setPen(self._text)
        p.drawText(QRectF(body.left() + pad, body.top(),
                          body.width() - 2 * pad, body.height() - pad * 0.7),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                   self._name)

        # Selection outline in the current theme's secondary colour.
        if sel > 0.01:
            ring = QColor(theme_store.current()["secondary"])
            ring.setAlphaF(sel)
            ring_w = float(sp(RING_WIDTH))
            pen = QPen(ring, ring_w)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            half = ring_w / 2.0
            p.drawRoundedRect(QRectF(half, half, w - ring_w, h - ring_w),
                              radius + sp(RING_GAP), radius + sp(RING_GAP))
        p.end()
