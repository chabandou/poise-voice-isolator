"""
TUI colors: a named theme plus the user's own overrides.

Every color has a role (ROLES). A theme (THEMES) sets some of them over
the defaults; the user's "colors" in tui.json set any of them over the
theme. apply() makes a choice current: the module's names (ACCENT, ...)
change, which the widgets read each time they draw, and
css_variables() gives the stylesheet the same colors ($poise-accent,
...). After a change at run time the app refreshes its CSS and redraws.
"""
from typing import Dict, List, Optional

from textual.color import Color, ColorParseError

# Role -> default (the "abyss" theme, the design's colors).
ROLES: Dict[str, str] = {
    "accent": "#5fd5eb",       # keys, focus, voice
    "accent_dim": "#4a9fb3",   # second meter
    "voice_light": "#a5f3fc",  # the loudest voice in the scope
    "highlight": "#e8c468",    # the value being changed, the device in use
    "text": "#f8fafc",
    "soft": "#c3cad5",
    "muted": "#8b94a3",        # labels
    "dim": "#5d6878",          # hints, timestamps
    "border": "#2a3a52",       # box borders
    "groove": "#1d2a3b",       # empty meter cells, dividers
    "selection": "#111c30",    # the selected row
    "scope_in": "#56616f",     # the input in the scope
    "surface": "#0f1828",      # the model picker
    "on_accent": "#080e18",    # text on the accent
    "scrim": "#050910",        # dims the screen behind the picker
    "ok": "#4ade80",
    "warn": "#facc15",
    "error": "#f87171",
}

# Theme -> the roles it changes. The names follow the design's Settings.
THEMES: Dict[str, Dict[str, str]] = {
    "abyss": {},
    "verdant": {"accent": "#35e0a8", "accent_dim": "#2a9f7c",
                "voice_light": "#a7f3d0"},
    "mono": {"accent": "#c9d1db", "accent_dim": "#8b94a3",
             "voice_light": "#f1f5f9", "highlight": "#f8fafc"},
    "ultraviolet": {"accent": "#a78bfa", "accent_dim": "#7c6bc4",
                    "voice_light": "#ddd6fe"},
    "ember": {"accent": "#f5a524", "accent_dim": "#b97a1f",
              "voice_light": "#fde68a", "highlight": "#7dd3fc"},
    "orchid": {"accent": "#f472b6", "accent_dim": "#b8558a",
               "voice_light": "#fbcfe8"},
}
DEFAULT_THEME = "abyss"

# The current colors (apply() sets them).
theme = DEFAULT_THEME
colors: Dict[str, str] = dict(ROLES)
ACCENT = ACCENT_DIM = LIGHT = GOLD = INK = SOFT = MUTED = DIM = ""
EDGE = GROOVE = PILL = GREEN = YELLOW = RED = ""


def _hex(color: Color) -> str:
    return color.hex6


def apply(theme_name: Optional[str] = None,
          overrides: Optional[dict] = None) -> List[str]:
    """Make ``theme_name`` (unknown: the default) with ``overrides``
    (role -> color) current. Returns one message per value left out."""
    global theme, colors
    global ACCENT, ACCENT_DIM, LIGHT, GOLD, INK, SOFT, MUTED, DIM
    global EDGE, GROOVE, PILL, GREEN, YELLOW, RED
    problems = []
    if theme_name and theme_name not in THEMES:
        problems.append(f"theme '{theme_name}' unknown; "
                        f"one of {', '.join(THEMES)}")
        theme_name = None
    theme = theme_name or DEFAULT_THEME
    chosen = {role: _hex(Color.parse(value))
              for role, value in {**ROLES, **THEMES[theme]}.items()}
    given = set()
    for role, value in (overrides or {}).items():
        if role not in ROLES:
            problems.append(f"colors: '{role}' is not a color role")
            continue
        try:
            chosen[role] = _hex(Color.parse(str(value)))
            given.add(role)
        except ColorParseError:
            problems.append(f"colors.{role}: '{value}' is not a color")
    # A new accent alone: its shades follow it.
    if "accent" in given:
        accent = Color.parse(chosen["accent"])
        if "accent_dim" not in given:
            chosen["accent_dim"] = _hex(accent.darken(0.15))
        if "voice_light" not in given:
            chosen["voice_light"] = _hex(accent.lighten(0.2))
    colors = chosen
    ACCENT, ACCENT_DIM, LIGHT = (chosen["accent"], chosen["accent_dim"],
                                 chosen["voice_light"])
    GOLD, INK, SOFT = chosen["highlight"], chosen["text"], chosen["soft"]
    MUTED, DIM, EDGE = chosen["muted"], chosen["dim"], chosen["border"]
    GROOVE, PILL = chosen["groove"], chosen["selection"]
    GREEN, YELLOW, RED = chosen["ok"], chosen["warn"], chosen["error"]
    return problems


def css_variables() -> Dict[str, str]:
    """$poise-<role> for the stylesheet (underscores become dashes)."""
    return {f"poise-{role.replace('_', '-')}": value
            for role, value in colors.items()}


def next_theme() -> str:
    names = list(THEMES)
    return names[(names.index(theme) + 1) % len(names)]


def _ramp(start: str, end: str, steps: int) -> List[str]:
    a, b = Color.parse(start), Color.parse(end)
    return [_hex(a.blend(b, i / (steps - 1))) for i in range(steps)]


def scope_input_rows(rows: int) -> List[str]:
    """Top to bottom: the input fades toward the border color."""
    return _ramp(colors["scope_in"],
                 _hex(Color.parse(colors["scope_in"]).blend(
                     Color.parse(colors["border"]), 0.6)), rows)


def scope_voice_rows(rows: int) -> List[str]:
    """Top to bottom: the voice brightens toward its light shade."""
    dark = _hex(Color.parse(colors["accent"]).darken(0.2))
    return _ramp(dark, colors["accent"], rows - 1) + [colors["voice_light"]]


def meter(fraction: float, width: int, color: str) -> str:
    """A row of ■ cells, ``fraction`` of them lit (markup)."""
    fraction = max(0.0, min(1.0, fraction))
    lit = int(round(fraction * width))
    return (f"[{color}]{'■' * lit}[/][{GROOVE}]{'■' * (width - lit)}[/]"
            if width > 0 else "")


apply()
