"""Tests for the Windows RNNoise integration (vendored rnnoise.dll).

The DLL itself can only be _loaded_ on Windows, but the search-path logic
and the vendored binary's integrity are verifiable on any platform.
"""
import os
import struct
import sys

import pytest

from stream_denoiser.engines.rnnoise import (
    WINDOWS_DLL_NAME,
    _windows_dll_candidates,
)

NATIVE_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "stream_denoiser", "native",
))
VENDORED_DLL = os.path.join(NATIVE_DIR, WINDOWS_DLL_NAME)


def test_windows_candidates_end_with_dll_name():
    candidates = _windows_dll_candidates()
    assert candidates, "expected at least one search path"
    assert all(c.endswith(WINDOWS_DLL_NAME) for c in candidates)
    # Dev checkout path must always be included so source runs find it.
    assert os.path.normpath(os.path.join(NATIVE_DIR, WINDOWS_DLL_NAME)) in (
        os.path.normpath(c) for c in candidates
    )


def test_vendored_dll_exists_and_is_pe():
    assert os.path.isfile(VENDORED_DLL), (
        f"{WINDOWS_DLL_NAME} missing — rebuild with build-rnnoise-dll.sh"
    )
    with open(VENDORED_DLL, "rb") as f:
        dos_header = f.read(64)
    assert dos_header[:2] == b"MZ", "missing DOS MZ magic"
    (e_lfanew,) = struct.unpack("<I", dos_header[60:64])
    with open(VENDORED_DLL, "rb") as f:
        f.seek(e_lfanew)
        assert f.read(6) == b"PE\x00\x00\x64\x86", (
            "expected PE32+ (x86-64) signature"
        )


def test_vendored_dll_is_64bit_only():
    # A 32-bit Python / installer must never pick this up silently;
    # the PE machine field pins the arch contract (0x8664 = x86-64).
    with open(VENDORED_DLL, "rb") as f:
        dos_header = f.read(64)
    (e_lfanew,) = struct.unpack("<I", dos_header[60:64])
    with open(VENDORED_DLL, "rb") as f:
        f.seek(e_lfanew + 4)
        (machine,) = struct.unpack("<H", f.read(2))
    assert machine == 0x8664


@pytest.mark.skipif(sys.platform == "win32",
                    reason="simulates win32 from a non-Windows host")
def test_win32_branch_raises_windows_error_when_unloadable(monkeypatch):
    # Pretend to be Windows on a host that cannot load PE binaries:
    # every candidate (incl. the vendored DLL) fails with OSError,
    # so the loader must surface the Windows-specific message.
    import stream_denoiser.engines.rnnoise as rnnoise_mod

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(rnnoise_mod, "_lib", None)
    with pytest.raises(RuntimeError, match=r"rnnoise\.dll"):
        rnnoise_mod._load_library()
    assert rnnoise_mod._lib is None, "failed load must not be cached"
