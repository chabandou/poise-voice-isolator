# Builds latmeter.exe, a measurement tool (not shipped): it plays into
# CABLE Input and records CABLE Input, the speakers and CABLE Output with
# their QPC times; tools/win_latency.py drives it. Same toolchains as
# poise_wasapi, e.g. on Windows itself:
#
#   make -C native/latmeter CC="zig cc -target x86_64-windows-gnu" STATIC=

OUT ?= ../../build/latmeter.exe
ifeq ($(origin CC),default)
CC = x86_64-w64-mingw32-gcc
endif
CFLAGS ?= -O2
CFLAGS += -std=gnu11 -Wall -Wextra -Wno-unused-parameter
STATIC ?= -static-libgcc

$(OUT): latmeter.c
	mkdir -p $(dir $(OUT))
	$(CC) $(CFLAGS) -o $@ latmeter.c -lole32 -lavrt -lwinmm $(STATIC) $(LDFLAGS)

clean:
	rm -f $(OUT)

.PHONY: clean
