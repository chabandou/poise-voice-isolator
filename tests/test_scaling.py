"""Tests for GUI scaling helpers (no Qt required).

scaling.py / styles.py are loaded straight from their file paths because
importing anything under stream_denoiser.gui would execute the package
__init__, which requires PyQt6.
"""
import importlib.util
import os
import sys
import types

import pytest

_GUI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "stream_denoiser", "gui")

# Fake a parent package so the modules' relative imports resolve.
_pkg = types.ModuleType("poise_gui_test")
_pkg.__path__ = [_GUI_DIR]
sys.modules["poise_gui_test"] = _pkg


def _load(name):
    fullname = f"poise_gui_test.{name}"
    if fullname in sys.modules:
        return sys.modules[fullname]
    spec = importlib.util.spec_from_file_location(
        fullname, os.path.join(_GUI_DIR, f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[fullname] = module
    spec.loader.exec_module(module)
    return module


scaling = _load("scaling")
styles = _load("styles")

MAX_SCALE = scaling.MAX_SCALE
MIN_SCALE = scaling.MIN_SCALE
scale_stylesheet = scaling.scale_stylesheet
set_scale_factor = scaling.set_scale_factor
sp = scaling.sp
ui_scale = scaling.ui_scale
POISE_STYLESHEET = styles.POISE_STYLESHEET
get_stylesheet = styles.get_stylesheet


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    monkeypatch.delenv("POISE_UI_SCALE", raising=False)
    old = scaling._scale_factor
    scaling._scale_factor = None
    yield
    scaling._scale_factor = old


def test_scale_factor_clamped():
    assert set_scale_factor(0.1) == MIN_SCALE
    assert set_scale_factor(99.0) == MAX_SCALE
    assert set_scale_factor(1.25) == 1.25


def test_sp_math():
    set_scale_factor(1.5)
    assert sp(100) == 150
    assert sp(14) == 21
    assert sp(1) >= 1


def test_sp_defaults_to_one_without_qapp():
    # No QApplication here and no env override -> factor 1.0.
    assert ui_scale() == 1.0
    assert sp(216) == 216


def test_env_override(monkeypatch):
    monkeypatch.setenv("POISE_UI_SCALE", "1.5")
    assert ui_scale() == 1.5
    assert sp(100) == 150


def test_env_override_invalid_falls_back(monkeypatch):
    monkeypatch.setenv("POISE_UI_SCALE", "not-a-number")
    assert ui_scale() == 1.0


def test_stylesheet_scales_pixels():
    set_scale_factor(1.5)
    css = get_stylesheet()
    assert "{ASSETS_DIR}" not in css
    assert "chevron-down.svg" in css
    assert "font-size: 21px" in css  # 14px * 1.5


def test_stylesheet_unscaled_at_default():
    css = get_stylesheet(scale=1.0)
    assert "font-size: 14px" in css
    assert "{ASSETS_DIR}" not in css
    assert "chevron-down.svg" in css


def test_card_border_width_steps_with_scale():
    assert styles._card_border_width(1.0) == 1
    assert styles._card_border_width(1.24) == 1
    assert styles._card_border_width(1.49) == 2
    assert styles._card_border_width(2.0) == 3
    css = get_stylesheet(scale=1.49)
    assert "{CARD_BORDER_WIDTH}" not in css
    assert "border: 2px solid rgba(165, 200, 255, 0.22)" in css


def test_scale_stylesheet_leaves_non_px_alone():
    out = scale_stylesheet("a { opacity: 0.5; x: 10; y: 8px; }", 2.0)
    assert "opacity: 0.5" in out
    assert "y: 16px" in out


def test_pick_scale_dense_panel_no_os_scaling():
    # 14" 1080p laptop (144 DPI), compositor at 100%: scale up.
    assert scaling._pick_scale(96.0, 143.9, 1.0) == pytest.approx(1.499, abs=0.01)


def test_pick_scale_standard_display():
    assert scaling._pick_scale(96.0, 92.0, 1.0) == 1.0


def test_pick_scale_trusts_os_scaling():
    # 4K laptop at 200% OS scaling: Qt already scales, stay at 1.0.
    assert scaling._pick_scale(192.0, 282.0, 2.0) == 1.0
    # Windows 150% text scaling.
    assert scaling._pick_scale(144.0, 92.0, 1.5) == 1.0


def test_pick_scale_honors_logical_dpi():
    # Desktop GNOME text-scaling (logical inflated, DPR untouched).
    assert scaling._pick_scale(144.0, 96.0, 1.0) == 1.5


def test_pick_scale_ignores_bogus_dpi():
    assert scaling._pick_scale(0.0, -1.0, 1.0) == 1.0


def test_isp_applies_icon_boost():
    set_scale_factor(1.5)
    assert scaling.isp(20) == 38  # 20 * 1.5 * 1.25 rounded


def test_icon_boost_env_override(monkeypatch):
    set_scale_factor(1.0)
    monkeypatch.setenv("POISE_ICON_SCALE", "1.5")
    assert scaling.isp(20) == 30
