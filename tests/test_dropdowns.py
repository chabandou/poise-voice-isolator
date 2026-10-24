"""Dropdown popup stylesheet asserts (no Qt required)."""
import importlib.util
import os
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


def _css(theme_id="halcyon"):
    return styles.get_stylesheet(scale=1.0, theme=theme_id)


def _block_after(css, marker):
    i = css.find(marker)
    assert i >= 0, marker
    j = css.find("{", i)
    k = css.find("}", j)
    assert j >= 0 and k >= 0, marker
    return css[j:k]


def test_focus_outline_and_no_stylesheet_ring():
    """No default white focus frame. The gold ring is painted by
    AnimatedComboBox: a QSS :hover ring dropped out on every click (the
    popup holds the mouse, and hover only returns on the next move)."""
    css = _css()
    focus = _block_after(css, "QComboBox#device-combo:focus")
    assert "outline" in focus and "none" in focus
    assert "QComboBox#device-combo:hover" not in css
    assert 'QComboBox#device-combo[open="true"]' not in css


def test_chevron_is_painted_not_an_image():
    """AnimatedComboBox paints (and turns) the chevron itself."""
    for theme_id in themes.theme_ids():
        css = styles.get_stylesheet(scale=1.0, theme=theme_id)
        arrow = _block_after(css, "QComboBox#device-combo::down-arrow")
        assert "image: none" in arrow, theme_id
