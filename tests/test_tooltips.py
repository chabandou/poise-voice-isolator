"""Tooltip stylesheet asserts (no Qt required)."""
import importlib.util
import os
import sys
import types

_GUI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "stream_denoiser", "gui")

_pkg = types.ModuleType("poise_gui_tips")
_pkg.__path__ = [_GUI_DIR]
sys.modules["poise_gui_tips"] = _pkg


def _load(name):
    fullname = f"poise_gui_tips.{name}"
    if fullname in sys.modules:
        return sys.modules[fullname]
    spec = importlib.util.spec_from_file_location(
        fullname, os.path.join(_GUI_DIR, f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[fullname] = module
    spec.loader.exec_module(module)
    return module


styles = _load("styles")
themes = _load("themes")


def test_native_and_managed_tips_share_one_rule():
    css = styles.get_stylesheet(scale=1.0, theme="abyss")
    assert "QLabel#poise-tip" in css
    assert "QToolTip" in css


def test_tips_are_themed_not_hardcoded():
    """No slate hexes left; every theme renders tip colors from tokens."""
    for theme_id in themes.theme_ids():
        css = styles.get_stylesheet(scale=1.0, theme=theme_id)
        for hard in ("#1e293b", "#334155"):
            assert hard not in css, (theme_id, hard)
        pal = themes.get_theme(theme_id)
        assert pal["sidebar"] in css
        assert pal["text"] in css


def test_tip_type_is_readable():
    import re
    css = styles.get_stylesheet(scale=1.0, theme="abyss")
    m = re.search(r"poise-tip\s*\{([^}]*)\}", css)
    assert m, "tip rule missing"
    body = m.group(1)
    assert "font-size: 14px" in body
    assert "border-radius: 8px" in body
