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
    echo "Creating poise-build conda environment with Python 3.12..."
    conda create -n poise-build python=3.12 -y
fi

# Activate and install dependencies
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate poise-build

echo "Installing build dependencies..."
# NOTE: textual is pinned to the repo floor (>=8.2.8): older releases wash
# footer key text and can't render transparent filler. A bare `textual`
# requirement would keep whatever stale version the env already has.
pip install -q nuitka ordered-set numpy onnxruntime "textual>=8.2.8" pulsectl samplerate scipy

# Install ccache if not present (speeds up rebuilds)
if ! command -v ccache &> /dev/null; then
    echo "Installing ccache for faster rebuilds..."
    conda install -q ccache -y
fi

# Install patchelf if not present (needed to clear a bad executable-stack
# flag on the ONNX Runtime library, which Nuitka would otherwise bundle)
if ! command -v patchelf &> /dev/null; then
    echo "Installing patchelf for execstack hygiene..."
    conda install -q patchelf -y || echo "⚠ patchelf unavailable - continuing (fails later only if the ONNX .so needs patching)"
fi

# Check for model files
if [ ! -f "denoiser_model_df3.onnx" ] || [ ! -f "denoiser_model_df3_states.npz" ]; then
    echo "❌ Error: DeepFilterNet3 model files not found (denoiser_model_df3.onnx + denoiser_model_df3_states.npz)!"
    exit 1
fi
echo "✓ ONNX models found"
echo

# Execstack hygiene: Nuitka bundles the build env's onnxruntime .so byte for
# byte, so a GNU_STACK RWE flag would break the binary on hardened systems
# for every user. Detect via the repo's own health module and patch the
# installed wheel in place (same operation as --fix-execstack) before bundling.
echo "Checking ONNX Runtime executable-stack flag..."
EXECSTACK_STATUS=$(python -c "
from stream_denoiser.health import find_onnxruntime_so, gnu_stack_flags
so = find_onnxruntime_so()
if so is None:
    print('MISSING')
else:
    flags = gnu_stack_flags(so)
    if flags is None:
        print(f'CLEAN|{so}')
    else:
        r, w, x = flags
        state = 'DIRTY' if (w and x) else 'CLEAN'
        print(f'{state}|{so}')
")
EXECSTACK_STATE=$(echo "$EXECSTACK_STATUS" | cut -d'|' -f1)
ORT_SO_PATH=$(echo "$EXECSTACK_STATUS" | cut -d'|' -f2-)
if [ "$EXECSTACK_STATE" = "MISSING" ]; then
    echo "❌ Error: onnxruntime not installed in the build environment!"
    exit 1
elif [ "$EXECSTACK_STATE" = "CLEAN" ]; then
    echo "✓ ONNX Runtime library clean ($ORT_SO_PATH)"
else
    echo "⚠ Executable-stack flag set on $ORT_SO_PATH - patching..."
    if ! command -v patchelf &> /dev/null; then
        echo "❌ Error: patchelf is required to fix this (the binary would fail on hardened systems)."
        echo "   Install it and rebuild: conda install patchelf"
        exit 1
    fi
    patchelf --clear-execstack "$ORT_SO_PATH"
    RECHECK=$(python -c "
from stream_denoiser.health import gnu_stack_flags
flags = gnu_stack_flags('$ORT_SO_PATH')
print('DIRTY' if (flags is not None and flags[1] and flags[2]) else 'CLEAN')
")
    if [ "$RECHECK" != "CLEAN" ]; then
        echo "❌ Error: flag still set after patchelf - aborting build."
        exit 1
    fi
    echo "✓ Executable-stack flag cleared ($ORT_SO_PATH)"
fi
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
    --nofollow-import-to=pytest,setuptools,pip,wheel,distutils \
    --nofollow-import-to=torch,tensorflow,keras,matplotlib,pandas,IPython \
    --nofollow-import-to=PyQt6,PyQt5,tkinter,PIL,cv2 \
    --nofollow-import-to=sounddevice,pyaudio,pyaudiowpatch \
    --nofollow-import-to=scipy.io,scipy.optimize,scipy.stats \
    --remove-output \
    --assume-yes-for-downloads \
    --include-data-files=denoiser_model_df3.onnx=denoiser_model_df3.onnx \
    --include-data-files=denoiser_model_df3_states.npz=denoiser_model_df3_states.npz \
    --include-data-dir=stream_denoiser/tui=stream_denoiser/tui \
    --output-filename=poise \
    --output-dir=dist \
    poise_tui.py

echo
echo "╭────────────────────────────────────────────╮"
echo "│           ✓ Build Complete!               │"
echo "╰────────────────────────────────────────────╯"
echo
echo "Output: dist/poise"
echo "Size: $(du -h dist/poise | cut -f1)"
echo
echo "Verifying no PortAudio linkage (pulse-simple only)..."
if command -v ldd &> /dev/null; then
    if ldd dist/poise 2>/dev/null | grep -qi portaudio; then
        echo "❌ Error: binary links libportaudio (PortAudio must not ship on Linux)."
        exit 1
    else
        echo "✓ No libportaudio in ldd output"
    fi
fi
# Runtime check: launch briefly and confirm no libportaudio maps.
# (Skipped when no Pulse server is available in the build container, or
# when there is no TTY for the TUI.) Any null sink the probe creates is
# torn down with --reset-audio afterwards so the build never litters audio.
if ./dist/poise --doctor >/dev/null 2>&1; then
    POISE_PID=""
    ./dist/poise >/dev/null 2>&1 &
    POISE_PID=$!
    sleep 2
    if [ -n "$POISE_PID" ] && [ -f "/proc/$POISE_PID/maps" ]; then
        if grep -qi portaudio "/proc/$POISE_PID/maps"; then
            echo "❌ Error: libportaudio appears in process maps."
            kill "$POISE_PID" 2>/dev/null || true
            ./dist/poise --reset-audio >/dev/null 2>&1 || true
            exit 1
        else
            echo "✓ No libportaudio in process maps"
        fi
    else
        echo "(probe exited without a TTY - ldd check only)"
    fi
    if [ -n "$POISE_PID" ]; then
        kill "$POISE_PID" 2>/dev/null || true
        wait "$POISE_PID" 2>/dev/null || true
        ./dist/poise --reset-audio >/dev/null 2>&1 || true
    fi
else
    echo "(doctor unavailable without a Pulse server - ldd check only)"
fi
echo
echo "To install system-wide:"
echo "  sudo cp dist/poise /usr/local/bin/"
echo
