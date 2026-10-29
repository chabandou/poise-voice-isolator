"""
Poise Voice Isolator - in-window notice.

A modal card drawn inside the main window over a dimmed backdrop, in the
app's own card style, instead of a native message box. Used once, on
first launch, to say music can pass through.
"""

from PyQt6.QtCore import QEvent, QPropertyAnimation, Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)

from .phosphor import PhosphorIcon
from ..scaling import sp
from ..themes import current as current_theme

SCRIM_ALPHA = 0.72
FADE_MS = 220


class NoticeOverlay(QWidget):
    """Covers `host` until dismissed; clicks and Tab stay inside it."""

    def __init__(self, host: QWidget, title: str, body: str,
                 button: str = "Got it"):
        super().__init__(host)
        self.setObjectName("notice-overlay")
        self._scrim = QColor(current_theme()["bg"])
        self._scrim.setAlphaF(SCRIM_ALPHA)

        card = QFrame(self)
        card.setObjectName("card")
        # Fixed, not a maximum: a wrapped label only gets its full height
        # when the width it wraps at is known.
        card.setFixedWidth(sp(480))
        lay = QVBoxLayout(card)
        lay.setContentsMargins(sp(28), sp(26), sp(28), sp(24))
        lay.setSpacing(sp(12))

        head = QHBoxLayout()
        head.setSpacing(sp(14))
        chip = QFrame()
        chip.setObjectName("chip")
        chip.setFixedSize(sp(44), sp(44))
        chip_lay = QHBoxLayout(chip)
        chip_lay.setContentsMargins(0, 0, 0, 0)
        chip_lay.addWidget(
            PhosphorIcon("info", color=current_theme()["secondary"], size=22),
            alignment=Qt.AlignmentFlag.AlignCenter)
        head.addWidget(chip)
        heading = QLabel(title)
        heading.setObjectName("card-title")
        head.addWidget(heading, stretch=1)
        lay.addLayout(head)

        text = QLabel(body)
        text.setWordWrap(True)
        lay.addWidget(text)

        lay.addSpacing(sp(6))
        foot = QHBoxLayout()
        foot.addStretch(1)
        self.button = QPushButton(button)
        self.button.setObjectName("primary")
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.clicked.connect(self.dismiss)
        foot.addWidget(self.button)
        lay.addLayout(foot)

        # Centred by stretches, not an alignment flag: aligned items get
        # their size hint, which cuts the wrapped text short.
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(card)
        row.addStretch(1)
        outer = QVBoxLayout(self)
        outer.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)

        host.installEventFilter(self)
        self.setGeometry(host.rect())

    def open(self) -> None:
        self.show()
        self.raise_()
        self.button.setFocus()
        from ..animations import fade_in
        fade_in(self, duration_ms=FADE_MS)

    def dismiss(self) -> None:
        from ..animations import motion_ok
        if not motion_ok():
            self.deleteLater()
            return
        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        self._fade = QPropertyAnimation(effect, b"opacity", self)
        self._fade.setDuration(FADE_MS)
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self.deleteLater)
        self._fade.start()

    def eventFilter(self, obj, event):  # noqa: N802 (Qt override)
        if event.type() == QEvent.Type.Resize:
            self.setGeometry(obj.rect())
        return False

    def keyPressEvent(self, event):  # noqa: N802 (Qt override)
        if event.key() == Qt.Key.Key_Escape:
            self.dismiss()
        else:
            super().keyPressEvent(event)

    def focusNextPrevChild(self, next):  # noqa: N802 (Qt override)
        return True  # keep keyboard focus off the page underneath

    def mousePressEvent(self, event):  # noqa: N802 (Qt override)
        event.accept()  # the backdrop swallows clicks

    def paintEvent(self, event):  # noqa: N802 (Qt override)
        p = QPainter(self)
        p.fillRect(self.rect(), self._scrim)
        p.end()
