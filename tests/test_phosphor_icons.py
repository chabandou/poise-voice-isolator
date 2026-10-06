"""Tests for the vendored Phosphor icon assets (no Qt required).

The loader itself (widgets/phosphor.py) needs Qt and is exercised through
the running GUI; here we guard the vendored files: every logical name the
app uses must resolve to a valid SVG, and the MIT license must ship.
"""
import os
import xml.etree.ElementTree as ET

ICONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "..", "stream_denoiser", "gui", "assets", "icons")

# Logical names used across the GUI -> Phosphor file stems.
# Must mirror FILES in stream_denoiser/gui/widgets/phosphor.py.
EXPECTED = {
    "waveform": "waveform",
    "gear": "gear",
    "doc": "file-text",
    "info": "info",
    "monitor": "monitor",
    "speaker": "speaker-high",
    "percent": "percent",
    "clock": "clock",
    "pulse": "pulse",
    "buffer": "stack",
    "refresh": "arrow-clockwise",
    "folder": "folder",
    "palette": "palette",
    "cpu": "cpu",
    "sliders": "sliders-horizontal",
}


def test_all_expected_svgs_present():
    for logical, stem in EXPECTED.items():
        path = os.path.join(ICONS_DIR, stem + ".svg")
        assert os.path.isfile(path), f"missing SVG for {logical!r}: {path}"


def test_svgs_are_valid():
    for stem in EXPECTED.values():
        path = os.path.join(ICONS_DIR, stem + ".svg")
        root = ET.parse(path).getroot()
        assert root.tag.endswith("svg"), f"{path} has no svg root"
        assert root.get("viewBox"), f"{path} has no viewBox"
        assert len(list(root)) > 0, f"{path} has no drawable elements"


def test_license_ships():
    path = os.path.join(ICONS_DIR, "LICENSE")
    assert os.path.isfile(path)
    with open(path) as f:
        text = f.read()
    assert "MIT License" in text
    assert "Phosphor" in text
