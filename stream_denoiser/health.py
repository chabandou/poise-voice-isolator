"""
Startup Health Checks and Audio Recovery (Linux)

Covers the known Linux issues from the README programmatically:

1. ONNX Runtime "cannot enable executable stack": some wheels ship the
   GNU_STACK ELF flag as RWE, which hardened loaders refuse. Detectable
   with a pure-Python ELF read; fixed with patchelf (explicit opt-in).
2. PortAudio "malloc(): invalid size" crash: distro PortAudio builds
   without PulseAudio support (or the JACK backend bug) segfault
   natively — uncatchable, so detect the risky setup up front and abort
   with the rebuild instructions instead of crashing.
3. Stuck on the Poise_Capture null sink after a crash: restore the real
   default sink and unload our null-sink module (no sudo needed).

All third-party imports are lazy so `--doctor` works on minimal installs.
"""
import glob
import os
import shutil
import struct
import subprocess
import sys
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .logging_config import get_logger

_logger = get_logger(__name__)

SKIP_HEALTH_ENV = "POISE_SKIP_HEALTH"

# Sink names we manage (current + legacy, pre-rename leftovers)
OWN_SINK_NAMES = ("Poise_Capture", "Denoiser_Capture")


@dataclass
class CheckResult:
    """Outcome of one health check."""
    name: str
    ok: bool
    detail: str
    fix: Optional[str] = None


def _run(cmd: List[str], timeout: int = 10) -> Tuple[bool, str, str]:
    """Run a command, capturing output. Never raises."""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return proc.returncode == 0, proc.stdout, proc.stderr
    except (OSError, subprocess.SubprocessError) as e:
        return False, "", str(e)


# ---------------------------------------------------------------------------
# Issue 1: ONNX Runtime executable-stack flag
# ---------------------------------------------------------------------------

def find_onnxruntime_so() -> Optional[str]:
    """Locate the ONNX Runtime native library without importing it."""
    try:
        import importlib.util
        spec = importlib.util.find_spec("onnxruntime")
    except (ImportError, ValueError):
        return None
    if spec is None or not spec.submodule_search_locations:
        return None
    base = spec.submodule_search_locations[0]
    candidates = sorted(glob.glob(os.path.join(
        base, "capi", "onnxruntime_pybind11_state*.so")))
    if not candidates:
        return None
    # Prefer the unversioned .so when several match
    for path in candidates:
        if path.endswith("onnxruntime_pybind11_state.so"):
            return path
    return candidates[0]


def gnu_stack_flags(so_path: str) -> Optional[Tuple[bool, bool, bool]]:
    """
    Read the PT_GNU_STACK segment flags as (readable, writable, executable).

    Returns None when the file is not parseable or has no GNU_STACK segment
    (absence means a non-executable stack on modern toolchains: healthy).
    """
    try:
        with open(so_path, "rb") as f:
            magic = f.read(4)
            if magic != b"\x7fELF":
                return None
            f.seek(4)
            ei_class, ei_data = f.read(1)[0], f.read(1)[0]
            is64 = ei_class == 2
            endian = "<" if ei_data == 1 else ">"
            if is64:
                f.seek(0x20)
                phoff = struct.unpack(endian + "Q", f.read(8))[0]
                f.seek(0x36)
                phentsize = struct.unpack(endian + "H", f.read(2))[0]
                phnum = struct.unpack(endian + "H", f.read(2))[0]
                fmt, size = endian + "II", 8
            else:
                f.seek(0x1C)
                phoff = struct.unpack(endian + "I", f.read(4))[0]
                f.seek(0x2A)
                phentsize = struct.unpack(endian + "H", f.read(2))[0]
                phnum = struct.unpack(endian + "H", f.read(2))[0]
                fmt, size = endian + "II", 8
            for i in range(phnum):
                f.seek(phoff + i * phentsize)
                ptype, pflags = struct.unpack(fmt, f.read(size))
                if ptype == 0x6474E551:  # PT_GNU_STACK
                    return (
                        bool(pflags & 4),
                        bool(pflags & 2),
                        bool(pflags & 1),
                    )
            return None
    except OSError as e:
        _logger.debug(f"ELF read failed for {so_path}: {e}")
        return None


def check_execstack() -> CheckResult:
    """Check the ONNX Runtime library for the RWE executable-stack flag."""
    so_path = find_onnxruntime_so()
    if so_path is None:
        return CheckResult(
            name="onnxruntime execstack",
            ok=True,
            detail="onnxruntime not installed — nothing to check",
        )
    flags = gnu_stack_flags(so_path)
    if flags is None:
        return CheckResult(
            name="onnxruntime execstack",
            ok=True,
            detail=f"no GNU_STACK segment in {so_path} (non-executable stack)",
        )
    readable, writable, executable = flags
    if writable and executable:
        fix = f"patchelf --clear-execstack {so_path}"
        return CheckResult(
            name="onnxruntime execstack",
            ok=False,
            detail=(f"{so_path} has GNU_STACK RWE — the loader will refuse "
                    f"it ('cannot enable executable stack')."),
            fix=(f"Run: python -m stream_denoiser --fix-execstack\n"
                 f"  (or manually: {fix})"),
        )
    return CheckResult(
        name="onnxruntime execstack",
        ok=True,
        detail=(f"{so_path} GNU_STACK "
                f"{'R' if readable else ''}{'W' if writable else ''}"
                f"{'X' if executable else ''} — clean"),
    )


def apply_execstack_fix() -> Tuple[bool, str]:
    """
    Clear the executable-stack flag with patchelf (explicit opt-in only).

    Returns (success, message).
    """
    so_path = find_onnxruntime_so()
    if so_path is None:
        return True, "onnxruntime not installed — nothing to fix."
    flags = gnu_stack_flags(so_path)
    if flags is not None and not (flags[1] and flags[2]):
        return True, f"Already clean: {so_path}"
    tool = shutil.which("patchelf") or shutil.which("execstack")
    if tool is None:
        return False, (
            "Neither patchelf nor execstack is installed.\n"
            "  Arch:   sudo pacman -S patchelf\n"
            "  Debian/Ubuntu: sudo apt install patchelf\n"
            f"Then run: patchelf --clear-execstack {so_path}"
        )
    if not os.access(so_path, os.W_OK):
        return False, (
            f"No write permission for {so_path}.\n"
            f"Re-run with write access (e.g. sudo) to apply: "
            f"patchelf --clear-execstack {so_path}"
        )
    ok, _, err = _run(["patchelf", "--clear-execstack", so_path])
    if not ok:
        return False, f"patchelf failed: {err.strip()}"
    flags = gnu_stack_flags(so_path)
    if flags is not None and (flags[1] and flags[2]):
        return False, "Flag still set after patchelf — see README manual steps."
    return True, f"Fixed: executable-stack flag cleared on {so_path}"


# ---------------------------------------------------------------------------
# Issue 2: PortAudio without PulseAudio support (native crash)
# ---------------------------------------------------------------------------

def pulse_server_present() -> bool:
    """Best-effort check that a PulseAudio/PipeWire server is reachable."""
    if os.environ.get("PULSE_SERVER"):
        return True
    try:
        from .backends.platform.linux import USE_PULSECTL
        if USE_PULSECTL:
            import pulsectl
            try:
                with pulsectl.Pulse("poise-health-check"):
                    return True
            except Exception:
                pass
    except ImportError:
        pass
    if shutil.which("pactl"):
        ok, _, _ = _run(["pactl", "info"])
        if ok:
            return True
    return False


def check_portaudio() -> CheckResult:
    """Detect the PortAudio setup known to segfault (no PulseAudio backend)."""
    try:
        from .backend_detection import (
            USE_SOUNDDEVICE, sd, SOUNDDEVICE_ERROR, SOUNDDEVICE_INSTALL_HINT,
        )
    except ImportError as e:
        return CheckResult(
            name="portaudio", ok=False,
            detail=f"backend detection unavailable: {e}",
        )
    if not USE_SOUNDDEVICE or sd is None:
        fix = "pip install sounddevice (needs PortAudio)."
        if SOUNDDEVICE_ERROR:
            fix += f" Import error was: {SOUNDDEVICE_ERROR}"
        if SOUNDDEVICE_INSTALL_HINT:
            fix += f" {SOUNDDEVICE_INSTALL_HINT}"
        return CheckResult(
            name="portaudio", ok=False,
            detail="sounddevice/PortAudio unavailable.", fix=fix,
        )
    try:
        apis = sorted({
            sd.query_hostapis(d["hostapi"])["name"]
            for d in sd.query_devices()
        })
    except Exception as e:
        return CheckResult(
            name="portaudio", ok=False,
            detail=f"could not query PortAudio host APIs: {e}",
        )
    has_pulse = any("pulse" in a.lower() for a in apis)
    has_jack = any("jack" in a.lower() for a in apis)
    detail = f"PortAudio host APIs: {', '.join(apis)}"
    if sys.platform.startswith("linux") and pulse_server_present() and not has_pulse:
        return CheckResult(
            name="portaudio",
            ok=False,
            detail=(detail + " — a PulseAudio server is running but this "
                    "PortAudio build has no PulseAudio backend (known "
                    "native-crash setup)."),
            fix=("Rebuild PortAudio with PulseAudio (see README 'Linux "
                 "Troubleshooting'), then: pip install sounddevice "
                 "--no-cache-dir, with LD_LIBRARY_PATH=/usr/local/lib. "
                 "Bypass (ALSA-direct, may work): "
                 f"{SKIP_HEALTH_ENV}=1"),
        )
    if has_jack:
        detail += " (JACK present — poise avoids it automatically)"
    return CheckResult(name="portaudio", ok=True, detail=detail)


# ---------------------------------------------------------------------------
# Issue 3: Stuck on our null sink after a crash
# ---------------------------------------------------------------------------

def _pactl_available() -> bool:
    return shutil.which("pactl") is not None


def _list_sink_names() -> List[str]:
    """All sink names via pulsectl, falling back to pactl."""
    try:
        from .backends.platform.linux import list_pulseaudio_sinks
        sinks = list_pulseaudio_sinks()
        if sinks:
            return [s.name for s in sinks]
    except Exception as e:
        _logger.debug(f"pulsectl sink list failed: {e}")
    if _pactl_available():
        ok, out, _ = _run(["pactl", "list", "sinks", "short"])
        if ok:
            names = []
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    names.append(parts[1])
            return names
    return []


def reset_audio() -> Tuple[bool, str]:
    """
    Restore a real default sink and unload our null-sink module(s).

    Replaces the README's manual pactl steps. Returns (success, message).
    """
    if not sys.platform.startswith("linux"):
        return False, "Audio reset is only supported on Linux."
    if not _pactl_available():
        return False, (
            "pactl not found — install it (Arch: sudo pacman -S libpulse, "
            "Debian/Ubuntu: sudo apt install pulseaudio-utils) and retry, "
            "or follow the README manual steps."
        )
    sinks = _list_sink_names()
    own = [s for s in sinks if s in OWN_SINK_NAMES]
    real = [s for s in sinks
            if s not in OWN_SINK_NAMES and "null" not in s.lower()
            and not s.endswith(".monitor")]

    messages = []
    ok_overall = True

    # 1. Point the default sink at real hardware (if we own any sink)
    ok, out, _ = _run(["pactl", "get-default-sink"])
    default_sink = out.strip() if ok else ""
    if default_sink in OWN_SINK_NAMES or not default_sink:
        if real:
            ok, _, err = _run(["pactl", "set-default-sink", real[0]])
            if ok:
                messages.append(f"Default sink restored to {real[0]}.")
            else:
                ok_overall = False
                messages.append(f"Could not set default sink: {err.strip()}")
        else:
            ok_overall = False
            messages.append("No real (non-virtual) sink found to restore.")
    else:
        messages.append(f"Default sink already real ({default_sink}).")

    # 2. Unload null-sink modules backing our sinks
    ok, out, _ = _run(["pactl", "list", "modules", "short"])
    unloaded = 0
    if ok:
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "module-null-sink" \
                    and any(own_name in line for own_name in OWN_SINK_NAMES):
                mod_id = parts[0]
                ok_un, _, err = _run(["pactl", "unload-module", mod_id])
                if ok_un:
                    unloaded += 1
                else:
                    ok_overall = False
                    messages.append(
                        f"Could not unload module {mod_id}: {err.strip()}")
    if unloaded:
        messages.append(f"Unloaded {unloaded} Poise null-sink module(s).")
    elif own:
        messages.append("Our sink exists but no matching module found "
                        "(it may be a static PipeWire node — remove it in "
                        "pavucontrol/helvum).")
    else:
        messages.append("No leftover Poise sink found — nothing to unload.")

    return ok_overall, " ".join(messages)


# ---------------------------------------------------------------------------
# Doctor entry point
# ---------------------------------------------------------------------------

def run_doctor() -> Tuple[bool, List[CheckResult]]:
    """Run all startup checks. Returns (all_ok, results)."""
    results = [check_execstack(), check_portaudio()]
    return all(r.ok for r in results), results


def format_doctor(results: List[CheckResult]) -> str:
    """Render doctor results for the terminal."""
    lines = []
    for r in results:
        mark = "ok" if r.ok else "FAIL"
        lines.append(f"[{mark}] {r.name}: {r.detail}")
        if not r.ok and r.fix:
            for fix_line in r.fix.splitlines():
                lines.append(f"       {fix_line}")
    return "\n".join(lines)
