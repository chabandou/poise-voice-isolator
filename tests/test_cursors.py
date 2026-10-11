"""Tests for OS cursor theme bootstrap (no Qt required)."""
import importlib.util
import os
import sys
import types
from unittest import mock

import pytest

_GUI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "stream_denoiser", "gui")

_pkg = types.ModuleType("poise_gui_cursors")
_pkg.__path__ = [_GUI_DIR]
sys.modules["poise_gui_cursors"] = _pkg


def _load():
    fullname = "poise_gui_cursors.cursors"
    if fullname in sys.modules:
        return sys.modules[fullname]
    spec = importlib.util.spec_from_file_location(
        fullname, os.path.join(_GUI_DIR, "cursors.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[fullname] = module
    spec.loader.exec_module(module)
    return module


cursors = _load()


def _env(**kwargs):
    base = {"XCURSOR_THEME": "", "XCURSOR_SIZE": ""}
    base.update(kwargs)
    return base


def test_respects_explicit_user_env():
    env = _env(XCURSOR_THEME="Bibata-Modern-Ice", XCURSOR_SIZE="32")
    with mock.patch.object(cursors, "_gsettings_theme", return_value="Adwaita"), \
         mock.patch.object(cursors, "_theme_installed", return_value=True):
        assert cursors.cursor_env_fixes(env) == {}


def test_prefers_desktop_theme_when_installed(tmp_path):
    env = _env()
    with mock.patch.object(cursors, "_gsettings_theme", return_value="Bibata"), \
         mock.patch.object(cursors, "_theme_installed",
                           side_effect=lambda name: name == "Bibata"):
        fixes = cursors.cursor_env_fixes(env)
    assert fixes["XCURSOR_THEME"] == "Bibata"
    assert fixes["XCURSOR_SIZE"] == "24"


def test_ignores_desktop_default_and_falls_back(tmp_path):
    env = _env()
    with mock.patch.object(cursors, "_gsettings_theme", return_value="default"), \
         mock.patch.object(cursors, "_theme_installed",
                           side_effect=lambda name: name == "Adwaita"):
        fixes = cursors.cursor_env_fixes(env)
    assert fixes["XCURSOR_THEME"] == "Adwaita"


def test_falls_back_to_adwaita(tmp_path):
    env = _env()
    with mock.patch.object(cursors, "_gsettings_theme", return_value=None), \
         mock.patch.object(cursors, "_theme_installed",
                           side_effect=lambda name: name == "Adwaita"):
        assert cursors.cursor_env_fixes(env)["XCURSOR_THEME"] == "Adwaita"


def test_no_theme_found_sets_size_only():
    env = _env()
    with mock.patch.object(cursors, "_gsettings_theme", return_value=None), \
         mock.patch.object(cursors, "_theme_installed", return_value=False):
        assert cursors.cursor_env_fixes(env) == {"XCURSOR_SIZE": "24"}


def test_theme_installed_checks_cursors_dir(tmp_path):
    good = tmp_path / ".icons" / "Mine" / "cursors"
    good.mkdir(parents=True)
    (good / "arrow").write_bytes(b"x")
    (tmp_path / ".icons" / "Empty" / "cursors").mkdir(parents=True)
    assert cursors._theme_installed("Mine", home=str(tmp_path)) is True
    assert cursors._theme_installed("Empty", home=str(tmp_path)) is False
    assert cursors._theme_installed("Missing", home=str(tmp_path)) is False
    assert cursors._theme_installed("../evil", home=str(tmp_path)) is False


def test_ensure_applies_without_clobbering(monkeypatch):
    monkeypatch.delenv("XCURSOR_THEME", raising=False)
    monkeypatch.delenv("XCURSOR_SIZE", raising=False)
    with mock.patch.object(cursors, "_gsettings_theme", return_value=None), \
         mock.patch.object(cursors, "_theme_installed", return_value=False):
        applied = cursors.ensure_cursor_env()
    assert applied == {"XCURSOR_SIZE": "24"}
    assert os.environ["XCURSOR_SIZE"] == "24"
    assert "XCURSOR_THEME" not in os.environ


def test_prefer_named_cursor_only_on_wayland():
    assert cursors.prefer_named_cursor("wayland") is True
    assert cursors.prefer_named_cursor("Wayland") is True
    assert cursors.prefer_named_cursor("xcb") is False
    assert cursors.prefer_named_cursor("windows") is False
    assert cursors.prefer_named_cursor("cocoa") is False
    assert cursors.prefer_named_cursor("offscreen") is False
    assert cursors.prefer_named_cursor("") is False
    assert cursors.prefer_named_cursor(None) is False


# -- XCursor parsing ------------------------------------------------------------
import struct as _struct


def _xcursor_file(sizes):
    """Build a minimal multi-size XCursor binary (pure white pixels)."""
    chunks = b""
    toc = b""
    pos = 16 + 12 * len(sizes)
    for nominal, (w, h) in sizes:
        px = b"\xff\xff\xff\xff" * (w * h)
        chunk = _struct.pack("<9I", 36, 0xFFFD0002, nominal, 1,
                             w, h, 1, 1, 0) + px
        toc += _struct.pack("<3I", 0xFFFD0002, nominal, pos)
        pos += len(chunk)
        chunks += chunk
    return _struct.pack("<4I", 0x72756358, 16, 1, len(sizes)) + toc + chunks


def test_parse_rejects_garbage():
    assert cursors.parse_xcursor(b"", 24) is None
    assert cursors.parse_xcursor(b"not a cursor", 24) is None
    assert cursors.parse_xcursor(b"\x00" * 64, 24) is None


def test_parse_picks_exact_size_then_next_up():
    data = _xcursor_file([(24, (24, 24)), (48, (48, 48))])
    assert cursors.parse_xcursor(data, 24)[:2] == (24, 24)
    assert cursors.parse_xcursor(data, 30)[:2] == (48, 48)
    assert cursors.parse_xcursor(data, 96)[:2] == (48, 48)
    w, h, xhot, yhot, px = cursors.parse_xcursor(data, 24)
    assert (xhot, yhot) == (1, 1) and len(px) == 24 * 24 * 4


def test_parse_real_adwaita_pointer():
    path = "/usr/share/icons/Adwaita/cursors/pointer"
    if not os.path.isfile(path):
        pytest.skip("Adwaita cursor theme not installed")
    with open(path, "rb") as f:
        parsed = cursors.parse_xcursor(f.read(), 24)
    assert parsed is not None
    w, h, xhot, yhot, px = parsed
    assert (w, h) == (24, 24) and len(px) == w * h * 4
    assert 0 <= xhot < w and 0 <= yhot < h


def test_find_theme_cursor_prefers_hand2_symlink():
    if not os.path.isfile("/usr/share/icons/Adwaita/cursors/pointer"):
        pytest.skip("Adwaita cursor theme not installed")
    env = {"XCURSOR_THEME": "Adwaita", "XCURSOR_SIZE": "24"}
    with mock.patch.object(cursors, "_theme_installed", return_value=True):
        found = cursors.find_theme_cursor(env=env)
    assert found is not None
    theme, w, h, xhot, yhot, px = found
    assert theme == "Adwaita" and (w, h) == (24, 24)


