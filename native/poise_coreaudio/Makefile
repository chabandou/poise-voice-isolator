# Builds the Poise Core Audio tap spike (native/poise_coreaudio/poise_coreaudio.m).
#
#   make -C native/poise_coreaudio            # -> ./poise_coreaudio
#   make -C native/poise_coreaudio clean
#
# The binary is not the shipping artifact: T4 turns this into
# libpoise_coreaudio.dylib (built, never committed; see plan T4). The spike has
# to be run from the dev bundle instead of as a bare CLI, because TCC attributes
# the System Audio Recording grant to the bundle:
#
#   tools/make_dev_app.sh && open -n -W build/PoiseDev.app --args --seconds 5 ...
#
# Core Audio itself needs no other framework; AudioToolbox is used for the
# format names in the probe report, Foundation for CATapDescription.

SDK ?= $(shell xcrun --sdk macosx --show-sdk-path 2>/dev/null)
# The tap API is macOS 14.2; set the deployment target from that, not from the
# Xcode default, so the built binary actually claims the API it uses.
MIN_MACOS ?= 14.2

CC ?= clang
OBJCFLAGS ?= -O2 -g
OBJCFLAGS += -std=gnu11 -Wall -Wextra -Wno-unused-parameter -fobjc-arc
LDLIBS := -framework CoreAudio -framework AudioToolbox -framework Foundation
OUT ?= poise_coreaudio

SRC := poise_coreaudio.m
HDR := poise_coreaudio.h

# Guard ARM64/Intel: the plan targets Apple Silicon; x86_64 is untested (R8), so
# build for the host arch rather than a universal binary.
ARCH ?= $(shell uname -m)
SYSROOT := $(if $(SDK),-isysroot $(SDK),)
TARGET := -mmacosx-version-min=$(MIN_MACOS) -arch $(ARCH) $(SYSROOT)

all: $(OUT)

$(OUT): $(SRC) $(HDR)
	$(CC) $(OBJCFLAGS) $(TARGET) -o $@ $(SRC) $(LDLIBS)

clean:
	rm -f $(OUT)

.PHONY: all clean
