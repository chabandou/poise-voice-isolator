#!/usr/bin/env python3
"""Write the frozen probe's PyInstaller spec from poise_windows.spec.

The probe (tools/frozen_probe.py) must freeze exactly what Poise.exe
freezes, so its spec is the app's with three edits: the entry script,
the executable's name, and SPECPATH pinned to the repository (the spec
finds tools/ through it, and this one is written elsewhere). Each edit
must match where expected: a spec that moved on fails here instead of
building something else.

Usage (from the repository root, as for poise_windows.spec):
    python tools/make_probe_spec.py [out.spec]   # default build/probe/PoiseProbe.spec
    pyinstaller build/probe/PoiseProbe.spec --noconfirm --distpath build/probe/dist --workpath build/probe/work
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_SPEC = ROOT / "poise_windows.spec"
PROBE = ROOT / "tools" / "frozen_probe.py"
DEFAULT_OUT = ROOT / "build" / "probe" / "PoiseProbe.spec"

# (old, new, how many times old must appear)
EDITS = (
    ("['run_poise_gui.py']", f"[{str(PROBE)!r}]", 1),
    ("name='Poise',", "name='PoiseProbe',", 2),        # EXE and COLLECT
    ("SPECPATH", repr(str(ROOT)), None),               # at least once
)


def probe_spec(text: str) -> str:
    for old, new, count in EDITS:
        found = text.count(old)
        if (count is None and found == 0) or (count is not None
                                              and found != count):
            want = "at least 1" if count is None else count
            raise SystemExit(f"{APP_SPEC.name}: {old!r} appears {found} "
                             f"times, expected {want}; update {__file__}")
        text = text.replace(old, new)
    return text


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(probe_spec(APP_SPEC.read_text(encoding="utf-8")),
                   encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
