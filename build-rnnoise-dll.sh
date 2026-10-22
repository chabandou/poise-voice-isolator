#!/usr/bin/env bash
#
# Poise Voice Isolator - RNNoise Build Script
#
# Builds the vendored RNNoise library from the pinned xiph/rnnoise sources
# (runs on Linux):
#   build-rnnoise-dll.sh          -> stream_denoiser/native/rnnoise.dll
#                                    (mingw-w64 cross build; committed)
#   build-rnnoise-dll.sh linux    -> stream_denoiser/native/librnnoise.so
#                                    (native gcc; build-linux.sh bundles it)
# Requires: git, curl, and mingw-w64-gcc (windows) or gcc (linux)
#
# Provenance (update these when refreshing the DLL):
#   RNNOISE_SRC_COMMIT = upstream git commit (github.com/xiph/rnnoise mirror)
#   MODEL_VERSION      = weights set id; the tarball is content-addressed,
#                        so its sha256 must equal MODEL_VERSION.
#
# The library keeps runtime CPU dispatch (generic C + SSE4.1 + AVX2 paths
# selected via cpuid), matching upstream's --enable-x86-rtcd build.

set -e

RNNOISE_SRC_COMMIT="70f1d256acd4b34a572f999a05c87bf00b67730d"
MODEL_VERSION="0a8755f8e2d834eff6a54714ecc7d75f9932e845df35f8b59bc52a7cfe6e8b37"
RNNOISE_MIRROR="https://github.com/xiph/rnnoise.git"
MODEL_URL="https://media.xiph.org/rnnoise/models/rnnoise_data-${MODEL_VERSION}.tar.gz"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="${RNNOISE_BUILD_DIR:-$(mktemp -d)}"

if [ "${1:-windows}" = "linux" ]; then
    CC="${CC:-cc}"
    STRIP=strip
    LIB_NAME=librnnoise.so
    # Hidden by default: only the RNNOISE_EXPORT API stays visible.
    TARGET_FLAGS="-fPIC -fvisibility=hidden"
    LINK_FLAGS="-Wl,-soname,$LIB_NAME -lm"
    list_exports() { nm -D --defined-only "$1"; }
else
    CC=x86_64-w64-mingw32-gcc
    STRIP=x86_64-w64-mingw32-strip
    LIB_NAME=rnnoise.dll
    TARGET_FLAGS="-DDLL_EXPORT"
    LINK_FLAGS="-Wl,--exclude-all-symbols"
    list_exports() {
        x86_64-w64-mingw32-objdump -p "$1" | sed -n '/Ordinal\/Name Pointer/,$p'
    }
fi
OUT_LIB="$SCRIPT_DIR/stream_denoiser/native/$LIB_NAME"

command -v "$CC" >/dev/null || {
    echo "error: $CC not found (install mingw-w64-gcc for windows, gcc for linux)" >&2
    exit 1
}

echo "Working in $WORK_DIR"
mkdir -p "$WORK_DIR"
cd "$WORK_DIR"

if [ ! -d rnnoise-src ]; then
    git clone "$RNNOISE_MIRROR" rnnoise-src
fi
git -C rnnoise-src fetch --depth 1 origin "$RNNOISE_SRC_COMMIT"
git -C rnnoise-src checkout "$RNNOISE_SRC_COMMIT"
test "$(git -C rnnoise-src rev-parse HEAD)" = "$RNNOISE_SRC_COMMIT"

if [ ! -f rnnoise_data.tar.gz ]; then
    curl -sSL --fail -o rnnoise_data.tar.gz "$MODEL_URL"
fi
# The tarball is content-addressed: name hash must match its sha256.
test "$(sha256sum rnnoise_data.tar.gz | cut -d' ' -f1)" = "$MODEL_VERSION"
tar xzf rnnoise_data.tar.gz -C rnnoise-src src/rnnoise_data.c src/rnnoise_data.h

mkdir -p build
printf '#define RNN_ENABLE_X86_RTCD 1\n#define CPU_INFO_BY_C 1\n' > build/config.h

cd rnnoise-src
CFG="$(pwd)/../build"
BASE="-DRNNOISE_BUILD $TARGET_FLAGS -DHAVE_CONFIG_H -I$CFG -Iinclude -Isrc"

for f in denoise rnn pitch kiss_fft celt_lpc nnet nnet_default \
         parse_lpcnet_weights rnnoise_tables x86/x86_dnn_map x86/x86cpu; do
    # shellcheck disable=SC2086
    "$CC" -c -O2 $BASE \
        -o "../build/$(echo "$f" | tr / _).o" "src/$f.c"
done
# Weights blob: -O1 is plenty for static data and keeps memory use sane.
# shellcheck disable=SC2086
"$CC" -c -O1 $BASE \
    -o ../build/rnnoise_data.o src/rnnoise_data.c
"$CC" -c -O2 $BASE -msse4.1 \
    -o ../build/x86_nnet_sse4_1.o src/x86/nnet_sse4_1.c
"$CC" -c -O2 $BASE -mavx -mfma -mavx2 \
    -o ../build/x86_nnet_avx2.o src/x86/nnet_avx2.c

"$CC" -shared -o "../build/$LIB_NAME" ../build/*.o $LINK_FLAGS
"$STRIP" "../build/$LIB_NAME"

echo "Exported symbols:"
list_exports "../build/$LIB_NAME" | grep -o 'rnnoise_[a-z_]*'
for sym in rnnoise_create rnnoise_destroy rnnoise_get_frame_size rnnoise_process_frame; do
    list_exports "../build/$LIB_NAME" | grep -q "$sym" || {
        echo "error: expected export $sym missing" >&2
        exit 1
    }
done

cp "../build/$LIB_NAME" "$OUT_LIB"
echo "Wrote $OUT_LIB ($(stat -c%s "$OUT_LIB") bytes)"
