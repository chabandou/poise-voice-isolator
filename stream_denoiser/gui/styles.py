"""
Poise Voice Isolator - Modern Dark Theme Stylesheet

A sleek, modern dark theme with glassmorphism-inspired elements, 
teal/cyan accents, and cohesive rounded styling.
Updated for full PyQt6 compatibility (removed unsupported webkit props).
"""

POISE_STYLESHEET = """
/* =================================================================================
   GLOBAL SETTINGS
   ================================================================================= */
QMainWindow {
    /* Subtle radial gradient background - Neutral Gray, Top-Right focus */
    background: qradialgradient(cx: 0.85, cy: 0, radius: 1.2, fx: 0.85, fy: 0, stop: 0 #2d2d30, stop: 1 #0a0a0a);
    color: #f8fafc;
}

QWidget {
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 14px;
    color: #f1f5f9;
}

/* =================================================================================
   CONTAINERS & GROUP BOXES (Glassmorphism)
   ================================================================================= */
QGroupBox {
    background-color: transparent;
    border: none;
    margin-top: 0;
    padding: 0;
}

QGroupBox::title {
    color: transparent;
    background-color: transparent;
    border: none;
}

/* =================================================================================
   LABELS & TEXT
   ================================================================================= */
QLabel {
    color: #e2e8f0;
    background-color: transparent;
}

QLabel#title {
    font-size: 36px;
    font-weight: 800;
    color: #a5f3fc; /* Cyan-200: Lighter & softer */
    padding-bottom: 5px;
    letter-spacing: 1px;
}


/* Status Light Indicator */
QLabel#status-light {
    background-color: #0f172a;
    border-radius: 5px; /* Perfect circle for 10px size */
    border: 2px solid #334155;
}
QLabel#status-light[state="ready"] {
    background-color: #4ade80; /* Green */
    border: 2px solid #22c55e;
}
QLabel#status-light[state="processing"] {
    background-color: #22d3ee; /* Cyan */
    border: 2px solid #06b6d4;
}
QLabel#status-light[state="error"] {
    background-color: #f87171; /* Red */
    border: 2px solid #ef4444;
}

QLabel#status-text {
    font-weight: 600;
    color: #94a3b8;
}

QLabel#status-text[state="ready"] {
    color: #4ade80; /* Green */
}
QLabel#status-text[state="processing"] {
    color: #22d3ee; /* Cyan */
}
QLabel#status-text[state="error"] {
    color: #f87171; /* Red */
}

QLabel#stat-value { font-size: 20px; font-weight: 700; color: #f8fafc; }
QLabel#stat-label { font-size: 13px; font-weight: 700; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; }

/* Stat colors */
QLabel#stat-good { color: #4ade80; } /* Green-400 */
QLabel#stat-warning { color: #facc15; } /* Yellow-400 */
QLabel#stat-bad { color: #f87171; } /* Red-400 */


/* =================================================================================
   INPUTS & DROPDOWNS
   ================================================================================= */
QComboBox {
    background-color: #18181b; /* Neutral dark gray */
    border: 1px solid rgba(148, 163, 184, 0.3);
    border-radius: 8px;
    padding: 5px 15px; /* Reduced vertical padding */
    min-height: 40px;  /* Force tall height */
    max-height: 40px;  /* Restrict expansion */
    color: #f1f5f9;
    font-weight: 500;
    font-size: 14px;
    line-height: 40px; /* Center text vertically */
}

QComboBox:hover {
    border: 1px solid #67e8f9; /* Lighter Cyan */
    background-color: #27272a; /* Zinc 800 */
}

QComboBox:on { /* shift text when menu is open */
    border: 1px solid #5eead4; /* Lighter Teal */
    background-color: #27272a;
}

QComboBox:disabled {
    background-color: #0d0d0f; /* Very dark/black */
    color: #52525b; /* Zinc-600 */
    border: 1px solid #27272a;
    opacity: 0.5; /* Note: Qt QSS opacity on widgets might not work as expected everywhere, usually rely on color modification */
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 35px;
    border-left-width: 0px;
    border-top-right-radius: 8px;
    border-bottom-right-radius: 8px;
}

QComboBox::down-arrow {
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #94a3b8;
    margin-right: 15px;
}

QComboBox QAbstractItemView {
    background-color: #18181b;
    border: 1px solid #27272a;
    border-radius: 8px;
    color: #f1f5f9;
    padding: 8px;
    selection-background-color: #2dd4bf;
    selection-color: #0f172a;
    outline: none;
}

/* =================================================================================
   BUTTONS
   ================================================================================= */
QPushButton {
    background-color: rgba(39, 39, 42, 0.6); /* Zinc 800 alpha */
    border: 1px solid rgba(113, 113, 122, 0.2);
    border-radius: 8px;
    padding: 10px 20px;
    color: #f8fafc;
    font-weight: 600;
}

QPushButton:hover {
    background-color: rgba(63, 63, 70, 0.8); /* Zinc 700 */
    border-color: #a1a1aa;
}

QPushButton:pressed {
    background-color: #334155;
    margin-top: 1px;
}

/* Main Toggle Button - Big Pill Shape with Glow */
QPushButton#start-button {
    /* More prominent gradient: Deep Cyan to Bright Teal (Lighter) */
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #06b6d4, stop:1 #5eead4); 
    border: 2px solid transparent; /* Invisible border that reserves space to prevent shifting */
    border-radius: 30px; /* Safe pill radius for ~50-60px height */
    padding: 12px 45px;
    font-size: 25px;
    font-weight: 700;
    color: #0f172a; 
    min-width: 220px;
    min-height: 47px;
}

QPushButton#start-button:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #22d3ee, stop:1 #99f6e4); /* Even Brighter hover */
    border: 2px solid transparent; /* Keep border reserved but invisible */
}

QPushButton#start-button:pressed {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0891b2, stop:1 #2dd4bf);
    padding-top: 14px; /* Reduced pressed offset */
}

/* Stop Button state */
QPushButton#stop-button {
    background-color: transparent;
    border: 2px solid #ef4444; /* Red border */
    border-radius: 30px; /* Safe pill radius */
    padding: 12px 45px;
    font-size: 25px;
    font-weight: 700;
    color: #ef4444;
    min-width: 220px;
    min-height: 47px;
}

QPushButton#stop-button:hover {
    background-color: rgba(239, 68, 68, 0.1);
    border-color: #f87171;
}

QPushButton#stop-button:pressed {
    background-color: rgba(239, 68, 68, 0.2);
}

/* Refresh Button */
QPushButton#refresh-btn {
    background-color: transparent;
    border: none;
    font-size: 18px;
    color: #94a3b8;
    padding: 0;
}
QPushButton#refresh-btn:hover { color: #22d3ee; }

/* =================================================================================
   CONTROLS (SLIDERS & CHECKBOXES)
   ================================================================================= */
QSlider {
    min-height: 26px;
}

QSlider::groove:horizontal {
    border: none;
    height: 8px; /* Thicker groove */
    background: rgba(39, 39, 42, 1); /* Zinc 800 */
    border-radius: 4px;
}

QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #67e8f9, stop:1 #5eead4); /* Lighter gradient */
    border-radius: 4px;
}

QSlider::handle:horizontal {
    background: #f8fafc;
    width: 24px;
    height: 24px;
    margin: -8px 0; /* center on groove */
    border-radius: 12px;
    border: 2px solid #a5f3fc; /* Lighter Ring */
}

QSlider::handle:horizontal:hover {
    background: #a5f3fc;
    width: 26px;
    height: 26px;
    margin: -9px 0;
    border-radius: 13px;
    border-color: #f8fafc;
}

QSlider::sub-page:horizontal:disabled {
    background: #27272a; /* Zinc-800 - hiding the active gradient */
}

QSlider::handle:horizontal:disabled {
    background: #3f3f46; /* Zinc-700 */
    border: 2px solid #27272a;
}

/* Checkboxes */
QCheckBox {
    spacing: 12px;
    color: #e2e8f0;
    font-weight: 500;
    min-height: 24px; /* Ensure height for text */
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 8px; /* Circular */
    border: 2px solid #475569;
    background-color: transparent;
}

QCheckBox::indicator:hover {
    border-color: #67e8f9;
    background-color: rgba(103, 232, 249, 0.1);
}

/* Checked State - Simple square fill */
QCheckBox::indicator:checked {
    background-color: #5eead4; /* Teal-300 */
    border: 2px solid #5eead4; /* Maintain border width to prevent shifting */
}


/* =================================================================================
   PANELS & MISC
   ================================================================================= */
/* VAD Panel Container - Matches Dropdown Style */
QFrame#vad-panel {
    background-color: #18181b; /* Neutral dark gray */
    border: 1px solid rgba(148, 163, 184, 0.3);
    border-radius: 12px; /* Slightly rounder than dropdowns for panel feel */
}

/* Stats Panel Container */
QFrame#stats-panel {
    background-color: #18181b; /* Neutral dark gray (Matches VAD panel) */
    border: 1px solid rgba(148, 163, 184, 0.3);
    border-radius: 12px;
}

/* Tooltips */
QToolTip {
    background-color: #1e293b;
    border: 1px solid #334155;
    color: #f8fafc;
    padding: 5px;
    border-radius: 4px;
}
"""

# Modern Palette Accessor
COLORS = {
    'background': '#0a0a0a',
    'surface': '#18181b',
    'text': '#f8fafc',
    'text_secondary': '#a1a1aa',
    'accent_cyan': '#67e8f9',
    'accent_teal': '#5eead4',
    'success': '#4ade80',
    'warning': '#facc15',
    'error': '#f87171',
}
