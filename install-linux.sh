#!/usr/bin/env bash
#
# Poise Voice Isolator - Linux Installer
#
# This script installs Poise with the 'poise' command available system-wide.
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_PREFIX="${HOME}/.local"
PORTAUDIO_BUILD_DIR="/tmp/portaudio-poise"

echo "╭────────────────────────────────────────────╮"
echo "│     Poise Voice Isolator - Installer       │"
echo "╰────────────────────────────────────────────╯"
echo

# Check for Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required but not found."
    echo "   Install it with: sudo pacman -S python  (Arch)"
    echo "                    sudo apt install python3  (Ubuntu)"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "✓ Python $PYTHON_VERSION found"

# Check for pip
if ! python3 -m pip --version &> /dev/null; then
    echo "❌ pip is required but not found."
    echo "   Install it with: sudo pacman -S python-pip  (Arch)"
    echo "                    sudo apt install python3-pip  (Ubuntu)"
    exit 1
fi
echo "✓ pip found"

# Detect distro for package manager
install_dependencies() {
    echo
    echo "Installing system dependencies..."
    
    if command -v pacman &> /dev/null; then
        # Arch Linux
        echo "Detected: Arch Linux"
        sudo pacman -S --needed --noconfirm base-devel cmake libpulse alsa-lib patchelf
    elif command -v apt &> /dev/null; then
        # Debian/Ubuntu
        echo "Detected: Debian/Ubuntu"
        sudo apt update
        sudo apt install -y build-essential cmake libpulse-dev libasound2-dev patchelf
    elif command -v dnf &> /dev/null; then
        # Fedora
        echo "Detected: Fedora"
        sudo dnf install -y gcc-c++ cmake pulseaudio-libs-devel alsa-lib-devel patchelf
    else
        echo "⚠ Unknown distribution. Please install manually:"
        echo "   - cmake, gcc/g++, pulseaudio-dev, alsa-dev, patchelf"
    fi
}

# Build PortAudio with PulseAudio support
build_portaudio() {
    echo
    echo "Building PortAudio with PulseAudio support..."
    echo "(This is required for proper audio device detection)"
    
    if [ -f "/usr/local/lib/libportaudio.so" ]; then
        echo "✓ PortAudio already installed in /usr/local/lib"
        read -p "  Rebuild anyway? [y/N] " rebuild
        if [[ ! "$rebuild" =~ ^[Yy]$ ]]; then
            return 0
        fi
    fi
    
    rm -rf "$PORTAUDIO_BUILD_DIR"
    git clone https://github.com/PortAudio/portaudio.git "$PORTAUDIO_BUILD_DIR"
    cd "$PORTAUDIO_BUILD_DIR"
    mkdir build && cd build
    
    cmake .. \
        -DCMAKE_BUILD_TYPE=Release \
        -DPA_USE_ALSA=ON \
        -DPA_USE_JACK=OFF \
        -DPA_USE_PULSEAUDIO=ON \
        -DCMAKE_INSTALL_PREFIX=/usr/local
    
    make -j$(nproc)
    sudo make install
    sudo ldconfig
    
    echo "✓ PortAudio built and installed to /usr/local/lib"
    cd "$SCRIPT_DIR"
    rm -rf "$PORTAUDIO_BUILD_DIR"
}

# Install Poise
install_poise() {
    echo
    echo "Installing Poise Voice Isolator..."
    
    # Install with pip in editable mode for development, or regular install
    cd "$SCRIPT_DIR"
    
    # Reinstall sounddevice to pick up new PortAudio
    pip3 uninstall -y sounddevice 2>/dev/null || true
    pip3 install sounddevice --no-cache-dir
    
    # Install poise with Linux extras
    pip3 install -e ".[linux]" --user
    
    echo "✓ Poise installed"
}

# Fix ONNX Runtime executable stack issue
fix_onnxruntime() {
    echo
    echo "Fixing ONNX Runtime executable stack issue..."
    
    ONNX_LIB=$(python3 -c "import onnxruntime; import os; print(os.path.dirname(onnxruntime.__file__))" 2>/dev/null)/capi/onnxruntime_pybind11_state.cpython-*.so
    
    if ls $ONNX_LIB 1>/dev/null 2>&1; then
        for lib in $ONNX_LIB; do
            if [ -f "$lib" ]; then
                patchelf --clear-execstack "$lib" 2>/dev/null || true
                echo "✓ Fixed: $(basename $lib)"
            fi
        done
    else
        echo "⚠ ONNX Runtime library not found, skipping fix"
    fi
}

# Create launcher script with LD_LIBRARY_PATH
create_launcher() {
    echo
    echo "Creating launcher script..."
    
    mkdir -p "$INSTALL_PREFIX/bin"
    
    cat > "$INSTALL_PREFIX/bin/poise" << 'EOF'
#!/usr/bin/env bash
# Poise Voice Isolator launcher
# Sets LD_LIBRARY_PATH for custom PortAudio build
export LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH
exec python3 -m stream_denoiser --tui "$@"
EOF
    
    chmod +x "$INSTALL_PREFIX/bin/poise"
    
    # Also create poise-cli for CLI mode
    cat > "$INSTALL_PREFIX/bin/poise-cli" << 'EOF'
#!/usr/bin/env bash
export LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH
exec python3 -m stream_denoiser "$@"
EOF
    
    chmod +x "$INSTALL_PREFIX/bin/poise-cli"
    
    echo "✓ Launcher scripts created in $INSTALL_PREFIX/bin/"
    
    # Check if ~/.local/bin is in PATH
    if [[ ":$PATH:" != *":$INSTALL_PREFIX/bin:"* ]]; then
        echo
        echo "⚠ $INSTALL_PREFIX/bin is not in your PATH."
        echo "  Add this to your ~/.bashrc or ~/.zshrc:"
        echo
        echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
        echo
    fi
}

# Main installation flow
main() {
    echo "This installer will:"
    echo "  1. Install system dependencies (requires sudo)"
    echo "  2. Build PortAudio with PulseAudio support"
    echo "  3. Install Poise and Python dependencies"
    echo "  4. Create the 'poise' command"
    echo
    read -p "Continue? [Y/n] " confirm
    if [[ "$confirm" =~ ^[Nn]$ ]]; then
        echo "Installation cancelled."
        exit 0
    fi
    
    install_dependencies
    build_portaudio
    install_poise
    fix_onnxruntime
    create_launcher
    
    echo
    echo "╭────────────────────────────────────────────╮"
    echo "│     ✓ Installation Complete!              │"
    echo "╰────────────────────────────────────────────╯"
    echo
    echo "Run 'poise' to start the TUI, or 'poise-cli' for CLI mode."
    echo
}

main "$@"
