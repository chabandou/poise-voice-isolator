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
