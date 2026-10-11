"""
Poise Voice Isolator - Color Themes

Named, self-matching palettes for the GUI. Every theme carries the full
token set consumed by styles.get_stylesheet() and the painted widgets,
so switching themes can never leave a stray color behind.

Themes ship with the app; the selection persists in Settings ("abyss"
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
    "abyss": {
        "label": "Abyss",
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
    "mono": {
        "label": "Mono",
        "blurb": "Neutral grayscale, distraction-free.",
        "bg": "#101012", "sidebar": "#0c0c0e",
        "card": "#151517", "pill": "#1a1a1e", "groove": "#2e2e34",
        "text": "#f5f5f5", "muted": "#a7a7ae",
        "device_title": "#b5b5bc",
        "nav_active": "#e4e4e7", "nav_muted": "#a3a3a9",
        "accent": "#c9d1db", "accent_light": "#eceff3",
        "accent_rgb": "201, 209, 219",
        "secondary": "#B9B3A8", "secondary_rgb": "185, 179, 168",
        "border_rgb": "255, 255, 255", "border_alpha": 0.30,
        "divider_rgb": "255, 255, 255", "divider_alpha": 0.42,
        "badge_bg": "#232329", "badge_fg": "#c9d1db",
        "success": "#4ade80", "warning": "#facc15", "error": "#f87171",
    },
    "ultraviolet": {
        "label": "Ultraviolet",
        "blurb": "Violet glow on near-black purple.",
        "bg": "#0f0d1d", "sidebar": "#0c0a17",
        "card": "#151226", "pill": "#191530", "groove": "#251f3d",
        "text": "#f5f3ff", "muted": "#8f8aa3",
        "device_title": "#9c94b5",
        "nav_active": "#d6c9ff", "nav_muted": "#8f8aa3",
        "accent": "#a78bfa", "accent_light": "#d6c9ff",
        "accent_rgb": "167, 139, 250",
        "secondary": "#F3A0C0", "secondary_rgb": "243, 160, 192",
        "border_rgb": "190, 170, 255", "border_alpha": 0.24,
        "divider_rgb": "180, 160, 255", "divider_alpha": 0.34,
        "badge_bg": "#1e1836", "badge_fg": "#a78bfa",
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

DEFAULT_THEME = "abyss"

# "secondary" is the second brand colour: idle dial ring, icon chips,
# focus markers and picker chevrons. Accent means "live"; secondary means
# "available / waiting". Chosen per theme as a soft complement of its accent.

# Accent wash alpha for hover/pressed states (shared by all themes).
ACCENT_WASH_ALPHA = 0.12

_current_id = DEFAULT_THEME


def set_current(theme_id: str) -> str:
    """Select the active theme (falls back to default). Returns the id used."""
    global _current_id
    _current_id = theme_id if theme_id in THEMES else DEFAULT_THEME
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


def theme_label(theme_id: str) -> str:
    """Display label for a theme id."""
    return get_theme(theme_id)["label"]


def theme_blurb(theme_id: str) -> str:
    """One-line description for a theme id."""
    return get_theme(theme_id)["blurb"]
