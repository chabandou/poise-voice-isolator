"""Tests for startup health checks and audio recovery (no system changes)."""
import struct
import sys

import pytest

from stream_denoiser import health


def _minimal_elf(tmp_path, flags):
    """Write a minimal ELF64 with a single PT_GNU_STACK segment."""
    e_ident = (b"\x7fELF" + bytes([2, 1, 1, 0]) + b"\x00" * 8)
    header = e_ident + struct.pack(
        "<HHIQQQIHHHHHH",
        2, 0x3E, 1, 0, 0x40, 0, 0, 64, 56, 1, 0, 0, 0,
    )
    assert len(header) == 0x40
    phdr = struct.pack("<IIQQQQQQ", 0x6474E551, flags, 0, 0, 0, 0, 0, 0)
    path = tmp_path / "fake.so"
    path.write_bytes(header + phdr)
    return str(path)


def test_gnu_stack_rw_is_clean(tmp_path):
    assert health.gnu_stack_flags(_minimal_elf(tmp_path, 0x6)) == (True, True, False)


def test_gnu_stack_rwe_detected(tmp_path):
    assert health.gnu_stack_flags(_minimal_elf(tmp_path, 0x7)) == (True, True, True)


def test_gnu_stack_garbage_returns_none(tmp_path):
    path = tmp_path / "not-elf.so"
    path.write_bytes(b"definitely not an elf file")
    assert health.gnu_stack_flags(str(path)) is None
    assert health.gnu_stack_flags(str(tmp_path / "missing.so")) is None


def test_check_execstack_live_library():
    if health.find_onnxruntime_so() is None:
        pytest.skip("onnxruntime not installed")
    result = health.check_execstack()
    assert result.ok  # this machine's wheel is clean; RWE would fail loudly


def test_check_portaudio_live():
    result = health.check_portaudio()
    # Must never raise; on a healthy box it passes, elsewhere it explains.
    assert result.name == "portaudio"
    assert isinstance(result.detail, str)


def test_reset_audio_rejects_non_linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    ok, message = health.reset_audio()
    assert ok is False
    assert "Linux" in message


def test_reset_audio_unloads_only_own_modules(monkeypatch):
    calls = []

    def fake_run(cmd, timeout=10):
        calls.append(cmd)
        if cmd[:2] == ["pactl", "get-default-sink"]:
            return True, "Poise_Capture\n", ""
        if cmd == ["pactl", "list", "modules", "short"]:
            return True, (
                "25\tmodule-null-sink\targs sink_name=Poise_Capture\n"
                "26\tmodule-null-sink\targs sink_name=OtherApp_Sink\n"
            ), ""
        if cmd[:2] == ["pactl", "set-default-sink"]:
            return True, "", ""
        if cmd[:2] == ["pactl", "unload-module"]:
            return True, "", ""
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(health, "_run", fake_run)
    monkeypatch.setattr(
        health, "_list_sink_names",
        lambda: ["Poise_Capture", "alsa_output.pci-0000_00_1f.3.analog-stereo"],
    )
    monkeypatch.setattr(health, "_pactl_available", lambda: True)

    ok, message = health.reset_audio()
    assert ok is True
    unloads = [c for c in calls if c[:2] == ["pactl", "unload-module"]]
    assert unloads == [["pactl", "unload-module", "25"]]
    assert any(c[:2] == ["pactl", "set-default-sink"] for c in calls)
    assert "restored" in message


def test_reset_audio_without_pactl(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(health, "_pactl_available", lambda: False)
    ok, message = health.reset_audio()
    assert ok is False
    assert "pactl" in message


def test_apply_fix_when_patchelf_missing(monkeypatch, tmp_path):
    so = _minimal_elf(tmp_path, 0x7)
    monkeypatch.setattr(health, "find_onnxruntime_so", lambda: so)
    monkeypatch.setattr(health.shutil, "which", lambda name: None)
    ok, message = health.apply_execstack_fix()
    assert ok is False
    assert "patchelf" in message
