"""
Poise Voice Isolator - Sidebar Navigation

Left navigation rail: logo row, nav buttons with a sliding active
highlight, and a version label pinned to the bottom.

The highlight is a soft accent wash that fades out to the right and
glides between items. Set INDICATOR_EDGE_BAR = True for the older thin
bar flush against the window edge instead.
"""
from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QWidget,
)
from PyQt6.QtCore import QPoint, QRectF, pyqtSignal, Qt
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPixmap

from .phosphor import PhosphorIcon
from ..scaling import isp, sp
from ..themes import current as current_theme
from ..animations import Blend
from ..utils import get_icon_path
from ... import __version__


INDICATOR_EDGE_BAR = False
HOVER_WASH_ALPHA = 0.17


class NavButton(QPushButton):
    """Sidebar navigation entry with an active state."""

    def __init__(self, index: int, icon: str, text: str, parent=None):
        super().__init__(parent)
        self._index = index
        self.setObjectName("nav")
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip(text)
        try:
            from ..cursors import apply_link_cursor
            apply_link_cursor(self)
        except Exception:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(14, 0, 8, 0)
        self._layout.setSpacing(12)
        self._icon = PhosphorIcon(
            icon, color=current_theme()["nav_muted"], size=20)
        self._layout.addWidget(self._icon)
        self._label = QLabel(text)
        self._label.setObjectName("nav-text")
        self._layout.addWidget(self._label, stretch=1)
        # The icon and label cover nearly the whole button. If they take
        # mouse events, Qt hovers *them* and the button's own :hover
        # background never paints (it only showed on the thin margins).
        for child in (self._icon, self._label):
            child.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        # Hover wash: painted (QSS cannot fade) with an eased blend, same
        # shape as the active highlight but a neutral, softer tone.
        self._hover_blend = Blend(self, self.update, 150)

        # Apple-style press dip (opacity only — layout-safe).
        try:
            from ..animations import install_press_fade
            install_press_fade(self, pressed_opacity=0.6)
        except Exception:
            pass

    def enterEvent(self, event):  # noqa: N802 (Qt override)
        if not self.property("active"):
            self._hover_blend.set_target(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802 (Qt override)
        self._hover_blend.set_target(0.0)
        super().leaveEvent(event)

    def paintEvent(self, event):  # noqa: N802 (Qt override)
        super().paintEvent(event)
        t = self._hover_blend.value
        if t <= 0.01 or self.property("active"):
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        wash = QLinearGradient(rect.left(), 0, rect.right(), 0)
        start = QColor(148, 163, 184)
        start.setAlphaF(HOVER_WASH_ALPHA * t)
        end = QColor(148, 163, 184)
        end.setAlphaF(0.0)
        wash.setColorAt(0.0, start)
        wash.setColorAt(1.0, end)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(wash)
        p.drawRoundedRect(rect, sp(10), sp(10))
        p.end()

    def set_compact(self, compact: bool) -> None:
        """Icon-rail mode: hide the label, center the icon."""
        self._label.setVisible(not compact)
        if compact:
            self._layout.setContentsMargins(0, 0, 0, 0)
            self._layout.setAlignment(
                self._icon, Qt.AlignmentFlag.AlignCenter)
        else:
            self._layout.setContentsMargins(14, 0, 8, 0)
            self._layout.setAlignment(
                self._icon,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    @property
    def index(self) -> int:
        return self._index

    def set_active(self, active: bool) -> None:
        palette = current_theme()
        self.setChecked(active)
        self.setProperty("active", active)
        if active:
            self._hover_blend.set_target(0.0)   # the active wash takes over
        elif self.underMouse():
            self._hover_blend.set_target(1.0)
        self._icon.set_color(
            palette["accent"] if active else palette["nav_muted"])
        # Repolish the label too: polishing only the button leaves the
        # child's QSS color (nav-text) frozen on its previous state.
        for widget in (self, self._label):
            self.style().unpolish(widget)
            self.style().polish(widget)


class Sidebar(QFrame):
    """Navigation rail. Emits page_requested(index) on nav clicks."""

    page_requested = pyqtSignal(int)

    PAGES = (
        ("Home", "waveform"),
        ("Settings", "gear"),
        ("Logs", "doc"),
        ("About", "info"),
    )

    FULL_W = 216
    RAIL_W = 68

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self._compact = False
        self.setFixedWidth(sp(self.FULL_W))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 24, 12, 22)
        layout.setSpacing(8)

        # Logo row (keeps its 16px from the edge via its own margins).
        self._logo_widget = QWidget()
        logo_widget_layout = QHBoxLayout(self._logo_widget)
        logo_widget_layout.setContentsMargins(10, 0, 0, 0)
        logo_widget_layout.setSpacing(12)
        self._logo_layout = logo_widget_layout
        self._logo_spacer = False
        self._logo_icon = self._make_logo_icon()
        logo_widget_layout.addWidget(self._logo_icon)
        self._logo_label = QLabel("POISE")
        self._logo_label.setObjectName("logo")
        font = self._logo_label.font()
        font.setPointSize(sp(19))
        font.setWeight(QFont.Weight.DemiBold)
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 135)
        self._logo_label.setFont(font)
        logo_widget_layout.addWidget(self._logo_label)
        logo_widget_layout.addStretch()
        layout.addWidget(self._logo_widget)
        layout.addSpacing(30)

        # Nav cluster: rows touch (no inter-button gap — the old 8px
        # spacing lives on as 4px + 4px internal padding per button, so
        # the rhythm is unchanged). Kept in its own container so the
        # outer layout's spacing still breathes around logo/version.
        self._nav_wrap = QWidget()
        self._nav_wrap.setObjectName("nav-wrap")
        nav_layout = QVBoxLayout(self._nav_wrap)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(0)

        # Nav buttons.
        self._buttons = []
        for i, (text, icon) in enumerate(self.PAGES):
            btn = NavButton(i, icon, text)
            btn.clicked.connect(self._on_nav_clicked)
            nav_layout.addWidget(btn)
            self._buttons.append(btn)
        self._buttons[0].set_active(True)
        layout.addWidget(self._nav_wrap)

        layout.addStretch()

        # Version footer.
        self._version = QLabel(f"POISE v{__version__}")
        self._version.setObjectName("version")
        self._version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._version)

        # Sliding active indicator: thin accent bar at the left edge that
        # glides between buttons (Apple sidebar feel). Absolutely
        # positioned — never in the layout — so it animates for free.
        self._indicator = QFrame(self)
        self._indicator.setObjectName("nav-indicator")
        self._indicator.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        if INDICATOR_EDGE_BAR:
            self._indicator.setFixedWidth(max(2, sp(3)))
        self._indicator_anim = None
        self._active_index = 0
        self._refresh_indicator_style()
        # Snap into place once layout has run.
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._snap_indicator())

    @staticmethod
    def _make_logo_icon() -> QLabel:
        """App icon pixmap, falling back to the painted glyph."""
        icon_path = get_icon_path()
        if icon_path:
            label = QLabel()
            label.setObjectName("logo-icon")
            side = isp(34)
            label.setPixmap(
                QPixmap(icon_path).scaled(
                    side, side, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
            return label
        return PhosphorIcon("waveform", size=26)

    def _on_nav_clicked(self):
        btn = self.sender()
        if not isinstance(btn, NavButton):
            return
        self.set_active_page(btn.index)
        self.page_requested.emit(btn.index)

    def set_active_page(self, index: int) -> None:
        for i, btn in enumerate(self._buttons):
            btn.set_active(i == index)
        self._active_index = index
        self._slide_indicator(animated=True)

    @property
    def is_compact(self) -> bool:
        return self._compact

    def set_compact(self, compact: bool) -> None:
        """Collapse to an icon rail (narrow windows) or back."""
        if compact == self._compact:
            return
        self._compact = compact
        self.setFixedWidth(sp(self.RAIL_W if compact else self.FULL_W))
        for btn in self._buttons:
            btn.set_compact(compact)
        # Logo mark stays (no text); center it with a balancing spacer.
        self._logo_label.setVisible(not compact)
        # The rail is narrower than icon + gutter: drop the left inset so
        # the centred logo is not clipped.
        self._logo_layout.setContentsMargins(0 if compact else 10, 0, 0, 0)
        if compact and not self._logo_spacer:
            self._logo_layout.insertStretch(0, 1)
            self._logo_spacer = True
        elif not compact and self._logo_spacer:
            taken = self._logo_layout.takeAt(0)
            del taken
            self._logo_spacer = False
        self._version.setVisible(not compact)
        # Geometry changed: re-snap the indicator without animating.
        self._snap_indicator()

    def refresh_theme(self) -> None:
        """Re-apply state colors after a theme switch."""
        for btn in self._buttons:
            btn.set_active(btn.isChecked())
        self._refresh_indicator_style()
        self._snap_indicator()
        self._reload_logo()

    def showEvent(self, event):  # noqa: N802 (Qt override)
        super().showEvent(event)
        self._snap_indicator()

    def resizeEvent(self, event):  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._snap_indicator()

    # -- sliding indicator ---------------------------------------------------
    def _refresh_indicator_style(self) -> None:
        try:
            palette = current_theme()
            if INDICATOR_EDGE_BAR:
                radius = max(1, sp(3) // 2)
                self._indicator.setStyleSheet(
                    f"QFrame#nav-indicator {{ background-color: "
                    f"{palette['accent']}; border: none; "
                    f"border-radius: {radius}px; }}")
                return
            rgb = palette["accent_rgb"]
            self._indicator.setStyleSheet(
                "QFrame#nav-indicator { background: qlineargradient("
                "x1:0, y1:0, x2:1, y2:0, "
                f"stop:0 rgba({rgb}, 0.22), stop:1 rgba({rgb}, 0.0)); "
                f"border: none; border-radius: {sp(10)}px; }}")
        except Exception:
            pass

    def _indicator_target(self):
        try:
            btn = self._buttons[self._active_index]
            # Buttons live in the nav cluster: map to sidebar coords.
            # The strip spans the full row height like a left border.
            top_left = btn.mapTo(self, QPoint(0, 0))
            if INDICATOR_EDGE_BAR:
                w = self._indicator.width() or max(2, sp(3))
                return 0, top_left.y(), w, btn.height()
            return top_left.x(), top_left.y(), btn.width(), btn.height()
        except Exception:
            return 0, 0, max(2, sp(3)), 24

    def _snap_indicator(self) -> None:
        try:
            if self._indicator_anim is not None:
                try:
                    self._indicator_anim.stop()
                except Exception:
                    pass
            x, y, w, h = self._indicator_target()
            self._indicator.setGeometry(x, y, w, h)
            self._indicator.show()
            self._send_indicator_back()
        except Exception:
            pass

    def _send_indicator_back(self) -> None:
        if INDICATOR_EDGE_BAR:
            self._indicator.raise_()
        else:
            self._indicator.lower()

    def _slide_indicator(self, animated: bool = True) -> None:
        try:
            from ..animations import motion_ok
            x, y, w, h = self._indicator_target()
            self._indicator.show()
            self._send_indicator_back()
            if not animated or not motion_ok():
                self._indicator.setGeometry(x, y, w, h)
                return
            from PyQt6.QtCore import QPropertyAnimation, QEasingCurve, QRect
            if self._indicator_anim is not None:
                try:
                    self._indicator_anim.stop()
                except Exception:
                    pass
            self._indicator_anim = QPropertyAnimation(
                self._indicator, b"geometry", self)
            self._indicator_anim.setDuration(220)
            self._indicator_anim.setStartValue(self._indicator.geometry())
            self._indicator_anim.setEndValue(QRect(x, y, w, h))
            self._indicator_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._indicator_anim.start()
        except Exception:
            pass

    def _reload_logo(self) -> None:
        """Reload the logo pixmap for the active theme's icon variant."""
        if isinstance(self._logo_icon, PhosphorIcon):
            return  # painted fallback has no file to reload
        icon_path = get_icon_path()
        if icon_path:
            side = isp(34)
            self._logo_icon.setPixmap(
                QPixmap(icon_path).scaled(
                    side, side, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
