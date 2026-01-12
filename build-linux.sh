#!/usr/bin/env bash
#
# Poise Voice Isolator - Linux Build Script (Nuitka)
#
# Builds an optimized single-file executable.
# Requires: Python 3.13, gcc, conda/mamba
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "╭────────────────────────────────────────────╮"
echo "│   Poise Voice Isolator - Nuitka Builder   │"
echo "╰────────────────────────────────────────────╯"
echo

# Setup conda env
if ! conda env list | grep -q "poise-build"; then
    echo "Creating poise-build conda environment with Python 3.13..."
    conda create -n poise-build python=3.13 -y
fi

# Activate and install dependencies
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate poise-build

echo "Installing build dependencies..."
pip install -q nuitka ordered-set numpy onnxruntime sounddevice pulsectl textual samplerate scipy

# Install ccache if not present (speeds up rebuilds)
if ! command -v ccache &> /dev/null; then
    echo "Installing ccache for faster rebuilds..."
    conda install -q ccache -y
fi

# Check for model file
if [ ! -f "denoiser_model.onnx" ]; then
    echo "❌ Error: denoiser_model.onnx not found!"
    exit 1
fi
echo "✓ ONNX model found"
echo

# Clean previous build
rm -rf dist/__main__.* dist/poise

# Build using --python-flag=-m to properly handle __main__.py as module
echo "Building with Nuitka (this takes several minutes)..."
python -m nuitka \
    --standalone \
    --onefile \
    --static-libpython=no \
    --lto=yes \
    --python-flag=-m \
    --module-name=stream_denoiser.tui \
    --nofollow-import-to=pytest,setuptools,pip,wheel,distutils \
    --nofollow-import-to=torch,tensorflow,keras,matplotlib,pandas,IPython \
    --nofollow-import-to=PyQt6,PyQt5,tkinter,PIL,cv2 \
    --nofollow-import-to=scipy.io,scipy.optimize,scipy.stats \
    --remove-output \
    --assume-yes-for-downloads \
    --include-data-files=denoiser_model.onnx=denoiser_model.onnx \
    --include-data-dir=stream_denoiser/tui=stream_denoiser/tui \
    --output-filename=poise \
    --output-dir=dist \
    stream_denoiser/tui

echo
echo "╭────────────────────────────────────────────╮"
echo "│           ✓ Build Complete!               │"
echo "╰────────────────────────────────────────────╯"
echo
echo "Output: dist/poise"
echo "Size: $(du -h dist/poise | cut -f1)"
echo
echo "To install system-wide:"
echo "  sudo cp dist/poise /usr/local/bin/"
echo
