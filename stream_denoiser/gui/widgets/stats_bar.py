"""
Poise Voice Isolator - Stats Bar

One-line performance readout for the window's status bar:

    * standby        load 0.11x   frame 1.2 ms   skipped 38%   buffer 2/2        source vb-cable

Replaces the old stats card on Home. Same update_stats()/reset() contract
as the former StatsPanel (keys: rtf, avg_time_ms, aad_bypass_ratio,
input_buffer, output_buffer). The load figure is colour-coded the way the
card was: < 0.8 good, < 1.0 warning, otherwise bad.
"""
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget
from PyQt6.QtCore import Qt

from ..scaling import sp

STATE_WORDS = {
    "ready": "standby",
    "processing": "working",
    "error": "error",
}


class StatsBar(QWidget):
    """Status-bar content: state dot + word, live stats, routing source."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("stats-bar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(sp(16), 0, sp(16), 0)
        layout.setSpacing(sp(22))

        state_box = QHBoxLayout()
        state_box.setSpacing(sp(8))
        self._dot = QFrame()
        self._dot.setObjectName("sb-dot")
        self._dot.setProperty("state", "ready")
        state_box.addWidget(self._dot, alignment=Qt.AlignmentFlag.AlignVCenter)
        self._state = QLabel(STATE_WORDS["ready"])
        self._state.setObjectName("sb-value")
        state_box.addWidget(self._state)
        layout.addLayout(state_box)

        # Live stats (hidden until the first update arrives).
        self._stats = QWidget()
        stats_layout = QHBoxLayout(self._stats)
        stats_layout.setContentsMargins(0, 0, 0, 0)
        stats_layout.setSpacing(sp(22))
        self._values = {}
        for key, name in (("load", "load"), ("frame", "frame"),
                          ("skipped", "skipped"), ("buffer", "buffer")):
            pair = QHBoxLayout()
            pair.setSpacing(sp(6))
            caption = QLabel(name)
            caption.setObjectName("sb-text")
            value = QLabel("-")
            value.setObjectName("sb-value")
            pair.addWidget(caption)
            pair.addWidget(value)
            stats_layout.addLayout(pair)
            self._values[key] = value
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
    def set_state(self, state: str, word: str = None) -> None:
        """state: ready | processing | error; word overrides the label."""
        self._dot.setProperty("state", state)
        self._state.setText(word or STATE_WORDS.get(state, state))
        self._dot.style().unpolish(self._dot)
        self._dot.style().polish(self._dot)

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
            self._hint.setVisible(False)
        rtf = stats.get("rtf", 0)
        load = self._values["load"]
        load.setText(f"{rtf:.2f}x")
        load.setObjectName(self.load_object_name(rtf))
        self._repolish(load)
        self._values["frame"].setText(f"{stats.get('avg_time_ms', 0):.1f} ms")
        self._values["skipped"].setText(
            f"{stats.get('aad_bypass_ratio', 0) * 100:.0f}%")
        self._values["buffer"].setText(
            f"{stats.get('input_buffer', 0)}/{stats.get('output_buffer', 0)}")

    def reset(self) -> None:
        """Back to the idle look (stats hidden, hint shown)."""
        load = self._values["load"]
        load.setObjectName("sb-value")
        self._repolish(load)
        for value in self._values.values():
            value.setText("-")
        self._live = False
        self._stats.setVisible(False)
        self._hint.setVisible(True)
