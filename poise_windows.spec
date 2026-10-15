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
vbcable_dir = os.path.join(project_dir, 'installer', 'windows', 'vbcable')

datas = [
    (models_dir, 'stream_denoiser/models'),
    (rnnoise_dll_path, '.'),
    (wasapi_dll_path, '.'),
    (assets_path, 'stream_denoiser/gui/assets'),
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
