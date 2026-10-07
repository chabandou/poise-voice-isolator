"""
Poise Voice Isolator - Stats Panel Widget

Real-time statistics display panel.
"""
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt

from .phosphor import PhosphorIcon
from ..scaling import isp

ICON_SIZE = 26
ROW_SPACING = 14


class StatsPanel(QFrame):
    """
    Panel displaying real-time processing statistics.
    
    Shows:
    - RTF (Real-Time Factor)
    - Average processing time
    - AAD bypass percentage
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setObjectName("stats-panel")
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup the panel UI (rows spread evenly, dividers between)."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(63, 42, 51, 42)
        layout.setSpacing(10)

        self._rtf_widget = self._create_stat_widget("percent", "RTF", "0.00")
        layout.addWidget(self._rtf_widget)
        layout.addWidget(self._make_divider())
        layout.addStretch(1)

        self._time_widget = self._create_stat_widget(
            "clock", "AVG TIME", "0.0 ms")
        layout.addWidget(self._time_widget)
        layout.addWidget(self._make_divider())
        layout.addStretch(1)

        self._aad_widget = self._create_stat_widget(
            "pulse", "AAD BYPASS", "0%")
        layout.addWidget(self._aad_widget)
        layout.addWidget(self._make_divider())
        layout.addStretch(1)

        self._buffer_widget = self._create_stat_widget(
            "buffer", "BUFFER", "0 / 0")
        layout.addWidget(self._buffer_widget)

    @staticmethod
    def _make_divider() -> QFrame:
        """Thin divider, indented past the icon column like the design."""
        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFrameShape(QFrame.Shape.HLine)
        wrap = QFrame()
        wrap_layout = QHBoxLayout(wrap)
        wrap_layout.setContentsMargins(isp(ICON_SIZE) + ROW_SPACING, 0, 0, 0)
        wrap_layout.setSpacing(0)
        wrap_layout.addWidget(divider)
        return wrap

    def _create_stat_widget(self, icon: str, label: str,
                            initial_value: str) -> QFrame:
        """Create a single stat display widget (icon + label + value)."""
        frame = QFrame()
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(ROW_SPACING)

        layout.addWidget(PhosphorIcon(icon, size=ICON_SIZE))

        # Label
        name_label = QLabel(label)
        name_label.setObjectName("stat-label")
        name_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(name_label)

        layout.addStretch()

        # Value label
        value_label = QLabel(initial_value)
        value_label.setObjectName("stat-value")
        value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(value_label)

        # Store reference to value label
        frame.value_label = value_label

        return frame
    
    def update_stats(self, stats: dict):
        """
        Update displayed statistics.
        
        Args:
            stats: Dictionary with stats from processor.get_stats()
        """
        # Update RTF
        rtf = stats.get('rtf', 0)
        rtf_label = self._rtf_widget.value_label
        rtf_label.setText(f"{rtf:.2f}")
        
        # Color-code RTF
        if rtf < 0.8:
            rtf_label.setObjectName("stat-good")
        elif rtf < 1.0:
            rtf_label.setObjectName("stat-warning")
        else:
            rtf_label.setObjectName("stat-bad")
        rtf_label.style().unpolish(rtf_label)
        rtf_label.style().polish(rtf_label)
        
        # Update processing time
        avg_time = stats.get('avg_time_ms', 0)
        self._time_widget.value_label.setText(f"{avg_time:.1f} ms")
        
        # Update AAD bypass
        bypass_ratio = stats.get('aad_bypass_ratio', 0)
        self._aad_widget.value_label.setText(f"{bypass_ratio * 100:.0f}%")
        
        # Update buffer status
        input_buf = stats.get('input_buffer', 0)
        output_buf = stats.get('output_buffer', 0)
        self._buffer_widget.value_label.setText(f"{input_buf} / {output_buf}")
    
    def reset(self):
        """Reset all stats to initial values."""
        self._rtf_widget.value_label.setText("0.00")
        self._rtf_widget.value_label.setObjectName("stat-value")
        self._time_widget.value_label.setText("0.0 ms")
        self._aad_widget.value_label.setText("0%")
        self._buffer_widget.value_label.setText("0 / 0")
        
        # Refresh styles
        for widget in [self._rtf_widget, self._time_widget, self._aad_widget, self._buffer_widget]:
            widget.value_label.style().unpolish(widget.value_label)
            widget.value_label.style().polish(widget.value_label)
