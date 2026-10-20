"""
Poise Voice Isolator - Stats Bar

One-line status and performance readout for the window's status bar:

    * isolating     load 0.11x   frame 1.2 ms   skip on   buffer 2/2        source vb-cable

The status (dot + text) carries every start/stop step in full ("switching
audio device…", "loading GTCRN…", "output: Speakers (…)"), while Home's card
keeps only the headline. Each step stays up at least STEP_MIN_MS so quick
ones can be read; later messages queue behind it, errors don't wait. Long
text is cut short with the full message in the tooltip, and a click on the
status opens the log (open_log).

Replaces the old stats card on Home. Same update_stats()/reset() contract
as the former StatsPanel (keys: rtf, avg_time_ms, aad_bypass_active,
input_buffer, output_buffer). The load figure is colour-coded the way the
card was: < 0.8 good, < 1.0 warning, otherwise bad. "skip" is live: on
while silence skipping is resting the model right now; hidden when
silence skipping is turned off (the processor then sends no aad_* keys).
"""
import time

from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QStyle, QStyleOption, QWidget,
)
from PyQt6.QtCore import QPoint, QPointF, QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter

from ..animations import (
    FrameTimer, TextSwap, ambient_ok, ease_out, motion_ok, stagger_in,
)
from ..scaling import sp
from ..themes import breathing, current as current_theme

STATE_WORDS = {
    "ready": "ready",
    "processing": "isolating",
    "error": "error",
}

#: A start/stop step stays up at least this long, so quick ones are read
#: (later messages queue behind it; errors don't wait).
STEP_MIN_MS = 700
#: Status text past this width is cut short (the full text is the tooltip).
STATUS_MAX_W = 440
#: How many messages may wait behind a step (oldest steps drop first).
QUEUE_MAX = 3
LOG_HINT = "Click to open the log."
#: While isolating a halo leaves the status dot this often (ms; half a
#: breath on a breathing theme, see widgets/sky.py)...
HALO_MS = 2400
HALO_BREATH_MS = 4000
#: ...growing to this many dot sizes as it fades.
HALO_GROWTH = 2.8


def _bar_voice(text: str) -> str:
    """The bar's lowercase voice, keeping names and acronyms as written
    ("Loading GTCRN..." -> "loading GTCRN…", "VB-CABLE: ..." unchanged)."""
    text = text.replace("...", "\u2026")
    if len(text) > 1 and text[0].isupper() and text[1].islower():
        text = text[0].lower() + text[1:]
    return text


def status_text(state: str, message: str = "") -> str:
    """Status-bar text for a status message in the given state: the
    message itself (Home's card only carries the headline), with the
    steady states as one word."""
    message = (message or "").strip()
    if state == "ready":
        return STATE_WORDS["ready"]
    if state == "error":
        if message.lower().startswith("error:"):
            message = message[len("error:"):].strip()
        first = message.splitlines()[0].strip() if message else ""
        return f"error: {first}" if first else STATE_WORDS["error"]
    if message.lower().startswith(("isolating", "processing")):
        return STATE_WORDS["processing"]
    return _bar_voice(message) if message else "starting\u2026"


class _StatusArea(QWidget):
    """The dot and status text; a click opens the log."""

    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sb-status-area")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event):  # noqa: N802 (Qt override)
        if (event.button() == Qt.MouseButton.LeftButton
                and self.rect().contains(event.position().toPoint())):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class StatsBar(QWidget):
    """Status-bar content: state dot + status text, live stats, routing
    source."""

    open_log = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("stats-bar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(sp(16), 0, sp(16), 0)
        layout.setSpacing(sp(22))

        self._status = _StatusArea()
        self._status.clicked.connect(self.open_log.emit)
        state_box = QHBoxLayout(self._status)
        state_box.setContentsMargins(0, 0, 0, 0)
        state_box.setSpacing(sp(8))
        self._dot = QFrame()
        self._dot.setObjectName("sb-dot")
        self._dot.setProperty("state", "ready")
        state_box.addWidget(self._dot, alignment=Qt.AlignmentFlag.AlignVCenter)
        self._state = QLabel(STATE_WORDS["ready"])
        self._state.setObjectName("sb-status")
        self._state.setProperty("state", "ready")
        state_box.addWidget(self._state)
        self._state_swap = TextSwap(self._state, rise=sp(6))
        self._status.setToolTip(LOG_HINT)
        layout.addWidget(self._status)
        self._halo_at = None
        self._halo = FrameTimer(self)
        self._halo.setInterval(33)
        self._halo.timeout.connect(self._halo_frame)

        # Steps waiting their turn (see show_status).
        self._queue = []            # (state, text)
        self._shown = ("ready", STATE_WORDS["ready"])
        self._shown_at = 0.0
        self._wait = QTimer(self)
        self._wait.setSingleShot(True)
        self._wait.timeout.connect(self._next)

        # Live stats (hidden until the first update arrives).
        self._stats = QWidget()
        stats_layout = QHBoxLayout(self._stats)
        stats_layout.setContentsMargins(0, 0, 0, 0)
        stats_layout.setSpacing(sp(22))
        self._values = {}
        self._pairs = {}
        for key in ("load", "frame", "skip", "buffer"):
            pair = QWidget()
            pair_layout = QHBoxLayout(pair)
            pair_layout.setContentsMargins(0, 0, 0, 0)
            pair_layout.setSpacing(sp(6))
            caption = QLabel(key)
            caption.setObjectName("sb-text")
            value = QLabel("-")
            value.setObjectName("sb-value")
            pair_layout.addWidget(caption)
            pair_layout.addWidget(value)
            stats_layout.addWidget(pair)
            self._values[key] = value
            self._pairs[key] = pair
        layout.addWidget(self._stats)

        self._hint = QLabel("stats appear when running")
        self._hint.setObjectName("sb-text")
        layout.addWidget(self._hint)
        self._stats.setVisible(False)
        self._live = False

        layout.addStretch(1)
        source = QHBoxLayout()
        source.setSpacing(sp(6))
        source_caption = QLabel("source")
        source_caption.setObjectName("sb-text")
        source_value = QLabel("vb-cable")
        source_value.setObjectName("sb-value")
        source.addWidget(source_caption)
        source.addWidget(source_value)
        layout.addLayout(source)

    # -- state ---------------------------------------------------------------
    def show_status(self, state: str, message: str = "") -> None:
        """A status message (state: ready | processing | error). Steps
        queue behind one that hasn't been up STEP_MIN_MS yet; an error
        shows at once and drops anything waiting."""
        text = status_text(state, message)
        if state == "error":
            self._queue.clear()
            self._wait.stop()
            self._apply(state, text)
            return
        last = self._queue[-1] if self._queue else self._shown
        if last == (state, text):
            return
        self._queue.append((state, text))
        while len(self._queue) > QUEUE_MAX:
            self._queue.pop(0)
        self._next()

    def _next(self) -> None:
        if not self._queue or self._wait.isActive():
            return
        held = self._shown[0] == "processing" and self._shown[1] != (
            STATE_WORDS["processing"])
        left = STEP_MIN_MS - (time.monotonic() - self._shown_at) * 1000.0
        if held and left > 1:
            self._wait.start(int(left))
            return
        self._apply(*self._queue.pop(0))
        if self._queue:
            self._next()

    def set_state(self, state: str, text: str = None) -> None:
        """Show `state` now (text defaults to its word), skipping the
        queue."""
        self._queue.clear()
        self._wait.stop()
        self._apply(state, text or STATE_WORDS.get(state, state))

    def _apply(self, state: str, text: str) -> None:
        self._shown = (state, text)
        self._shown_at = time.monotonic()
        metrics = self._state.fontMetrics()
        shown = metrics.elidedText(text, Qt.TextElideMode.ElideRight,
                                   sp(STATUS_MAX_W))
        self._status.setToolTip(
            LOG_HINT if shown == text and state != "error"
            else f"{text}\n{LOG_HINT}")

        def restyle(label=self._state, state=state):
            label.setProperty("state", state)
            label.style().unpolish(label)
            label.style().polish(label)

        self._state_swap.set_text(shown, on_apply=restyle)
        self._sync_hint()
        self._dot.setProperty("state", state)
        self._dot.style().unpolish(self._dot)
        self._dot.style().polish(self._dot)
        self._set_halo(state == "processing"
                       and text == STATE_WORDS["processing"])

    # -- the live halo -------------------------------------------------------
    def _set_halo(self, on: bool) -> None:
        """While isolating, a halo leaves the dot every HALO_MS."""
        if on and ambient_ok():
            if self._halo_at is None:
                self._halo_at = time.monotonic()
                self._halo.start()
        elif self._halo_at is not None:
            self._halo_at = None
            self._halo.stop()
            self.update(self._halo_rect())

    def refresh_motion(self) -> None:
        """Reduce motion changed (animations.set_still): the live halo
        stops, or starts again while isolating."""
        state, text = self._shown
        self._set_halo(state == "processing"
                       and text == STATE_WORDS["processing"])

    def _halo_rect(self) -> QRect:
        centre = self._dot.mapTo(self, self._dot.rect().center())
        reach = int(self._dot.width() * HALO_GROWTH / 2) + 2
        return QRect(centre.x() - reach, centre.y() - reach,
                     2 * reach + 1, 2 * reach + 1)

    def _halo_frame(self) -> None:
        if self.isVisible():
            self.update(self._halo_rect())

    def showEvent(self, event):  # noqa: N802 (Qt override)
        super().showEvent(event)
        if self._halo_at is not None:
            self._halo.start()

    def hideEvent(self, event):  # noqa: N802 (Qt override)
        self._halo.stop()   # e.g. hidden to the tray: no wake-ups
        super().hideEvent(event)

    def paintEvent(self, event):  # noqa: N802 (Qt override)
        p = QPainter(self)
        opt = QStyleOption()
        opt.initFrom(self)
        self.style().drawPrimitive(
            QStyle.PrimitiveElement.PE_Widget, opt, p, self)
        if self._halo_at is not None:
            period = HALO_BREATH_MS if breathing() else HALO_MS
            phase = ((time.monotonic() - self._halo_at) * 1000.0
                     % period) / period
            if phase < 0.7:
                u = phase / 0.7
                colour = QColor(current_theme()["accent"])
                colour.setAlphaF(0.6 * (1.0 - u))
                half = self._dot.width() / 2.0
                centre = (QPointF(self._dot.mapTo(self, QPoint(0, 0)))
                          + QPointF(half, self._dot.height() / 2.0))
                radius = half * (1.0 + (HALO_GROWTH - 1.0) * ease_out(u))
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(colour)
                p.drawEllipse(centre, radius, radius)
        p.end()

    def _sync_hint(self) -> None:
        """"stats appear when running" only while idle (not beside a
        step or an error)."""
        self._hint.setVisible(not self._live and self._shown[0] == "ready")

    @property
    def status_shown(self) -> str:
        """The full status text on show (before any cutting short)."""
        return self._shown[1]

    # -- stats ---------------------------------------------------------------
    @staticmethod
    def load_object_name(rtf: float) -> str:
        if rtf < 0.8:
            return "sb-good"
        if rtf < 1.0:
            return "sb-warn"
        return "sb-bad"

    def _repolish(self, label: QLabel) -> None:
        label.style().unpolish(label)
        label.style().polish(label)

    def update_stats(self, stats: dict) -> None:
        if not self._live:
            self._live = True
            self._stats.setVisible(True)
            self._sync_hint()
            # The readouts arrive one after another.
            stagger_in(list(self._pairs.values()), step_ms=60,
                       duration_ms=360)
        rtf = stats.get("rtf", 0)
        load = self._values["load"]
        load.setText(f"{rtf:.2f}x")
        load.setObjectName(self.load_object_name(rtf))
        self._repolish(load)
        self._values["frame"].setText(f"{stats.get('avg_time_ms', 0):.1f} ms")
        skipping = stats.get("aad_bypass_active")
        self._pairs["skip"].setVisible(skipping is not None)
        self._values["skip"].setText("on" if skipping else "off")
        self._values["buffer"].setText(
            f"{stats.get('input_buffer', 0)}/{stats.get('output_buffer', 0)}")

    def reset(self) -> None:
        """Back to the idle look (stats hidden, hint shown)."""
        load = self._values["load"]
        load.setObjectName("sb-value")
        self._repolish(load)
        for value in self._values.values():
            value.setText("-")
        self._pairs["skip"].setVisible(True)
        self._live = False
        self._stats.setVisible(False)
        self._sync_hint()
