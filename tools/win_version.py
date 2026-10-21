"""The Windows version resource for Poise's executables.

What Explorer shows under Properties > Details (company, copyright,
product, version) for Poise.exe and Poise_Setup.exe. Shared by
poise_windows.spec and installer/PoiseSetup.spec:

    from win_version import version_info
    exe = EXE(..., version=version_info(PROJECT, "Poise Setup", "Poise_Setup.exe"))

This is credit, not trust: SmartScreen ignores it. Only a code-signing
signature (and the reputation it builds) changes that warning.
"""
from __future__ import annotations

import os
import re

PUBLISHER = "chabandou"
PRODUCT = "Poise Voice Isolator"
COPYRIGHT = "Copyright (c) 2026 chabandou. MIT licensed."


def project_version(project_dir: str) -> str:
    """pyproject.toml's version, e.g. '1.5.0'."""
    with open(os.path.join(project_dir, "pyproject.toml"), encoding="utf-8") as fh:
        match = re.search(r'^version\s*=\s*"([^"]+)"', fh.read(), re.MULTILINE)
    return match.group(1) if match else "0.0.0"


def _numbers(version: str) -> tuple:
    """'1.5.0' -> (1, 5, 0, 0); non-numeric parts count as 0."""
    parts = [int(p) if p.isdigit() else 0
             for p in re.split(r"[.\-+]", version)[:4]]
    return tuple(parts + [0] * (4 - len(parts)))


def version_info(project_dir: str, description: str, filename: str):
    """A PyInstaller VSVersionInfo for one executable."""
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable,
        VarFileInfo, VarStruct, VSVersionInfo,
    )

    version = project_version(project_dir)
    numbers = _numbers(version)
    strings = [
        StringStruct("CompanyName", PUBLISHER),
        StringStruct("FileDescription", description),
        StringStruct("FileVersion", version),
        StringStruct("InternalName", os.path.splitext(filename)[0]),
        StringStruct("LegalCopyright", COPYRIGHT),
        StringStruct("OriginalFilename", filename),
        StringStruct("ProductName", PRODUCT),
        StringStruct("ProductVersion", version),
    ]
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=numbers, prodvers=numbers,
                          mask=0x3F, flags=0x0, OS=0x40004,
                          fileType=0x1, subtype=0x0, date=(0, 0)),
        kids=[
            # 0409 = US English, 04B0 = Unicode.
            StringFileInfo([StringTable("040904B0", strings)]),
            VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
        ],
    )
