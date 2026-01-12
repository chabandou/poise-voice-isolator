# -*- mode: python ; coding: utf-8 -*-
import sys
import os
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# Define paths
project_dir = os.getcwd()
icon_path = os.path.join(project_dir, 'stream_denoiser', 'gui', 'assets', 'icon.ico')
model_path = os.path.join(project_dir, 'denoiser_model.onnx')
assets_path = os.path.join(project_dir, 'stream_denoiser', 'gui', 'assets')

a = Analysis(
    ['run_poise_gui.py'],
    pathex=[project_dir],
    binaries=[],
    datas=[
        (model_path, '.'),
        (assets_path, 'stream_denoiser/gui/assets'),
    ],
    hiddenimports=[
        'stream_denoiser.backends.pyaudio_backend',
        'stream_denoiser.backends.sounddevice_backend',
        'pyaudiowpatch',
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
