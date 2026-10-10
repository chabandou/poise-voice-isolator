#!/usr/bin/env python3
"""Stage VB-Cable driver files for the Windows installer/app bundle.

Downloads VBCABLE_Driver_Pack45.zip from VB-Audio, verifies its SHA-256,
and extracts the setup executables into installer/windows/vbcable/.

The zip itself is NOT committed to git (build-time download, like the
RNNoise weights in build-rnnoise-dll.sh). Only the two setup exes needed
at install/runtime are staged:

    installer/windows/vbcable/VBCABLE_Setup_x64.exe  (64-bit + ARM64)
    installer/windows/vbcable/VBCABLE_Setup.exe      (32-bit fallback)

VB-Audio allows bundling the base VB-CABLE package with silent install
provided the donationware attribution is shown (see setup.iss and the
in-app dialog). CABLE A+B / C+D must NOT be bundled.

Usage:
    python installer/fetch_vbcable.py [--force]

Exit 0 when the staged files are present and valid (idempotent: skips
the download when the staged exes already match).
"""
import hashlib
import sys
import urllib.request
import zipfile
from pathlib import Path

PACK_URL = (
    "https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack45.zip"
)
# Pinned 2024-10 pack. Bump together with PACK_URL when refreshing.
PACK_SHA256 = "b950e39f01af1d04ea623c8f6d8eb9b6ea5c477c637295fabf20631c85116bfb"

INSTALLER_DIR = Path(__file__).resolve().parent / "windows"
STAGE_DIR = INSTALLER_DIR / "vbcable"
WANTED = ("VBCABLE_Setup_x64.exe", "VBCABLE_Setup.exe")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _staged_ok() -> bool:
    return all((STAGE_DIR / name).is_file() for name in WANTED)


def main() -> int:
    force = "--force" in sys.argv[1:]
    if _staged_ok() and not force:
        print(f"VB-Cable already staged in {STAGE_DIR}, skipping.")
        return 0

    STAGE_DIR.mkdir(parents=True, exist_ok=True)
    tmp_zip = STAGE_DIR / "pack45.zip"
    print(f"Downloading {PACK_URL} ...")
    try:
        urllib.request.urlretrieve(PACK_URL, tmp_zip)
    except Exception as e:
        print(f"error: download failed: {e}", file=sys.stderr)
        return 1

    digest = _sha256(tmp_zip)
    if digest.lower() != PACK_SHA256.lower():
        print(
            f"error: sha256 mismatch:\n  got:      {digest}\n"
            f"  expected: {PACK_SHA256}\n"
            "Refusing to stage (pack may have been re-released; "
            "update PACK_URL/PACK_SHA256).",
            file=sys.stderr,
        )
        tmp_zip.unlink(missing_ok=True)
        return 1
    print("Checksum OK.")

    with zipfile.ZipFile(tmp_zip) as zf:
        names = set(zf.namelist())
        for name in WANTED:
            if name not in names:
                print(f"error: {name} missing from pack", file=sys.stderr)
                return 1
            with zf.open(name) as src, open(STAGE_DIR / name, "wb") as dst:
                dst.write(src.read())
    tmp_zip.unlink(missing_ok=True)
    for name in WANTED:
        size = (STAGE_DIR / name).stat().st_size
        print(f"Staged {name} ({size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
