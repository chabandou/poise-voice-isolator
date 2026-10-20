# -*- mode: python ; coding: utf-8 -*-
import sys
import os
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# Define paths
project_dir = os.getcwd()
icon_path = os.path.join(project_dir, 'stream_denoiser', 'gui', 'assets', 'icon.ico')
models_dir = os.path.join(project_dir, 'stream_denoiser', 'models')
rnnoise_dll_path = os.path.join(project_dir, 'stream_denoiser', 'native', 'rnnoise.dll')
# Native audio path (make -C native/poise_wasapi).
wasapi_dll_path = os.path.join(project_dir, 'stream_denoiser', 'native', 'poise_wasapi.dll')
assets_path = os.path.join(project_dir, 'stream_denoiser', 'gui', 'assets')
# stream_denoiser.__version__ reads it (the single version source).
pyproject_path = os.path.join(project_dir, 'pyproject.toml')
vbcable_dir = os.path.join(project_dir, 'installer', 'windows', 'vbcable')

datas = [
    (models_dir, 'stream_denoiser/models'),
    (rnnoise_dll_path, '.'),
    (wasapi_dll_path, '.'),
    (assets_path, 'stream_denoiser/gui/assets'),
    (pyproject_path, '.'),
]
# Vendored VB-Cable setups (staged via installer/fetch_vbcable.py).
# Optional: a build without the stage dir still works, the in-app
# Install button then falls back to the VB-Audio website.
if os.path.isdir(vbcable_dir):
    datas.append((vbcable_dir, 'vbcable'))

a = Analysis(
    ['run_poise_gui.py'],
    pathex=[project_dir],
    binaries=[],
    datas=datas,
    hiddenimports=[
        # The audio process (spawned: it imports these on its own).
        'stream_denoiser.audio_host',
        'stream_denoiser.session',
        'stream_denoiser.backends.sounddevice_backend',
        'stream_denoiser.backends.wasapi_backend',
        'sounddevice',
        'onnxruntime',
        'numpy',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'torch',
        'torchvision',
        'torchaudio',
        'matplotlib',
        'scipy',
        'pandas',
        'tensorboard',
        'tensorflow',
        'IPython',
        'PIL',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# PyInstaller's QtQml hook bundles every QML module PyQt6 ships
# (Quick3D, Controls, Multimedia...) and the Qt DLLs they link. Only
# the night sky uses Qt Quick (widgets/sky_gpu.py: `import QtQuick`,
# which imports QtQml), so keep those and drop the Qt DLLs nothing
# else links.
from PyInstaller.depend import bindepend

_QML_DIR = 'PyQt6/Qt6/qml/'
_QML_KEEP = {'QtQuick', 'QtQml', 'QtQml/Models', 'QtQml/WorkerScript'}
_QT_BIN = 'PyQt6/Qt6/bin/'


def _dest(entry):
    return entry[0].replace('\\', '/')


def _qml_wanted(entry):
    dest = _dest(entry)
    if not dest.startswith(_QML_DIR):
        return True
    return os.path.dirname(dest[len(_QML_DIR):]) in _QML_KEEP


a.datas = [e for e in a.datas if _qml_wanted(e)]
a.binaries = [e for e in a.binaries if _qml_wanted(e)]

# Qt files nothing loads: the software OpenGL fallback, translations,
# unused image formats and plugins, Git's stray OpenSSL (tools/qt_trim.py
# lists each with its reason). Before the DLL pass below, so Qt6Pdf goes
# with the PDF image plugin that was its only user.
sys.path.insert(0, os.path.join(SPECPATH, 'tools'))
from qt_trim import trim as _qt_trim  # noqa: E402
from win_version import version_info  # noqa: E402
a.binaries, a.datas = _qt_trim(a.binaries, a.datas)

# Qt DLLs still linked from what is left (Qt loads none of them by name).
_qt_dlls = {os.path.basename(_dest(e)).lower(): e for e in a.binaries
            if _dest(e).startswith(_QT_BIN)
            and os.path.basename(_dest(e)).lower().startswith('qt6')}
_linked = set()
_todo = [e[1] for e in a.binaries
         if os.path.basename(_dest(e)).lower() not in _qt_dlls]
while _todo:
    for _name, _ in bindepend.get_imports(_todo.pop()):
        _name = _name.lower()
        if _name in _qt_dlls and _name not in _linked:
            _linked.add(_name)
            _todo.append(_qt_dlls[_name][1])
a.binaries = [e for e in a.binaries
              if os.path.basename(_dest(e)).lower() not in _qt_dlls
              or os.path.basename(_dest(e)).lower() in _linked]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Poise',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements=None,
    icon=icon_path,
    # Properties > Details: publisher, copyright, version (tools/win_version.py).
    version=version_info(SPECPATH, 'Poise Voice Isolator', 'Poise.exe'),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Poise',
)
