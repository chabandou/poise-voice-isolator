#!/usr/bin/env bash
#
# Poise Voice Isolator - development environment (macOS, and anywhere else)
#
# Creates the venv, installs the package and the test deps, builds the native
# node on macOS, and runs the suite. Safe to re-run: it repairs a venv whose
# interpreter has gone away, which is the usual failure after a tool manager
# prunes or upgrades the Python it was built from:
#
#   .venv/bin/poise: bad interpreter: .../python3.12: no such file or directory
#
#   tools/dev_env.sh              # repair/create, install, build, test
#   tools/dev_env.sh --no-test    # skip the test run
#   PYTHON=/path/to/python3.12 tools/dev_env.sh
#
# Why 3.12: requirements.txt pins numpy<2, which has no wheels past cp312, so
# 3.13+ falls back to an sdist build that fails. Any 3.10-3.12 works; the port
# was developed and measured on 3.12.

set -eu

cd "$(dirname "${BASH_SOURCE[0]}")/.."
ROOT=$(pwd)
VENV="$ROOT/.venv"

run_tests=1
[ "${1:-}" = "--no-test" ] && run_tests=0

say() { printf '%s\n' "$*"; }
die() { printf 'dev_env: %s\n' "$*" >&2; exit 1; }

# --- 1. which interpreter ---------------------------------------------------
# Prefer an explicit one, then a pinned tool (mise is what the macOS port was
# developed with), then whatever python3.12 is on PATH.
pick_python() {
    if [ -n "${PYTHON:-}" ]; then
        printf '%s' "$PYTHON"
        return 0
    fi
    if command -v mise >/dev/null 2>&1 && mise where python@3.12 >/dev/null 2>&1; then
        printf '%s' "$(mise where python@3.12)/bin/python3.12"
        return 0
    fi
    command -v python3.12 2>/dev/null && return 0
    return 1
}

PY=$(pick_python) || die "no python3.10-3.12 found: install one (brew install python@3.12,
       or mise install python@3.12) or pass PYTHON=/path/to/python"
[ -x "$PY" ] || die "$PY is not executable (a pruned tool version? try: mise install python@3.12)"
say "dev_env: interpreter $("$PY" -V 2>&1)"

# --- 2. the venv ------------------------------------------------------------
# A venv keeps a link (or copy) of the interpreter it was made from and the
# path back to its standard library in pyvenv.cfg, so removing that install
# breaks it even though the directory still looks fine. Test it by running it.
venv_ok=0
if [ -x "$VENV/bin/python" ] && "$VENV/bin/python" -c 'import sys' >/dev/null 2>&1; then
    venv_ok=1
fi
if [ "$venv_ok" = 1 ]; then
    say "dev_env: venv ok ($("$VENV/bin/python" -V 2>&1))"
else
    say "dev_env: (re)creating .venv"
    rm -rf "$VENV"
    "$PY" -m venv "$VENV"
fi

# --- 3. dependencies --------------------------------------------------------
if "$VENV/bin/python" -c 'import numpy, onnxruntime, samplerate, textual, pytest' \
        >/dev/null 2>&1; then
    say "dev_env: dependencies present"
else
    say "dev_env: installing dependencies (this fetches wheels, ~1 minute)"
    "$VENV/bin/pip" -q install --upgrade pip
    "$VENV/bin/pip" -q install -e .
    "$VENV/bin/pip" -q install pytest textual
fi

# --- 4. the native node (macOS only; Linux/Windows have their own makefiles)
if [ "$(uname -s)" = "Darwin" ]; then
    if [ ! -f stream_denoiser/native/libpoise_coreaudio.dylib ]; then
        say "dev_env: building the Core Audio node"
        make -C native/poise_coreaudio >/dev/null
    fi
    [ -f stream_denoiser/native/libpoise_coreaudio.dylib ] \
        || die "the Core Audio node did not build (needs the Xcode command-line tools)"
    say "dev_env: native node present"
fi

# --- 5. done ----------------------------------------------------------------
if [ "$run_tests" = 1 ]; then
    say "dev_env: running the suite"
    "$VENV/bin/python" -m pytest -q
fi

cat <<EOF

Ready:
  $VENV/bin/poise              terminal UI  (space starts/stops, q quits)
  $VENV/bin/poise-cli          headless     (Ctrl-C stops)
  $VENV/bin/poise --doctor     why is it silent / is the grant missing
EOF
