"""Tests for GUI color themes (no Qt required, same loader as test_scaling)."""
import importlib.util
import os
import re
import sys
import types

import pytest

_GUI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "stream_denoiser", "gui")

_pkg = types.ModuleType("poise_gui_themes")
_pkg.__path__ = [_GUI_DIR]
sys.modules["poise_gui_themes"] = _pkg


def _load(name):
    fullname = f"poise_gui_themes.{name}"
    if fullname in sys.modules:
        return sys.modules[fullname]
    spec = importlib.util.spec_from_file_location(
        fullname, os.path.join(_GUI_DIR, f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[fullname] = module
    spec.loader.exec_module(module)
    return module


themes = _load("themes")
styles = _load("styles")

HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
RGB_TRIPLET = re.compile(r"^\d{1,3}, \d{1,3}, \d{1,3}$")
LEFTOVER_TOKEN = re.compile(r"\{[A-Z_]+\}")


def test_registry_complete_and_valid():
    assert set(themes.theme_ids()) == set(themes.THEMES)
    assert themes.DEFAULT_THEME in themes.THEMES
    for theme_id in themes.theme_ids():
        palette = themes.get_theme(theme_id)
        assert set(palette) >= set(themes.KEYS), theme_id
        assert themes.theme_label(theme_id)
        assert themes.theme_blurb(theme_id)
        for key in themes.KEYS:
            value = palette[key]
            if key.endswith("_rgb"):
                assert RGB_TRIPLET.match(value), (theme_id, key, value)
                assert all(0 <= int(c) <= 255 for c in value.split(", ")), key
            elif key in ("label", "blurb"):
                assert isinstance(value, str) and value
            elif key.endswith("_alpha"):
                assert isinstance(value, float) and 0.0 < value < 1.0, key
            else:
                assert HEX_COLOR.match(value), (theme_id, key, value)


def test_unknown_theme_falls_back():
    assert themes.get_theme("nope") is themes.get_theme(themes.DEFAULT_THEME)
    assert themes.set_current("nope") == themes.DEFAULT_THEME
    assert themes.current_id() == themes.DEFAULT_THEME


def test_set_current_roundtrip():
    assert themes.set_current("mono") == "mono"
    assert themes.current_id() == "mono"
    assert themes.current()["label"] == "Mono"
    themes.set_current(themes.DEFAULT_THEME)


def test_stylesheet_renders_every_theme_cleanly():
    for theme_id in themes.theme_ids():
        css = styles.get_stylesheet(scale=1.0, theme=theme_id)
        assert not LEFTOVER_TOKEN.search(css), theme_id
        assert "{ASSETS_DIR}" not in css
        assert "chevron-down.svg" in css


def test_abyss_preserves_current_look():
    css = styles.get_stylesheet(scale=1.0, theme="abyss")
    assert "background-color: #0a111e" in css  # page bg unchanged
    assert "95, 213, 235" in css  # abyss accent rgb


def test_mono_is_cyan_free():
    css = styles.get_stylesheet(scale=1.0, theme="mono")
    for cyan in ("#5fd5eb", "#22d3ee", "95, 213, 235", "34, 211, 238"):
        assert cyan not in css
    assert "201, 209, 219" in css  # mono accent rgb


def _rgb(hex_color):
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def _luminance(hex_color):
    def lin(c):
        c /= 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in _rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b):
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_secondary_matches_its_rgb_and_stays_legible():
    for theme_id in themes.theme_ids():
        p = themes.get_theme(theme_id)
        assert ", ".join(str(c) for c in _rgb(p["secondary"])) \
            == p["secondary_rgb"], theme_id
        # Chips, ring and markers must read against the card surface.
        assert _contrast(p["secondary"], p["card"]) >= 4.5, theme_id


def test_secondary_is_a_distinct_second_colour():
    for theme_id in themes.theme_ids():
        p = themes.get_theme(theme_id)
        a, s = _rgb(p["accent"]), _rgb(p["secondary"])
        distance = sum((x - y) ** 2 for x, y in zip(a, s)) ** 0.5
        assert distance >= 45, (theme_id, distance)


def test_secondary_reaches_the_stylesheet():
    css = styles.get_stylesheet(scale=1.0, theme="abyss")
    assert "#E8C468" in css                      # model-card checked border
    assert "232, 196, 104" in css                # chip wash


def test_verdant_is_registered_with_gold_secondary():
    assert "verdant" in themes.theme_ids()
    p = themes.get_theme("verdant")
    assert p["label"] == "Verdant"
    assert p["accent"].lower() == "#35e0a8"
    assert p["secondary"].lower() == "#e9c46a"
    assert themes.DEFAULT_THEME == "abyss"      # default is unchanged
    css = styles.get_stylesheet(scale=1.0, theme="verdant")
    assert not LEFTOVER_TOKEN.search(css)
    assert "53, 224, 168" in css


def test_six_themes_fill_a_three_by_two_grid():
    ids = themes.theme_ids()
    assert len(ids) == 6 and ids[0] == themes.DEFAULT_THEME
    assert ids[-1] == "orchid"
    p = themes.get_theme("orchid")
    assert p["label"] == "Orchid"
    css = styles.get_stylesheet(scale=1.0, theme="orchid")
    assert not LEFTOVER_TOKEN.search(css)
    assert "244, 114, 182" in css          # accent wash


def test_ghost_buttons_hover_like_the_dropdown():
    """One hover colour for fields and ghost buttons: the secondary.
    (The dropdown's ring is painted in that colour: test_combo.py.)"""
    import re
    css = styles.get_stylesheet(scale=1.0, theme="abyss")
    ghost = re.search(r"QPushButton#ghost:hover\s*\{([^}]*)\}", css)
    assert ghost
    assert "#E8C468" in ghost.group(1)
