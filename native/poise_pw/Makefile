# Builds libpoise_pw.so, the in-graph PipeWire node (see poise_pw.c).
# Needs a C compiler and the libpipewire-0.3 development headers.
#
#   make -C native/poise_pw            # -> stream_denoiser/native/libpoise_pw.so

OUT ?= ../../stream_denoiser/native/libpoise_pw.so
CFLAGS ?= -O2 -g
CFLAGS += -std=gnu11 -fPIC -Wall -Wextra -Wno-unused-parameter
PKG_CONFIG ?= pkg-config
PW_CFLAGS := $(shell $(PKG_CONFIG) --cflags libpipewire-0.3)
PW_LIBS := $(shell $(PKG_CONFIG) --libs libpipewire-0.3)

# The fixed-delay core, shared with the Windows path (native/poise_wasapi).
CORE := ../core
SRC := $(CORE)/poise_core.c poise_pw.c
HDR := $(CORE)/poise_core.h

$(OUT): $(SRC) $(HDR)
	$(CC) $(CFLAGS) -I$(CORE) $(PW_CFLAGS) -shared -o $@ $(SRC) $(PW_LIBS) -lpthread $(LDFLAGS)

clean:
	rm -f $(OUT)

.PHONY: clean
