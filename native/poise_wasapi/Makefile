# Builds poise_wasapi.dll, Poise's native audio path on Windows (see
# poise_wasapi.c). Cross-compiles with mingw-w64 (Linux), like
# rnnoise.dll; any mingw-w64 toolchain works, e.g. on Windows itself:
#
#   make -C native/poise_wasapi     # -> stream_denoiser/native/poise_wasapi.dll
#   make -C native/poise_wasapi CC="zig cc -target x86_64-windows-gnu" STATIC=
#
# Only system DLLs are needed at runtime (kernel32, ole32, the C runtime;
# avrt is loaded on demand).

OUT ?= ../../stream_denoiser/native/poise_wasapi.dll
ifeq ($(origin CC),default)
CC = x86_64-w64-mingw32-gcc
endif
CFLAGS ?= -O2
CFLAGS += -std=gnu11 -Wall -Wextra -Wno-unused-parameter
# No libgcc DLL next to Poise.exe.
STATIC ?= -static-libgcc

# The fixed-delay core, shared with the PipeWire node (native/poise_pw).
CORE := ../core
SRC := poise_wasapi.c $(CORE)/poise_core.c
HDR := poise_wasapi.h $(CORE)/poise_core.h

$(OUT): $(SRC) $(HDR)
	$(CC) $(CFLAGS) -I$(CORE) -shared -o $@ $(SRC) -lole32 $(STATIC) $(LDFLAGS)

clean:
	rm -f $(OUT)

.PHONY: clean
