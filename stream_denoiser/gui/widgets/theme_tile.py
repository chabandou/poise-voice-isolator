"""
Poise Voice Isolator - Theme Tile Widget

Swatch-style theme picker tile: a rounded square filled with the theme's
main accent color with the theme name inside. The checked tile gets a
thick outline and a bold name.
"""
from PyQt6.QtWidgets import QAbstractButton, QSizePolicy
from PyQt6.QtCore import QSize, Qt, QPropertyAnimation, QEasingCurve, pyqtProperty
from PyQt6.QtGui import QPainter, QColor, QFont, QPen

from ..scaling import sp


class ThemeTile(QAbstractButton):
    """Checkable accent swatch with the theme name."""

    def __init__(self, accent: str, background: str, text_dark: str,
                 name: str, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        try:
            from ..cursors import apply_link_cursor
            apply_link_cursor(self)
        except Exception:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self._accent = QColor(accent)
        self._background = QColor(background)
        self._text_dark = QColor(text_dark)
        self._name = name
        self.setMinimumSize(self.sizeHint())

        # Apple-style tactile state (paint-time only, layout-safe).
        self._press = 0.0   # 1 while held -> squash to ~0.97
        self._hover = 0.0   # 1 on hover -> brighten (no scaling)
        self._select = 1.0  # 0 -> 1 spring pop on selection
        self._selT = 0.0    # 0 <-> 1 eased selection blend (ring + fill)
        self._press_anim = None
        self._hover_anim = None
        self._select_anim = None
        self._sel_anim = None
        self.toggled.connect(self._on_toggled)

    def sizeHint(self):  # noqa: N802 (Qt override)
        return QSize(sp(120), sp(88))

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
        # Selection blend (ring fade + fill crossfade, both directions).
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
        side_w, side_h = self.width(), self.height()
        radius = sp(18)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Combined tactile scale around the center (paint-time only).
        # Strictly capped at full size: the swatch is full-bleed, so any
        # growth would push the corners outside the widget bounds and
        # visibly flatten the rounding. Hover feedback comes from the
        # brightening below, not from scaling.
        press = max(0.0, min(1.0, self._press))
        hover = max(0.0, min(1.0, self._hover))
        select = max(0.0, min(1.0, self._select))
        sel = max(0.0, min(1.0, self._selT))
        scale = (1.0 - 0.03 * press) * (0.94 + 0.06 * select)
        scale = min(scale, 1.0)
        cx, cy = side_w / 2.0, side_h / 2.0
        p.translate(cx, cy)
        p.scale(scale, scale)
        p.translate(-cx, -cy)

        # Swatch fill: dimmed when unselected, full when selected, with
        # the selection blend animated and hover adding up to +50.
        fill = QColor(self._accent)
        fill.setAlpha(min(255, int(110 + 145 * sel + 50 * hover * (1 - sel))))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(0, 0, side_w, side_h, radius, radius)

        # Thick outline for the selected tile (softened ring on the
        # swatch), set in as an inner frame: press/pop scaling never
        # exceeds full size, so it can't clip. Fades with the blend.
        if sel > 0.01:
            ring = QColor(self._background.lighter(150))
            ring.setAlphaF(sel)
            pen = QPen(ring, sp(4))
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            inset = sp(5)
            ring_radius = max(sp(4), radius - inset)
            p.drawRoundedRect(inset, inset, side_w - inset * 2,
                              side_h - inset * 2,
                              ring_radius, ring_radius)

        # Name, bottom-left corner.
        font = QFont("Segoe UI", sp(14))
        font.setWeight(QFont.Weight.Bold if self.isChecked()
                       else QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(self._text_dark)
        pad_left, pad_bottom = sp(12), sp(10)
        p.drawText(pad_left, 0, side_w - pad_left, side_h - pad_bottom,
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                   self._name)
        p.end()
