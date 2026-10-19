# -*- mode: python ; coding: utf-8 -*-
"""Builds Poise_Setup.exe: the Poise setup window with the Inno core inside.

Compile the core first - it is what actually installs anything:

    ISCC.exe /DCORE setup.iss        ->  installer/PoiseCore.exe

then:

    pyinstaller installer/PoiseSetup.spec --noconfirm ^
        --distpath installer --workpath build/installer

The result is a single Poise_Setup.exe. A UI-only build (for working on
the window itself) is possible with POISE_SETUP_DEV=1; it opens and looks
right but refuses to install anything.
"""
import os
import re

ROOT = SPECPATH                     # .../installer
PROJECT = os.path.dirname(ROOT)
CORE = os.path.join(ROOT, "PoiseCore.exe")
ASSETS = os.path.join(PROJECT, "stream_denoiser", "gui", "assets")
ICON = os.path.join(ASSETS, "icon.ico")
DEV = os.environ.get("POISE_SETUP_DEV") == "1"

if not os.path.isfile(CORE) and not DEV:
    raise SystemExit(
        "installer/PoiseCore.exe is missing.\n"
        "Compile the core first:  ISCC.exe /DCORE setup.iss\n"
        "or set POISE_SETUP_DEV=1 to build the window alone.")


def _version():
    with open(os.path.join(PROJECT, "pyproject.toml"), encoding="utf-8") as fh:
        match = re.search(r'^version\s*=\s*"([^"]+)"', fh.read(), re.MULTILINE)
    return match.group(1) if match else "dev"


# The window reads the release version from this bundled file.
_build_dir = os.path.join(PROJECT, "build", "installer")
os.makedirs(_build_dir, exist_ok=True)
_version_file = os.path.join(_build_dir, "version.txt")
with open(_version_file, "w", encoding="utf-8") as fh:
    fh.write(_version() + "\n")

datas = [
    (os.path.join(ASSETS, "icon.png"), "assets"),
    (os.path.join(ASSETS, "icon.svg"), "assets"),
    (os.path.join(ASSETS, "icon.ico"), "assets"),
    (os.path.join(ASSETS, "fonts", "Rajdhani-Bold.ttf"), "assets/fonts"),
    (os.path.join(ASSETS, "fonts", "Rajdhani-SemiBold.ttf"), "assets/fonts"),
    (_version_file, "."),
]
if os.path.isfile(CORE):
    datas.append((CORE, "."))

a = Analysis(
    [os.path.join(ROOT, "setup_app.py")],
    pathex=[PROJECT],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # None of the app's runtime, none of Qt's heavier siblings: the
        # window only needs Widgets/Gui/Core.
        "numpy", "onnxruntime", "sounddevice", "scipy", "pandas", "torch",
        "matplotlib", "PIL", "IPython",
        "PyQt6.QtNetwork", "PyQt6.QtQml", "PyQt6.QtQuick",
        "PyQt6.QtMultimedia", "PyQt6.QtWebEngineCore", "PyQt6.QtSql",
        "PyQt6.QtTest", "PyQt6.QtDBus", "PyQt6.QtOpenGL",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Poise_Setup",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements=None,
    icon=ICON,
    # The core must write to Program Files and run the driver setup, so
    # a real build asks for elevation once, up front. A UI-only build
    # cannot install anything, so it does not demand admin.
    uac_admin=not DEV,
)
