# Builds wake_probe twice from one source, so the two wake primitives are
# otherwise identical binaries (see wake_probe.c and measurements/mac-wake.md):
#
#   build/wake_probe_mach      -DUSE_MACH_SEM   (the Mach-semaphore choice)
#   build/wake_probe_condvar   -DUSE_CONDVAR    (the alternative)
#
# Measurement tool, not shipped. No audio device, no permissions, no network.
#
#   make -C native/poise_coreaudio/wakeprobe
#   ./native/poise_coreaudio/wakeprobe/build/wake_probe_mach --mode p2
#
# Binaries land in build/ (gitignored).

CC ?= clang
ifeq ($(origin CC),default)
CC = clang
endif
CFLAGS ?= -O2 -g
CFLAGS += -std=gnu11 -Wall -Wextra -Wno-unused-parameter
LDFLAGS += -lpthread

OUTDIR := build
BINS := $(OUTDIR)/wake_probe_mach $(OUTDIR)/wake_probe_condvar

all: $(BINS)

$(OUTDIR)/wake_probe_mach: wake_probe.c | $(OUTDIR)
	$(CC) $(CFLAGS) -DUSE_MACH_SEM -o $@ wake_probe.c $(LDFLAGS)

$(OUTDIR)/wake_probe_condvar: wake_probe.c | $(OUTDIR)
	$(CC) $(CFLAGS) -DUSE_CONDVAR -o $@ wake_probe.c $(LDFLAGS)

$(OUTDIR):
	mkdir -p $(OUTDIR)

clean:
	rm -rf $(OUTDIR)

.PHONY: all clean
