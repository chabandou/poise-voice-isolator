"""Tests for the themed app-icon variants (no Qt required)."""
import importlib.util
import os
import xml.etree.ElementTree as ET

_GUI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "stream_denoiser", "gui")
_ASSETS_DIR = os.path.join(_GUI_DIR, "assets")

GRAY_TIP = "#D1D6DD"


def _load_utils():
    spec = importlib.util.spec_from_file_location(
        "gui_utils_standalone", os.path.join(_GUI_DIR, "utils.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stops(name):
    root = ET.parse(os.path.join(_ASSETS_DIR, name)).getroot()
    assert root.tag.endswith("svg"), name
    stops = [el.get("stop-color") for el in root.iter()
             if el.tag.endswith("stop")]
    assert len(stops) == 3, (name, stops)
    return stops


def test_signature_icon_keeps_cyan_and_gray_tip():
    assert _stops("icon.svg") == ["#22D3EE", "#22D3EE", GRAY_TIP]


def test_themed_variants_recolor_accent_only():
    assert _stops("icon-ultraviolet.svg") == ["#a78bfa", "#a78bfa", GRAY_TIP]
    assert _stops("icon-ember.svg") == ["#f5a524", "#f5a524", GRAY_TIP]


def test_variant_mapping_matches_files():
    utils = _load_utils()
    for theme_id, filename in utils.THEME_ICON_VARIANTS.items():
        assert os.path.isfile(os.path.join(_ASSETS_DIR, filename)), theme_id
    # Mono and Abyss intentionally keep the signature cyan icon.
    assert "mono" not in utils.THEME_ICON_VARIANTS
    assert "abyss" not in utils.THEME_ICON_VARIANTS
