"""Tests for vendored VB-Cable driver install helpers (no Qt, no drivers).

Covers pure logic only: exit-code mapping, bundled-setup discovery, and
the installed check. Nothing here touches real hardware or elevation —
install_vbcable_driver is only exercised with a bogus path (must fail
fast with RuntimeError on every platform).
"""
import sys

import pytest

from stream_denoiser.backends.platform.windows import (
    SETUP_EXIT_OK,
    SETUP_EXIT_REBOOT,
    VBCABLE_INSTALL_ARGS,
    find_bundled_vbcable_setup,
    install_vbcable_driver,
    interpret_setup_exit_code,
    is_vbcable_installed,
)


def test_install_args_are_silent():
    assert VBCABLE_INSTALL_ARGS == "-i -h"


def test_exit_code_mapping():
    assert interpret_setup_exit_code(SETUP_EXIT_OK) == "ok"
    assert interpret_setup_exit_code(0) == "ok"
    for code in SETUP_EXIT_REBOOT:
        assert interpret_setup_exit_code(code) == "reboot-required"
    assert interpret_setup_exit_code(3010) == "reboot-required"
    assert interpret_setup_exit_code(1641) == "reboot-required"
    assert interpret_setup_exit_code(1) == "failed"
    assert interpret_setup_exit_code(1223) == "failed"  # UAC cancelled


def test_find_prefers_x64(tmp_path):
    staged = tmp_path / "vbcable"
    staged.mkdir()
    (staged / "VBCABLE_Setup.exe").write_bytes(b"x86")
    (staged / "VBCABLE_Setup_x64.exe").write_bytes(b"x64")
    found = find_bundled_vbcable_setup(search_dirs=[tmp_path])
    assert found is not None and found.endswith("VBCABLE_Setup_x64.exe")


def test_find_falls_back_to_x86(tmp_path):
    staged = tmp_path / "vbcable"
    staged.mkdir()
    (staged / "VBCABLE_Setup.exe").write_bytes(b"x86")
    found = find_bundled_vbcable_setup(search_dirs=[tmp_path])
    assert found is not None and found.endswith("VBCABLE_Setup.exe")


def test_find_returns_none_when_missing(tmp_path):
    assert find_bundled_vbcable_setup(search_dirs=[tmp_path]) is None
    assert find_bundled_vbcable_setup(search_dirs=[]) is None


def test_find_default_search_returns_path_or_none():
    found = find_bundled_vbcable_setup()
    assert found is None or found.endswith(".exe")


def test_is_installed_returns_bool():
    # No raising on any platform (False where winreg is unavailable).
    assert isinstance(is_vbcable_installed(), bool)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only driver box")
def test_is_installed_matches_box():
    # Live-box pin: True when CABLE endpoints exist, skip otherwise
    # (the box legitimately has no driver e.g. mid reinstall-test).
    if not is_vbcable_installed():
        pytest.skip("VB-Cable not installed on this box right now")
    assert is_vbcable_installed() is True


class _FakeKey:
    def __init__(self, subkeys=None, values=None, flow=None):
        self.subkeys = subkeys or []
        self.values = values or {}
        self.flow = flow

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_winreg(endpoints):
    """Fake winreg over {flow: [friendly names]}."""
    import types

    mod = types.ModuleType("winreg")
    mod.HKEY_LOCAL_MACHINE = 0
    base = "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\MMDevices\\Audio\\"

    def OpenKey(root, path):
        if path.startswith(base):
            flow = path[len(base):]
            names = endpoints.get(flow, [])
            return _FakeKey(
                subkeys=[f"guid-{i}" for i in range(len(names))], flow=flow)
        # Relative nested open: "<guid>\\Properties" under a flow key.
        guid = path.split("\\")[0]
        flow = getattr(root, "flow", None)
        idx = int(guid.rsplit("-", 1)[1])
        name = endpoints[flow][idx]
        return _FakeKey(values={
            "{a45c254e-df1c-4efd-8020-67d146a850e0},2": (name, 1)})

    def QueryInfoKey(key):
        return (len(key.subkeys), 0, 0)

    def EnumKey(key, i):
        return key.subkeys[i]

    def QueryValueEx(key, name):
        return key.values[name]

    mod.OpenKey = OpenKey
    mod.QueryInfoKey = QueryInfoKey
    mod.EnumKey = EnumKey
    mod.QueryValueEx = QueryValueEx
    return mod


def test_scan_logic_with_fake_registry(monkeypatch):
    import stream_denoiser.backends.platform.windows as win_mod

    fake = _fake_winreg({
        "Render": ["Speakers (High Definition Audio Device)",
                   "CABLE Input (VB-Audio Virtual Cable)"],
        "Capture": ["CABLE Output (VB-Audio Virtual Cable)"],
    })
    monkeypatch.setitem(sys.modules, "winreg", fake)
    assert win_mod.is_vbcable_installed() is True

    fake2 = _fake_winreg({
        "Render": ["Speakers (High Definition Audio Device)"],
        "Capture": ["Microphone"],
    })
    monkeypatch.setitem(sys.modules, "winreg", fake2)
    assert win_mod.is_vbcable_installed() is False


def test_install_bogus_path_fails_fast():
    with pytest.raises(RuntimeError):
        install_vbcable_driver(
            setup_exe="Z:\\definitely\\not\\here\\VBCABLE_Setup_x64.exe",
            timeout_sec=5,
        )
