"""Dropdown popup stylesheet asserts (no Qt required)."""
import importlib.util
import os
import re
import sys
import types

_GUI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "stream_denoiser", "gui")

_pkg = types.ModuleType("poise_gui_dd")
_pkg.__path__ = [_GUI_DIR]
sys.modules["poise_gui_dd"] = _pkg


def _load(name):
    fullname = f"poise_gui_dd.{name}"
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


def _css(theme_id="abyss"):
    return styles.get_stylesheet(scale=1.0, theme=theme_id)


def _block_after(css, marker):
    i = css.find(marker)
    assert i >= 0, marker
    j = css.find("{", i)
    k = css.find("}", j)
    assert j >= 0 and k >= 0, marker
    return css[j:k]


def test_popup_view_block_intact():
    """Frame, font, and selection tokens survive for both combo styles."""
    css = _css()
    for combo in ("device-combo", "settings-combo"):
        assert f"QComboBox#{combo} QAbstractItemView" in css, combo
    body = _block_after(css, "QComboBox#settings-combo QAbstractItemView")
    assert "background-color" in body
    assert "border-radius" in body
    assert re.search(r"font-size:\s*1[5-9]px", body), "readable item text"


def test_no_dead_item_selectors():
    """::item subcontrols never reach combo popups (delegate paints rows).

    Guards against re-adding rules that silently do nothing.
    """
    css = _css()
    assert "QAbstractItemView::item" not in css


def test_focus_outline_and_open_state():
    """No default white focus frame; open state echoes hover accent."""
    css = _css()
    for combo in ("device-combo", "settings-combo"):
        focus = _block_after(css, f"QComboBox#{combo}:focus")
        assert "outline" in focus and "none" in focus, combo
        opened = _block_after(css, f"QComboBox#{combo}:on")
        assert "border" in opened, combo


def test_every_theme_renders_popup_cleanly():
    for theme_id in themes.theme_ids():
        css = styles.get_stylesheet(scale=1.0, theme=theme_id)
        assert "QAbstractItemView" in css, theme_id
