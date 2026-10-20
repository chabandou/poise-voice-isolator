"""
Poise Voice Isolator - Dashboard Theme

Card-based dark theme driven by gui/themes.py palettes: every hue in
this sheet is a {token} resolved per theme, so all colorways stay
self-matching. {HEADING_FONT} is the bundled heading face (gui/fonts.py);
{HEADING_WEIGHT}, {WINDOW_FILL} and {CARD_FILL} are optional per theme
(themes.STYLE_DEFAULTS: bold headings on flat surfaces unless a theme,
like Vigil or Eclipse, says otherwise).
Custom-painted widgets (DialButton, ToggleSwitch) draw
themselves from the same palette; icons come from the vendored
Phosphor SVGs (see widgets/phosphor.py).
"""

POISE_STYLESHEET = """
/* =================================================================================
   GLOBAL SETTINGS
   ================================================================================= */
QMainWindow {
    background-color: {WINDOW_FILL};
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
    font-family: {HEADING_FONT};
    font-size: 24px;
    font-weight: {HEADING_WEIGHT};
}

QPushButton#nav {
    background-color: transparent;
    border: none;
    border-radius: 10px;
    min-height: 50px;
    color: {nav_muted};
    font-size: 14px;
    font-weight: 500;
}

/* Hover wash is painted by NavButton (animated, same shape as the
   active highlight); QSS has no transitions. */
QPushButton#nav[active="true"] {
    background-color: transparent;
    color: {text};
}

QLabel#nav-text {
    color: {nav_muted};
    font-size: 14px;
    font-weight: 500;
    background-color: transparent;
}

QPushButton#nav[active="true"] QLabel#nav-text {
    color: {text};
}

QLabel#version {
    color: {muted};
    font-size: 11px;
    background-color: transparent;
}

QPushButton#update-pill {
    background-color: rgba({accent_rgb}, 0.12);
    border: 1px solid rgba({accent_rgb}, 0.30);
    border-radius: 11px;
    padding: 4px 12px;
    color: {accent};
    font-size: 11px;
    font-weight: 600;
}

QPushButton#update-pill:hover {
    background-color: rgba({accent_rgb}, 0.22);
}

/* About's Update: the ghost buttons' metrics (a 1px border in the
   fill colour keeps the height equal), filled in the accent. */
QPushButton#update {
    background-color: {accent};
    border: 1px solid {accent};
    border-radius: 10px;
    padding: 9px 18px;
    color: {bg};
    font-weight: 600;
    font-size: 13px;
}

QPushButton#update:hover {
    background-color: {accent_light};
    border-color: {accent_light};
}

QLabel#update-status {
    font-size: 12px;
    color: {muted};
}

/* =================================================================================
   CARDS
   ================================================================================= */
QFrame#card {
    background-color: {CARD_FILL};
    border: {CARD_BORDER_WIDTH}px solid rgba({border_rgb}, {border_alpha});
    border-radius: 16px;
}

QFrame#chip {
    background-color: rgba({secondary_rgb}, 0.16);
    border: none;
    border-radius: 12px;
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
    font-family: {HEADING_FONT};
    color: {text};
    font-size: 24px;
    font-weight: {HEADING_WEIGHT};
}

QLabel#page-title {
    font-family: {HEADING_FONT};
    font-size: 34px;
    font-weight: {HEADING_WEIGHT};
    color: {text};
}

QLabel#page-subtitle {
    font-size: 14px;
    color: {muted};
}

QLabel#card-title {
    font-family: {HEADING_FONT};
    font-size: 24px;
    font-weight: {HEADING_WEIGHT};
    color: {text};
}

/* Settings list rows / summary rows */
QLabel#row-title {
    font-family: {HEADING_FONT};
    font-size: 22px;
    font-weight: {HEADING_WEIGHT};
    color: {text};
}

QLabel#row-sub {
    font-size: 13px;
    color: {muted};
}

QLabel#row-value {
    font-family: {HEADING_FONT};
    font-size: 21px;
    font-weight: {HEADING_WEIGHT};
    color: {secondary};
}

/* Home headline + live status line */
QLabel#home-title {
    font-family: {HEADING_FONT};
    font-size: 36px;
    font-weight: {HEADING_WEIGHT};
    color: {text};
}

QLabel#log-path {
    font-family: 'JetBrains Mono', 'Cascadia Mono', 'Consolas', 'DejaVu Sans Mono', monospace;
    font-size: 12px;
    color: {muted};
}

QLabel#about-version {
    font-family: 'JetBrains Mono', 'Cascadia Mono', 'Consolas', 'DejaVu Sans Mono', monospace;
    font-size: 13px;
    color: {secondary};
}

/* VB-Cable recovery dialog */
QDialog#vb-dialog {
    background-color: {bg};
}

QFrame#err-chip {
    background-color: rgba(248, 113, 113, 0.14);
    border: none;
    border-radius: 12px;
}

QLabel#step-num {
    font-family: {HEADING_FONT};
    font-size: 14px;
    font-weight: {HEADING_WEIGHT};
    color: {secondary};
    border: 1px solid rgba({secondary_rgb}, 0.55);
    border-radius: 12px;
    min-width: 24px;
    max-width: 24px;
    min-height: 24px;
    max-height: 24px;
    background-color: transparent;
}

QLabel#code-box {
    font-family: 'JetBrains Mono', 'Cascadia Mono', 'Consolas', 'DejaVu Sans Mono', monospace;
    font-size: 12px;
    color: {text};
    background-color: {pill};
    border: 1px solid rgba(148, 163, 184, 0.2);
    border-radius: 8px;
    padding: 10px 12px;
}

QPushButton#primary {
    background-color: {accent};
    color: {bg};
    border: none;
    border-radius: 10px;
    padding: 10px 20px;
    font-weight: 700;
}

QPushButton#primary:hover {
    background-color: {accent_light};
}

QPushButton#primary:disabled {
    background-color: rgba({accent_rgb}, 0.3);
    color: {muted};
}

/* Status bar */
QStatusBar {
    background-color: {sidebar};
    border-top: 1px solid rgba(148, 163, 184, 0.12);
    min-height: 30px;
}

QStatusBar::item {
    border: none;
}

QLabel#sb-text,
QLabel#sb-value,
QLabel#sb-status,
QLabel#sb-good,
QLabel#sb-warn,
QLabel#sb-bad {
    font-family: 'JetBrains Mono', 'Cascadia Mono', 'Consolas', 'DejaVu Sans Mono', monospace;
    font-size: 12px;
    background-color: transparent;
}

QLabel#sb-text { color: {muted}; }
QLabel#sb-value { color: {text}; }
QLabel#sb-status { color: {text}; }
QLabel#sb-status[state="error"] { color: {error}; }
QLabel#sb-good { color: {success}; }
QLabel#sb-warn { color: {warning}; }
QLabel#sb-bad { color: {error}; }

QFrame#sb-dot {
    background-color: {muted};
    border: none;
    border-radius: 4px;
    min-width: 8px;
    max-width: 8px;
    min-height: 8px;
    max-height: 8px;
}

QFrame#sb-dot[state="processing"] { background-color: {accent}; }
QFrame#sb-dot[state="error"] { background-color: {error}; }

QLabel#card-subtitle {
    font-size: 12px;
    color: {muted};
}

QLabel#status-line {
    font-size: 15px;
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

/* =================================================================================
   DEVICE DROPDOWNS (underline style)
   ================================================================================= */
QComboBox#device-combo {
    background-color: {pill};
    border: 1px solid rgba(148, 163, 184, 0.25);
    border-radius: 10px;
    padding: 0px 14px;
    min-height: 46px;
    color: {text};
    font-weight: 500;
    font-size: 15px;
}

/* No :hover / open border here: AnimatedComboBox paints the gold ring
   (hover is lost while its popup holds the mouse; see widgets/combo.py). */

QComboBox#device-combo:focus {
    outline: none;
}

QComboBox#device-combo:disabled {
    color: #52525b;
    border: 1px solid rgba(82, 82, 91, 0.4);
}

QComboBox#device-combo::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 38px;
    border: none;
    border-left: 1px solid rgba(148, 163, 184, 0.2);
}

/* The chevron is painted by AnimatedComboBox (it turns as the list
   opens), and the list itself is its card popup (widgets/combo.py). */
QComboBox#device-combo::down-arrow {
    image: none;
    width: 12px;
    height: 8px;
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
    image: url("{ASSETS_DIR}/chevron-down.svg");
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
    border-radius: 10px;
    padding: 9px 18px;
    color: {text};
    font-weight: 600;
    font-size: 13px;
}

QPushButton#ghost:hover {
    border-color: {secondary};
}

QPushButton#ghost:pressed {
    background-color: rgba({accent_rgb}, {ACCENT_WASH_ALPHA});
}

/* Donate: filled in the secondary colour with a dark label. The fill and
   the offset hover ring are painted by DonateButton (QSS can't draw an
   outline with a gap); the padding includes the ring's 5px margin. */
QPushButton#donate {
    background-color: transparent;
    border: none;
    padding: 14px 23px;
    color: {bg};
    font-weight: 700;
    font-size: 13px;
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
    height: 4px;
    background: {groove};
    border-radius: 2px;
}

QSlider::sub-page:horizontal {
    background: {accent};
    border-radius: 2px;
}

QSlider::handle:horizontal {
    background: {secondary};
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 4px;
    border: none;
}

QSlider::handle:horizontal:hover {
    background: {text};
}

QSlider::sub-page:horizontal:disabled {
    background: {groove};
}

QSlider::handle:horizontal:disabled {
    background: #3f3f46;
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
QPlainTextEdit#logs {
    background-color: {sidebar};
    border: 1px solid rgba(148, 163, 184, 0.14);
    border-radius: 12px;
    color: {text};
    /* Family is set in code (MainWindow._build_logs_page): QSS only tries
       the first family, so an uninstalled one falls back to a sans font. */
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
    background-color: {WINDOW_FILL};
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

# Qt Style Sheets require forward slashes in url() — even on Windows —
# and quoting so paths with spaces/colons (e.g. "C:/Users/John Doe/…")
# still parse. Without this, every Windows launch logs
# "Could not parse stylesheet of object MainWindow" twice (once per
# down-arrow rule: device-combo + settings-combo).
_ASSETS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "assets"
).replace(os.sep, "/")


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
        STYLE_DEFAULTS,
        get_theme,
    )
    from . import themes as _themes
    factor = ui_scale() if scale is None else scale
    palette = get_theme(_themes.current_id() if theme is None else theme)
    css = POISE_STYLESHEET.replace("{ASSETS_DIR}", _ASSETS_DIR)
    for key in KEYS:
        css = css.replace("{" + key + "}", str(palette[key]))
    css = css.replace("{ACCENT_WASH_ALPHA}", str(ACCENT_WASH_ALPHA))
    # Optional theme styling (STYLE_DEFAULTS): fills fall back to the
    # flat palette colours.
    def styled(key):
        return palette.get(key, STYLE_DEFAULTS[key])
    css = css.replace("{HEADING_WEIGHT}", str(styled("heading_weight")))
    css = css.replace("{WINDOW_FILL}", styled("window_fill") or palette["bg"])
    css = css.replace("{CARD_FILL}", styled("card_fill") or palette["card"])
    from .fonts import heading_css
    css = css.replace("{HEADING_FONT}", heading_css())
    # Substitute after px-scaling so the stepped width is not scaled twice.
    css = scale_stylesheet(css, factor)
    return css.replace("{CARD_BORDER_WIDTH}", str(_card_border_width(factor)))
