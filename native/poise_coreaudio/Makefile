# Builds Poise's macOS audio node: libpoise_coreaudio.dylib (the shipping
# artifact, loaded by stream_denoiser/backends/coreaudio_node.py through
# ctypes) and the standalone spike harness (poise_coreaudio, the T3 CLI).
#
#   make -C native/poise_coreaudio            # -> dylib + ./poise_coreaudio
#   make -C native/poise_coreaudio dylib
#   make -C native/poise_coreaudio cli
#   make -C native/poise_coreaudio clean
#
# The dylib is built, never committed (mirroring native/poise_pw's .so and
# .gitignore): it carries both symbol families, poise_ca_* (the node) and
# poise_core_* (the fixed-delay core, compiled in from ../core).
#
# The CLI is the spike's measurement harness and has to be run from the dev
# bundle instead of as a bare executable, because TCC attributes the System
# Audio Recording grant to the bundle:
#
#   tools/make_dev_app.sh && open -n -W build/PoiseDev.app --args --seconds 5 ...
#
# Core Audio itself needs no other framework; AudioToolbox is used for the
# format names in the report, Foundation for CATapDescription.

SDK ?= $(shell xcrun --sdk macosx --show-sdk-path 2>/dev/null)
# The tap API is macOS 14.2; set the deployment target from that, not from the
# Xcode default, so the built artifact actually claims the API it uses.
MIN_MACOS ?= 14.2

CC ?= clang
OBJCFLAGS ?= -O2 -g
OBJCFLAGS += -std=gnu11 -Wall -Wextra -Wno-unused-parameter -fobjc-arc
LDLIBS := -framework CoreAudio -framework AudioToolbox -framework Foundation

# The fixed-delay core, shared with the Linux and Windows paths.
CORE := ../core
SRC := poise_coreaudio.m $(CORE)/poise_core.c
HDR := poise_coreaudio.h $(CORE)/poise_core.h

OUT ?= ../../stream_denoiser/native/libpoise_coreaudio.dylib
CLI ?= poise_coreaudio

# Guard ARM64/Intel: the plan targets Apple Silicon; x86_64 is untested (R8), so
# build for the host arch rather than a universal binary.
ARCH ?= $(shell uname -m)
SYSROOT := $(if $(SDK),-isysroot $(SDK),)
TARGET := -mmacosx-version-min=$(MIN_MACOS) -arch $(ARCH) $(SYSROOT)

all: $(OUT) $(CLI)

dylib: $(OUT)
cli: $(CLI)

$(OUT): $(SRC) $(HDR)
	$(CC) $(OBJCFLAGS) $(TARGET) -I$(CORE) -dynamiclib -o $@ $(SRC) $(LDLIBS)

$(CLI): $(SRC) $(HDR)
	$(CC) $(OBJCFLAGS) $(TARGET) -I$(CORE) -DPOISE_CA_CLI -o $@ $(SRC) $(LDLIBS)

clean:
	rm -f $(OUT) $(CLI)

.PHONY: all dylib cli clean
