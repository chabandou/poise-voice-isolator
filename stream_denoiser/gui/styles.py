"""
Poise Voice Isolator - Dashboard Theme

Card-based dark theme driven by gui/themes.py palettes: every hue in
this sheet is a {token} resolved per theme, so all colorways stay
self-matching. Custom-painted widgets (PowerButton, ToggleSwitch) draw
themselves from the same palette; icons come from the vendored
Phosphor SVGs (see widgets/phosphor.py).
"""

POISE_STYLESHEET = """
/* =================================================================================
   GLOBAL SETTINGS
   ================================================================================= */
QMainWindow {
    background-color: {bg};
    color: {text};
}

QWidget {
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 14px;
    color: {text};
}

/* =================================================================================
   SIDEBAR
   ================================================================================= */
QFrame#sidebar {
    background-color: {sidebar};
    border: none;
    border-right: 1px solid rgba(148, 163, 184, 0.12);
}

QLabel#logo {
    color: {text};
}

QPushButton#nav {
    background-color: transparent;
    border: none;
    border-top-left-radius: 0px;
    border-bottom-left-radius: 0px;
    border-top-right-radius: 10px;
    border-bottom-right-radius: 10px;
    min-height: 52px;
    color: {nav_muted};
    font-size: 14px;
    font-weight: 500;
}

QPushButton#nav:hover {
    background-color: rgba(148, 163, 184, 0.08);
    color: {text};
}

QPushButton#nav[active="true"] {
    background-color: rgba({accent_rgb}, {ACCENT_WASH_ALPHA});
    color: {nav_active};
}

QLabel#nav-text {
    color: {nav_muted};
    font-size: 14px;
    font-weight: 500;
    background-color: transparent;
}

QPushButton#nav[active="true"] QLabel#nav-text {
    color: {nav_active};
}

QLabel#version {
    color: {muted};
    font-size: 11px;
    background-color: transparent;
}

/* =================================================================================
   CARDS
   ================================================================================= */
QFrame#card {
    background-color: {card};
    border: {CARD_BORDER_WIDTH}px solid rgba({border_rgb}, {border_alpha});
    border-radius: 16px;
}

QFrame#vb-pill {
    background-color: {pill};
    border: 1px solid rgba(148, 163, 184, 0.12);
    border-radius: 32px;
}

QFrame#icon-circle {
    background-color: {badge_bg};
    border: none;
    border-radius: 22px;
}

QFrame#divider {
    background-color: rgba({divider_rgb}, {divider_alpha});
    border: none;
    max-height: 1px;
}

/* =================================================================================
   LABELS & TEXT
   ================================================================================= */
QLabel {
    color: {text};
    background-color: transparent;
}

QLabel#section {
    color: {muted};
    font-size: 12px;
    font-weight: 700;
}

QLabel#device-title {
    color: {device_title};
    font-size: 14px;
    font-weight: 700;
}

QLabel#page-title {
    font-size: 22px;
    font-weight: 700;
    color: {text};
}

QLabel#page-subtitle {
    font-size: 13px;
    color: {muted};
}

QLabel#card-title {
    font-size: 16px;
    font-weight: 700;
    color: {text};
}

QLabel#card-subtitle {
    font-size: 12px;
    color: {muted};
}

QLabel#status-line {
    font-size: 12px;
    color: {muted};
}

QLabel#status-line[state="processing"] {
    color: {accent};
}

QLabel#status-line[state="error"] {
    color: {error};
}

QLabel#stat-value { font-size: 20px; font-weight: 700; color: {text}; }
QLabel#stat-label { font-size: 13px; font-weight: 700; color: {muted}; }

/* Stat colors */
QLabel#stat-good { font-size: 20px; font-weight: 700; color: {success}; }
QLabel#stat-warning { font-size: 20px; font-weight: 700; color: {warning}; }
QLabel#stat-bad { font-size: 20px; font-weight: 700; color: {error}; }

QLabel#thresh-value {
    font-size: 15px;
    font-weight: 600;
    color: {accent};
}

/* =================================================================================
   DEVICE DROPDOWNS (underline style)
   ================================================================================= */
QComboBox#device-combo {
    background-color: transparent;
    border: none;
    border-bottom: 1px solid rgba(148, 163, 184, 0.25);
    border-radius: 0px;
    padding: 0px 28px 10px 0px;
    min-height: 30px;
    color: {text};
    font-weight: 500;
    font-size: 17px;
}

QComboBox#device-combo:hover {
    border-bottom: 1px solid {accent};
}

QComboBox#device-combo:on {
    border-bottom: 1px solid {accent};
}

QComboBox#device-combo:focus {
    outline: none;
}

QComboBox#device-combo:disabled {
    color: #52525b;
    border-bottom: 1px solid rgba(82, 82, 91, 0.4);
}

QComboBox#device-combo::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border: none;
}

QComboBox#device-combo::down-arrow {
    image: url({ASSETS_DIR}/chevron-down.svg);
    width: 12px;
    height: 8px;
    margin-right: 6px;
}

/* Dropdown popups (shared list styling for both combo styles).
   NOTE: QSS ::item subcontrols never reach combo popup views, so row
   height, dividers, and row states are painted by PopupItemDelegate
   (see widgets/combo.py) — only the frame itself is styled here.
   The popup's outer frame is styled in code (AnimatedComboBox): style-
   sheets don't cascade into top-level popup windows, so it carries its
   own tiny sheet. */
QComboBox#device-combo QAbstractItemView,
QComboBox#settings-combo QAbstractItemView {
    background-color: {pill};
    color: {text};
    border: 1px solid rgba(148, 163, 184, 0.2);
    border-radius: 10px;
    padding: 6px;
    outline: none;
    font-size: 15px;
    selection-background-color: {accent};
    selection-color: {bg};
}

/* Settings-page dropdown (boxed style) */
QComboBox#settings-combo {
    background-color: {pill};
    border: 1px solid rgba(148, 163, 184, 0.25);
    border-radius: 8px;
    padding: 6px 12px;
    min-height: 32px;
    color: {text};
    font-size: 14px;
}

QComboBox#settings-combo:hover {
    border: 1px solid {accent};
}

QComboBox#settings-combo:on {
    border: 1px solid {accent};
}

QComboBox#settings-combo:focus {
    outline: none;
}

QComboBox#settings-combo::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 28px;
    border: none;
}

QComboBox#settings-combo::down-arrow {
    image: url({ASSETS_DIR}/chevron-down.svg);
    width: 12px;
    height: 8px;
    margin-right: 8px;
}

/* =================================================================================
   BUTTONS
   ================================================================================= */
QPushButton#ghost {
    background-color: rgba(148, 163, 184, 0.08);
    border: 1px solid rgba(148, 163, 184, 0.18);
    border-radius: 8px;
    padding: 8px 18px;
    color: {text};
    font-weight: 600;
    font-size: 13px;
}

QPushButton#ghost:hover {
    border-color: {accent};
    color: {accent_light};
}

QPushButton#ghost:pressed {
    background-color: rgba({accent_rgb}, {ACCENT_WASH_ALPHA});
}

QPushButton#icon-btn {
    background-color: transparent;
    border: none;
    border-radius: 6px;
    padding: 0px;
}

QPushButton#icon-btn:hover {
    background-color: rgba({accent_rgb}, {ACCENT_WASH_ALPHA});
}

/* Legacy refresh button id (kept for compatibility) */
QPushButton#refresh-btn {
    background-color: transparent;
    border: none;
    font-size: 18px;
    color: #94a3b8;
    padding: 0;
}
QPushButton#refresh-btn:hover { color: {accent}; }

/* =================================================================================
   SLIDERS
   ================================================================================= */
QSlider {
    min-height: 30px;
}

QSlider::groove:horizontal {
    border: none;
    height: 10px;
    background: {groove};
    border-radius: 5px;
}

QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {accent}, stop:1 {accent_light});
    border-radius: 5px;
}

QSlider::handle:horizontal {
    background: {text};
    width: 20px;
    height: 20px;
    margin: -7px 0;
    border-radius: 11px;
    border: 2px solid {accent};
}

QSlider::handle:horizontal:hover {
    background: {accent_light};
    border-radius: 11px;
    border-color: {text};
}

QSlider::sub-page:horizontal:disabled {
    background: {groove};
}

QSlider::handle:horizontal:disabled {
    background: #3f3f46;
    border: 2px solid #27272a;
}

/* =================================================================================
   CHECKBOXES (settings page)
   ================================================================================= */
QCheckBox {
    spacing: 12px;
    color: {text};
    font-weight: 500;
    min-height: 24px;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 2px solid #475569;
    background-color: transparent;
}

QCheckBox::indicator:hover {
    border-color: {accent};
}

QCheckBox::indicator:checked {
    background-color: {accent};
    border: 2px solid {accent};
}

/* =================================================================================
   LOG VIEWER
   ================================================================================= */
QTextEdit#logs {
    background-color: {sidebar};
    border: 1px solid rgba(148, 163, 184, 0.14);
    border-radius: 12px;
    color: {text};
    font-family: 'JetBrains Mono', 'Consolas', monospace;
    font-size: 12px;
    padding: 8px;
}

/* Tooltips: native (tray icons — fallback only) and the app-managed
   animated tooltip (see gui/tooltip.py) share one look, fully themed. */
QToolTip,
QLabel#poise-tip {
    background-color: {sidebar};
    border: 1px solid rgba({border_rgb}, {border_alpha});
    border-radius: 8px;
    padding: 8px 12px;
    color: {text};
    font-size: 14px;
}

/* Page scrollbars */
QScrollArea#page-scroll {
    border: none;
    background-color: transparent;
}

QWidget#page {
    background-color: {bg};
    border: none;
}

QScrollBar:vertical {
    background-color: transparent;
    width: 10px;
    margin: 2px;
}

QScrollBar::handle:vertical {
    background-color: rgba(148, 163, 184, 0.25);
    border-radius: 4px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background-color: rgba(148, 163, 184, 0.45);
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background-color: transparent;
}
"""

import os

_ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def _card_border_width(scale: float) -> int:
    """Outline thickness steps up with the UI scale (1px per ~0.5x)."""
    if scale < 1.25:
        return 1
    if scale < 1.75:
        return 2
    return 3


def get_stylesheet(scale=None, theme=None) -> str:
    """Build the theme with substituted assets, palette, and UI scale.

    Args:
        scale: UI scale factor override. None follows the detected screen
            scale, 1.0 returns the unscaled theme.
        theme: Theme id (see gui/themes.py). None follows the current theme.
    """
    from .scaling import scale_stylesheet, ui_scale
    from .themes import (
        ACCENT_WASH_ALPHA,
        KEYS,
        get_theme,
    )
    from . import themes as _themes
    factor = ui_scale() if scale is None else scale
    palette = get_theme(_themes.current_id() if theme is None else theme)
    css = POISE_STYLESHEET.replace("{ASSETS_DIR}", _ASSETS_DIR)
    for key in KEYS:
        css = css.replace("{" + key + "}", str(palette[key]))
    css = css.replace("{ACCENT_WASH_ALPHA}", str(ACCENT_WASH_ALPHA))
    # Substitute after px-scaling so the stepped width is not scaled twice.
    css = scale_stylesheet(css, factor)
    return css.replace("{CARD_BORDER_WIDTH}", str(_card_border_width(factor)))
