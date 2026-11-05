#!/bin/sh
# Runs every mode of both builds, one mode per invocation, under a watchdog
# (BSD/macOS has no timeout(1); perl's alarm does the same job), and keeps the
# output in runs/<build>.log.  This is what measurements/mac-wake.md quotes.
#
#   ./run_all.sh              # both builds, modes p1..p5
#   WATCHDOG=300 ./run_all.sh # longer per-mode limit
set -u
cd "$(dirname "$0")" || exit 1
mkdir -p runs
WATCHDOG=${WATCHDOG:-180}

for build in mach condvar; do
	: > "runs/$build.log"
	for mode in p1 p2 p3 p4 p5; do
		printf '=== %s %s ===\n' "$build" "$mode" | tee -a "runs/$build.log"
		perl -e 'alarm shift; exec @ARGV' "$WATCHDOG" \
			"./build/wake_probe_$build" --mode "$mode" 2>&1 |
			tee -a "runs/$build.log"
		printf 'exit=%d\n' "$?" | tee -a "runs/$build.log"
	done
done
