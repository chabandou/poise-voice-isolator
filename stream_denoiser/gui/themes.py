"""
Poise Voice Isolator - Color Themes

Named, self-matching palettes for the GUI. Every theme carries the full
token set consumed by styles.get_stylesheet() and the painted widgets,
so switching themes can never leave a stray color behind.

Themes ship with the app; the selection persists in Settings ("halcyon"
is the default and preserves the original look).
"""
from typing import Dict, List

#: Palette keys every theme must define.
KEYS = (
    "bg", "sidebar", "card", "pill", "groove",
    "text", "muted", "device_title", "nav_active", "nav_muted",
    "accent", "accent_light", "accent_rgb",
    "secondary", "secondary_rgb",
    "border_rgb", "border_alpha", "divider_rgb", "divider_alpha",
    "badge_bg", "badge_fg",
    "success", "warning", "error",
)

THEMES: Dict[str, Dict] = {
    "halcyon": {
        "label": "Halcyon",
        "blurb": "Signature cyan on deep navy.",
        "bg": "#0a111e", "sidebar": "#080e18",
        "card": "#0f1828", "pill": "#111c30", "groove": "#1d2a3b",
        "text": "#f8fafc", "muted": "#8b94a3",
        "device_title": "#9aa3b2",
        "nav_active": "#a5f3fc", "nav_muted": "#9aa3b2",
        "accent": "#5fd5eb", "accent_light": "#a5f3fc",
        "accent_rgb": "95, 213, 235",
        "secondary": "#E8C468", "secondary_rgb": "232, 196, 104",
        "border_rgb": "165, 200, 255", "border_alpha": 0.22,
        "divider_rgb": "150, 185, 225", "divider_alpha": 0.32,
        "badge_bg": "#182437", "badge_fg": "#4aa8b8",
        "success": "#4ade80", "warning": "#facc15", "error": "#f87171",
    },
    "verdant": {
        "label": "Verdant",
        "blurb": "Emerald on forest black, with gold highlights.",
        "bg": "#0a1110", "sidebar": "#070d0c",
        "card": "#0f1918", "pill": "#14201f", "groove": "#1f302e",
        "text": "#eef3ec", "muted": "#8fa6a0",
        "device_title": "#9bb0aa",
        "nav_active": "#8ff0cc", "nav_muted": "#98aea8",
        "accent": "#35e0a8", "accent_light": "#8ff0cc",
        "accent_rgb": "53, 224, 168",
        "secondary": "#E9C46A", "secondary_rgb": "233, 196, 106",
        "border_rgb": "150, 215, 195", "border_alpha": 0.22,
        "divider_rgb": "140, 205, 185", "divider_alpha": 0.30,
        "badge_bg": "#10201d", "badge_fg": "#3fb890",
        "success": "#4ade80", "warning": "#facc15", "error": "#f87171",
    },
    "ember": {
        "label": "Ember",
        "blurb": "Warm amber on dark roast.",
        "bg": "#140f0a", "sidebar": "#100c08",
        "card": "#1a130c", "pill": "#1e1610", "groove": "#2e2318",
        "text": "#fff8f0", "muted": "#a39a8b",
        "device_title": "#ab9f8d",
        "nav_active": "#ffd9ab", "nav_muted": "#a39a8b",
        "accent": "#f5a524", "accent_light": "#ffd9ab",
        "accent_rgb": "245, 165, 36",
        "secondary": "#6FD0C0", "secondary_rgb": "111, 208, 192",
        "border_rgb": "255, 200, 150", "border_alpha": 0.22,
        "divider_rgb": "255, 195, 150", "divider_alpha": 0.32,
        "badge_bg": "#2a1f14", "badge_fg": "#f5a524",
        "success": "#4ade80", "warning": "#facc15", "error": "#f87171",
    },
    "vigil": {
        "label": "Vigil",
        "blurb": "Lavender and candle gold under a slow night sky.",
        "bg": "#0a0920", "sidebar": "#07061a",
        "card": "#141131", "pill": "#151236", "groove": "#2a2552",
        "text": "#f3efff", "muted": "#9a93b8",
        "device_title": "#a49dc2",
        "nav_active": "#e4dcff", "nav_muted": "#a49dc2",
        "accent": "#b9a6ff", "accent_light": "#e4dcff",
        "accent_rgb": "185, 166, 255",
        "secondary": "#E6CD8A", "secondary_rgb": "230, 205, 138",
        "border_rgb": "190, 170, 255", "border_alpha": 0.18,
        "divider_rgb": "190, 170, 255", "divider_alpha": 0.24,
        "badge_bg": "#1c1842", "badge_fg": "#b9a6ff",
        "success": "#7ee0b0", "warning": "#f5d77a", "error": "#f49aa6",
        # Beyond the colours: a night sky behind the dial instead of the
        # lattice, the dial breathing on a slow cycle, lighter headings
        # and softly lit surfaces (see STYLE_DEFAULTS and widgets/sky.py).
        "backdrop": "sky", "motion": "breath",
        "heading_weight": 600,
        "window_fill": ("qradialgradient(cx:0.62, cy:0.28, radius:0.95, "
                        "fx:0.62, fy:0.28, stop:0 #181440, stop:0.45 "
                        "#0e0c28, stop:0.75 #0a0920, stop:1 #0a0920)"),
        "card_fill": ("qlineargradient(x1:0, y1:0, x2:0, y2:1, "
                      "stop:0 #18143c, stop:1 #100e29)"),
    },
    "eclipse": {
        # Vigil in graphite: the same sky and breathing Home, its candle
        # gold a moon's deep blue and its lavender a soft silver. Deep
        # neutral greys, soft text and faint edges, nothing pure white.
        # (Was Mono.)
        "label": "Eclipse",
        "blurb": "Silver and deep blue on graphite under a slow night sky.",
        "bg": "#0a0a0a", "sidebar": "#070707",
        "card": "#111111", "pill": "#141414", "groove": "#282828",
        "text": "#e6e6e6", "muted": "#a3a3a3",
        "device_title": "#adadad",
        "nav_active": "#ececec", "nav_muted": "#adadad",
        "accent": "#c8c8c8", "accent_light": "#ececec",
        "accent_rgb": "200, 200, 200",
        "secondary": "#4A83C9", "secondary_rgb": "74, 131, 201",
        "border_rgb": "220, 220, 220", "border_alpha": 0.14,
        "divider_rgb": "220, 220, 220", "divider_alpha": 0.20,
        "badge_bg": "#191919", "badge_fg": "#c8c8c8",
        "success": "#86d0ae", "warning": "#e2c983", "error": "#e89aa2",
        "backdrop": "sky", "motion": "breath",
        "heading_weight": 600,
        "window_fill": ("qradialgradient(cx:0.62, cy:0.28, radius:0.95, "
                        "fx:0.62, fy:0.28, stop:0 #151515, stop:0.45 "
                        "#0e0e0e, stop:0.75 #0a0a0a, stop:1 #0a0a0a)"),
        "card_fill": ("qlineargradient(x1:0, y1:0, x2:0, y2:1, "
                      "stop:0 #141414, stop:1 #0e0e0e)"),
    },
    "orchid": {
        "label": "Orchid",
        "blurb": "Hot pink on dark plum, with a sky-blue accent.",
        "bg": "#150d14", "sidebar": "#110a10",
        "card": "#1b1119", "pill": "#20141d", "groove": "#30202b",
        "text": "#fdf2f8", "muted": "#a8939f",
        "device_title": "#b59fac",
        "nav_active": "#fbb6d9", "nav_muted": "#a8939f",
        "accent": "#f472b6", "accent_light": "#fbb6d9",
        "accent_rgb": "244, 114, 182",
        "secondary": "#86C5FF", "secondary_rgb": "134, 197, 255",
        "border_rgb": "255, 170, 215", "border_alpha": 0.22,
        "divider_rgb": "255, 165, 210", "divider_alpha": 0.32,
        "badge_bg": "#2a1623", "badge_fg": "#f472b6",
        "success": "#4ade80", "warning": "#facc15", "error": "#f87171",
    },
}

DEFAULT_THEME = "halcyon"

#: Retired theme ids and the theme that replaced each, so a saved choice
#: lands on its successor rather than the default.
RENAMED = {"ultraviolet": "vigil", "mono": "eclipse", "abyss": "halcyon"}

#: Optional per-theme keys and their values when a theme leaves them out.
#: backdrop: what the dial card shows behind the dial ("lattice" or
#: "sky"); motion: the Home rhythm ("tactile", or "breath": slower, on a
#: breathing cycle); heading_weight: the heading font weight; window_fill
#: and card_fill: QSS backgrounds (None: the flat bg / card colour).
STYLE_DEFAULTS = {
    "backdrop": "lattice",
    "motion": "tactile",
    "heading_weight": 700,
    "window_fill": None,
    "card_fill": None,
}

# "secondary" is the second brand colour: idle dial ring, icon chips,
# focus markers and picker chevrons. Accent means "live"; secondary means
# "available / waiting". Chosen per theme as a soft complement of its accent.

# Accent wash alpha for hover/pressed states (shared by all themes).
ACCENT_WASH_ALPHA = 0.12

_current_id = DEFAULT_THEME


def resolve_id(theme_id) -> str:
    """A known theme id for `theme_id`: itself, its successor if it was
    retired, else the default."""
    theme_id = RENAMED.get(theme_id, theme_id)
    return theme_id if theme_id in THEMES else DEFAULT_THEME


def set_current(theme_id: str) -> str:
    """Select the active theme (falls back to default). Returns the id used."""
    global _current_id
    _current_id = resolve_id(theme_id)
    return _current_id


def current_id() -> str:
    """Active theme id."""
    return _current_id


def current() -> Dict:
    """Active palette."""
    return get_theme(_current_id)


def theme_ids() -> List[str]:
    """Theme ids in display order."""
    return list(THEMES)


def get_theme(theme_id: str) -> Dict:
    """Palette for an id, falling back to the default theme."""
    return THEMES.get(theme_id, THEMES[DEFAULT_THEME])


def style(key: str, theme_id: str = None):
    """An optional STYLE_DEFAULTS key of a theme (default: the current
    one), falling back to its default."""
    palette = get_theme(_current_id if theme_id is None else theme_id)
    return palette.get(key, STYLE_DEFAULTS[key])


def breathing(theme_id: str = None) -> bool:
    """True when the theme's Home moves on the slow breathing cycle."""
    return style("motion", theme_id) == "breath"


def theme_label(theme_id: str) -> str:
    """Display label for a theme id."""
    return get_theme(theme_id)["label"]


def theme_blurb(theme_id: str) -> str:
    """One-line description for a theme id."""
    return get_theme(theme_id)["blurb"]
