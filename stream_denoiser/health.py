"""
Startup Health Checks and Audio Recovery (Linux, macOS)

Covers the known Linux issues programmatically:

1. ONNX Runtime "cannot enable executable stack": some wheels ship the
   GNU_STACK ELF flag as RWE, which hardened loaders refuse. Detectable
   with a pure-Python ELF read; fixed with patchelf (explicit opt-in).
2. PulseAudio backend unavailable: libpulse-simple missing or no
   Pulse-compatible server reachable (PulseAudio, or PipeWire with
   pipewire-pulse).
3. Stuck on the Poise_Capture null sink after a crash: restore the real
   default sink and unload our null-sink module (no sudo needed).

And the macOS ones (plan C2b, C1), where both failure modes are silent:

1. A denied or absent System Audio Recording grant: the tap captures
   digital silence, or no IOProc callback arrives at all, and the audio
   API reports no error. The doctor opens the tap for a second and
   compares what it captured with whether the output device was playing.
2. A tap that outlived the process that owned it: it keeps the apps it
   read muted, so the whole Mac is silent. The doctor lists the HAL
   devices and says whether a Poise aggregate is still registered.

All third-party imports are lazy so `--doctor` works on minimal installs.
"""
import glob
import os
import platform
import shutil
import struct
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .constants import PW_NODE_NAME
from .logging_config import get_log_file_path, get_logger

_logger = get_logger(__name__)

SKIP_HEALTH_ENV = "POISE_SKIP_HEALTH"

# Sink names we manage (PipeWire node, null sink, pre-rename leftovers)
OWN_SINK_NAMES = (PW_NODE_NAME, "Poise_Capture", "Denoiser_Capture")


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
# Issue 2: PulseAudio backend (libpulse-simple + server reachable)
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


def check_pulse_backend() -> CheckResult:
    """Check libpulse-simple loads and the Pulse server is reachable."""
    try:
        from .backends.pulse_simple import _load_library
    except ImportError as e:
        return CheckResult(
            name="pulse-simple", ok=False,
            detail=f"pulse-simple backend unavailable: {e}",
        )
    try:
        _load_library()
    except Exception as e:
        return CheckResult(
            name="pulse-simple", ok=False,
            detail=f"libpulse-simple could not be loaded: {e}",
            fix=("Install libpulse. Arch: sudo pacman -S libpulse. "
                 "Debian/Ubuntu: sudo apt install libpulse0."),
        )
    try:
        from .backends.platform.linux import get_pulse_server_info
        server_name, server_version = get_pulse_server_info()
    except Exception as e:
        return CheckResult(
            name="pulse-simple", ok=False,
            detail=f"could not query PulseAudio server: {e}",
        )
    if not server_name and not pulse_server_present():
        return CheckResult(
            name="pulse-simple", ok=False,
            detail=("libpulse-simple loads, but no Pulse-compatible server "
                    "is reachable (need PulseAudio, or PipeWire with "
                    "pipewire-pulse)."),
            fix=("Start PulseAudio/PipeWire, then retry. Bypass: "
                 f"{SKIP_HEALTH_ENV}=1"),
        )
    detail = (f"libpulse-simple OK; server: {server_name or '?'} "
              f"({server_version or '?'})")
    return CheckResult(name="pulse-simple", ok=True, detail=detail)


def check_pipewire_node() -> CheckResult:
    """Report whether the PipeWire node backend can run (never fails:
    without it Poise uses pulse-simple)."""
    try:
        from .backends.pipewire_backend import pipewire_node_status
        ok, detail = pipewire_node_status()
    except Exception as e:
        ok, detail = False, str(e)
    if ok:
        return CheckResult(name="pipewire-node", ok=True,
                           detail=f"in-graph node available ({detail})")
    return CheckResult(name="pipewire-node", ok=True,
                       detail=f"not used, falling back to pulse-simple: {detail}")


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

    Replaces the README's manual pactl steps on Linux; macOS has nothing a
    second process can reset (see _reset_macos_audio). Returns
    (success, message).
    """
    if sys.platform == "darwin":
        return _reset_macos_audio()
    if not sys.platform.startswith("linux"):
        return False, "Audio reset is only supported on Linux and macOS."
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
# macOS: the Core Audio tap (plans C1, C2b)
# ---------------------------------------------------------------------------

# How long the capture probe listens, and how long --doctor lets it.
# poise_ca_new waits for the permission prompt (up to 3 minutes), so the probe
# runs on a thread that the report does not wait for indefinitely.
PROBE_SECONDS = 1.0
PROBE_TIMEOUT_SEC = 8.0


@dataclass
class _OutputState:
    """The default output device: its name, and whether it is playing."""

    name: str
    playing: Optional[bool]


def _grant_fix() -> str:
    """What a denied, stale or absent capture grant needs (plan C2b).

    Measured in T3: the toggle is in the pane's "System Audio Recording
    Only" section, and the grant is keyed to the code identity of the app
    that creates the tap — so a shell run answers under the terminal's
    identity, and a rebuild can invalidate a switch that reads ON.
    """
    return (
        "Open System Settings > Privacy & Security >\n"
        "Screen & System Audio Recording, and switch the app that runs\n"
        "Poise on in its \"System Audio Recording Only\" section. The grant\n"
        "belongs to that app: started from a shell, Poise runs under your\n"
        "terminal's identity (Terminal, iTerm, Ghostty, ...), so the\n"
        "terminal is what has to be listed. A switch that already reads ON\n"
        "can be stale, which is why re-arming it is the reliable sequence:\n"
        "  tccutil reset AudioCapture <bundle-id>   (no id: every app)\n"
        "then start Poise again and click Allow, not \"Allow once\".")


def _flush_c_streams() -> None:
    """Flush the C library's stdout buffer.

    The native node prints with printf, whose buffer is not Python's: it
    would otherwise be flushed later, after fd 1 points at the terminal
    again (i.e. out of order).
    """
    try:
        import ctypes

        ctypes.CDLL(None).fflush(None)
    except Exception:
        pass


@contextmanager
def _captured_stdio() -> Iterator[Optional[str]]:
    """Point fds 1 and 2 at a temp file for the duration; yields its path.

    ``poise_ca_new`` prints the device, the stream formats and the tap with
    printf, and reports advisory OSStatus values on stderr. Worth keeping
    (they go into the log), but not in the middle of --doctor's report.
    Yields None when this process's streams cannot be redirected (a captured
    stream under pytest, say); the probe then runs with that output where it
    would have gone anyway.
    """
    try:
        import tempfile

        fd, path = tempfile.mkstemp(prefix="poise-doctor-", suffix=".txt")
    except OSError:
        yield None
        return
    saved = {}
    try:
        sys.stdout.flush()
        sys.stderr.flush()
        for target in (1, 2):
            saved[target] = os.dup(target)
            os.dup2(fd, target)
    except OSError as e:
        _logger.debug("doctor: streams not redirected: %r", e)
        for target, copy in saved.items():
            try:
                os.dup2(copy, target)
                os.close(copy)
            except OSError:
                pass
        saved = {}
    finally:
        os.close(fd)
    try:
        yield path
    finally:
        if saved:
            _flush_c_streams()
            for stream in (sys.stdout, sys.stderr):
                try:
                    stream.flush()
                except Exception:
                    pass
            for target, copy in saved.items():
                try:
                    os.dup2(copy, target)
                finally:
                    os.close(copy)


def _log_captured_output(path: Optional[str]) -> None:
    """Log (and remove) what the native node printed during the probe."""
    if not path:
        return
    text = ""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read().strip()
    except OSError:
        pass
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    if text:
        _logger.info("doctor: the tap node's startup output:\n%s", text)


# kAudioDevicePropertyDeviceIsRunningSomewhere: 1 while any process runs the
# device, i.e. while something is being played.
_RUNNING_SOMEWHERE = int.from_bytes(b"gone", "big")


def _default_output_state() -> _OutputState:
    """The default output device's name and whether it is playing.

    ``playing`` is None when the HAL cannot be asked. The HAL binding is
    backends/platform/macos.py's (the same one --list-devices uses); this
    adds only the running-somewhere property, which the doctor needs to tell
    "a quiet Mac" from "capturing zeros while sound is playing".
    """
    from .backends.platform import macos as hal

    try:
        device = hal.default_output_device()
        if device is None:
            return _OutputState("the output device", None)
        ca, _cf = hal._core_audio()
        playing = bool(hal._u32(ca, device.id, _RUNNING_SOMEWHERE))
        return _OutputState(f'"{device.name}"', playing)
    except Exception as e:
        _logger.debug("doctor: cannot read the output device state: %r", e)
        return _OutputState("the output device", None)


def _probe_node(result: Dict[str, Any]) -> None:
    """Open the tap unmuted and silent for PROBE_SECONDS, then close it.

    Unmuted (``tap_mute=False``) because --doctor must not mute the Mac, and
    the playback leg at zero gain so the probe does not duplicate what is
    playing by the fixed delay. The node is closed on every route here: the
    tap only lives while a process holds it (plan C1).
    """
    from .backends.coreaudio_node import NODE_RATE, CoreAudioNode
    from .constants import (DEFAULT_FRAME_SIZE, MAC_FADE_SAMPLES,
                            MAC_MARGIN_SAMPLES, MAC_QUANTUM)

    node = None
    try:
        node = CoreAudioNode(output=None, frame=DEFAULT_FRAME_SIZE,
                             engine_latency=0, quantum=MAC_QUANTUM,
                             margin=MAC_MARGIN_SAMPLES,
                             fade=MAC_FADE_SAMPLES, dry_gain=0.0,
                             rate=NODE_RATE, tap_mute=False)
        time.sleep(PROBE_SECONDS)
        result["stats"] = node.node_stats()
        result["error"] = node.error()
    except BaseException as e:  # noqa: BLE001 - reported by check_macos_capture
        result["error"] = str(e) or type(e).__name__
    finally:
        if node is not None:
            try:
                node.close()
            except Exception:
                _logger.debug("doctor: closing the probe node failed",
                              exc_info=True)


def check_macos_version() -> CheckResult:
    """The running macOS against the 14.2 floor Core Audio taps need."""
    from .backends.platform.macos import (CORE_AUDIO_TAP_FLOOR,
                                          MacOSUnsupported, macos_version,
                                          require_core_audio_tap_support)

    floor = f"{CORE_AUDIO_TAP_FLOOR[0]}.{CORE_AUDIO_TAP_FLOOR[1]}"
    version = macos_version()
    try:
        require_core_audio_tap_support()
    except MacOSUnsupported as e:
        return CheckResult(
            name="macOS", ok=False, detail=str(e),
            fix=("Core Audio process taps arrived in macOS " + floor +
                 "; there is no other audio path on macOS."))
    machine = platform.machine()
    if machine != "arm64":
        return CheckResult(
            name="macOS", ok=False,
            detail=(f"macOS {version} on {machine}: Poise's macOS audio path "
                    "is Apple Silicon only (the engines ship arm64 macOS "
                    "wheels)."),
            fix="Run Poise on an Apple Silicon Mac (Intel Macs are untested "
                "and out of scope for this backend).")
    return CheckResult(
        name="macOS", ok=True,
        detail=(f"{version} ({machine}) — Core Audio process taps need "
                f"{floor} or newer"))


def check_core_audio_node() -> CheckResult:
    """Whether the native tap library is there and loads."""
    from .backends.coreaudio_node import (LIB_NAME, CoreAudioUnavailable,
                                          _candidate_paths, load_library)

    build = ("Build it: make -C native/poise_coreaudio\n"
             f"  (writes stream_denoiser/native/{LIB_NAME}; needs the Xcode "
             "command line tools)")
    try:
        load_library()
    except CoreAudioUnavailable as e:
        return CheckResult(name="core-audio-node", ok=False,
                           detail=f"the native tap library is not usable: {e}",
                           fix=build)
    found = [p for p in _candidate_paths() if os.path.exists(p)]
    return CheckResult(
        name="core-audio-node", ok=True,
        detail=f"{LIB_NAME} loads ({found[0] if found else 'from the package'})")


# The one native error that is ambiguous: AudioDeviceStart succeeds and no
# IOProc callback ever arrives. A denied grant looks like this, and so does an
# output device that nothing is playing through (the HAL then has no reason to
# run the aggregate). The doctor needs the output device's own state to tell
# the two apart (poise_ca_new's wording is native/poise_coreaudio, frozen).
_NO_CALLBACK_HINT = "no IOProc callback arrived"


def check_macos_capture() -> CheckResult:
    """What the tap is delivering right now (plan C2b).

    Three answers matter, and only the first is good news: the tap is
    delivering sound; it is capturing zeros while the output device is
    playing (a denied or stale System Audio Recording grant); or no IOProc
    callback arrives at all (the same grant, seen from the other side — the
    native node refuses to report that as a working capture). An idle Mac
    produces the last two symptoms as well, so the output device is asked
    whether it was playing anything before the answer is called a failure.
    """
    from .backends.coreaudio_backend import capture_state

    output = _default_output_state()
    result: Dict[str, Any] = {}
    thread = threading.Thread(target=_probe_node, args=(result,),
                              name="poise-doctor-probe", daemon=True)
    with _captured_stdio() as captured:
        thread.start()
        thread.join(PROBE_TIMEOUT_SEC)
    _log_captured_output(captured)

    if thread.is_alive():
        return CheckResult(
            name="capture", ok=False,
            detail=(f"the tap did not finish opening within "
                    f"{PROBE_TIMEOUT_SEC:.0f} s. The native node waits for the "
                    "System Audio Recording prompt (up to 3 minutes), so an "
                    "unanswered permission request looks exactly like this."),
            fix=_grant_fix())

    stats = result.get("stats")
    if not stats:
        error = str(result.get("error") or "unknown error")
        if _NO_CALLBACK_HINT in error:
            if output.playing:
                return CheckResult(
                    name="capture", ok=False,
                    detail=(f"no IOProc callback arrived while {output.name} "
                            "was playing. The aggregate starts and the HAL "
                            "never runs it: a denied or stale System Audio "
                            "Recording grant looks exactly like this and "
                            "raises no error"),
                    fix=_grant_fix())
            return CheckResult(
                name="capture", ok=True,
                detail=(f"no IOProc callback arrived, and nothing was playing "
                        f"through {output.name}: the HAL does not run the "
                        "aggregate for a silent Mac, so this says nothing "
                        "about the grant yet. Play something (music, a "
                        "video) and run --doctor again"),
                fix=("Sound on the tap next time means the grant is fine.\n" +
                     _grant_fix()))
        return CheckResult(
            name="capture", ok=False,
            detail=f"the tap could not be opened: {error}",
            fix=_grant_fix())

    state = capture_state(stats)
    frames = stats["input_frames"]
    if state == "signal":
        return CheckResult(
            name="capture", ok=True,
            detail=(f"the tap is delivering sound: {frames} frames in "
                    f"{PROBE_SECONDS:.0f} s, {stats['quiet_frames']} of them "
                    "below the silence floor (saw_signal=1)"))

    heard = ("no audio frames at all" if state == "no-audio"
             else f"{frames} frames, every one below the silence floor")
    if output.playing:
        return CheckResult(
            name="capture", ok=False,
            detail=(f"the tap is capturing zeros while {output.name} is "
                    f"playing ({heard}). A denied or stale System Audio "
                    "Recording grant looks exactly like this and raises no "
                    "error at all"),
            fix=_grant_fix())
    if output.playing is None:
        return CheckResult(
            name="capture", ok=True,
            detail=(f"the tap delivered silence ({heard}) and the HAL could "
                    "not say whether the output device was playing, so this "
                    "is inconclusive: play something and run --doctor again"),
            fix=("Sound on the tap next time means the grant is fine.\n" +
                 _grant_fix()))
    return CheckResult(
        name="capture", ok=True,
        detail=(f"the tap delivered silence ({heard}) and nothing was "
                f"playing through {output.name}, so there was nothing to "
                "hear. Play something (music, a video) and run --doctor "
                "again to check the grant"))


def check_macos_taps() -> CheckResult:
    """Whether a Poise tap or aggregate is still registered in the HAL.

    A tap whose owner died keeps the apps it read muted, so the whole Mac
    stays silent until the audio daemon drops it (plan C1's risk R2).
    """
    from .backends.platform.macos import list_core_audio_devices

    try:
        devices = list_core_audio_devices()
    except Exception as e:
        return CheckResult(
            name="tap/aggregate", ok=False,
            detail=f"cannot enumerate the Core Audio devices: {e}")
    strays = [d for d in devices
              if d.name.startswith("Poise") or d.uid.startswith("dev.poise.")]
    recovery = (
        "Quit Poise: its exit routes destroy the tap, which is what unmutes "
        "the Mac.\n"
        "If no Poise is running and the Mac is still silent, restart the "
        "audio daemon:\n"
        "  sudo killall coreaudiod\n"
        "(it starts again at once; every stale tap and aggregate goes with "
        "it and audio comes back)")
    if strays:
        listed = ", ".join(f'{d.name} ({d.uid})' for d in strays)
        return CheckResult(
            name="tap/aggregate", ok=False,
            detail=(f"a Poise aggregate is still registered: {listed}. Its "
                    "owner is running (normal while Poise runs) or died "
                    "without destroying it (the Mac stays muted then)"),
            fix=recovery)
    return CheckResult(
        name="tap/aggregate", ok=True,
        detail=("no Poise tap or aggregate is registered, so nothing of "
                "Poise's is left in the HAL. (A private aggregate is listed "
                "only for the process that owns it, so a tap leaked by a "
                "dead process shows up as a silent Mac, not as a device "
                "here.)\n"
                "If the Mac is silent with no Poise running: sudo killall "
                "coreaudiod"))


def check_macos_log() -> CheckResult:
    """The file log the doctor has just written to."""
    path = get_log_file_path()
    if not path:
        return CheckResult(
            name="log", ok=False,
            detail="no file log is being written (--no-file-log?)",
            fix=("Run without --no-file-log (and without "
                 "POISE_DISABLE_FILE_LOG=1); POISE_LOG_FILE=<path> puts it "
                 "somewhere specific."))
    return CheckResult(name="log", ok=True,
                       detail=f"{path} (this report is in it)")


def run_macos_doctor() -> Tuple[bool, List[CheckResult]]:
    """The macOS checks. Returns (all_ok, results).

    The Linux checks next to this one ask about PulseAudio and PipeWire, so
    they are not run here at all — there is nothing on a Mac for them to
    find, and their fixes do not apply.
    """
    node = check_core_audio_node()
    results = [check_macos_version(), node]
    if node.ok:
        results.append(check_macos_capture())
    else:
        results.append(CheckResult(
            name="capture", ok=False,
            detail="not probed: the native tap library is not usable (see "
                   "core-audio-node)"))
    results += [check_macos_taps(), check_macos_log()]
    return all(r.ok for r in results), results


def _reset_macos_audio() -> Tuple[bool, str]:
    """macOS's --reset-audio: say what cannot be done, and what works.

    A Core Audio process tap and its private aggregate belong to the process
    that created them; there is no HAL call with which another process can
    destroy them. So the honest answer names the two things that do work,
    instead of the Linux pactl steps.
    """
    ok = True
    lines = [
        "Poise cannot dismantle another process's Core Audio tap: the tap "
        "and\nits private aggregate are destroyed by the process that "
        "created them,\nand no HAL call lets this process do it from outside.",
    ]
    try:
        from .backends.platform.macos import list_core_audio_devices

        strays = [d for d in list_core_audio_devices()
                  if d.name.startswith("Poise")
                  or d.uid.startswith("dev.poise.")]
    except Exception as e:
        strays = []
        lines.append(f"(the HAL could not be asked: {e})")
    if strays:
        ok = False
        lines.append(
            "A Poise aggregate is registered right now: "
            + ", ".join(f'{d.name} ({d.uid})' for d in strays) + ".")
    else:
        lines.append("No Poise aggregate is registered right now, so another\n"
                     "Poise is probably not why audio is missing.")
    lines += [
        "What restores audio, in order:",
        "  1. Quit Poise (the TUI ends its audio process on quit too): its "
        "exit\n     routes destroy the tap, and destroying the tap unmutes "
        "the Mac.",
        "  2. Still silent: sudo killall coreaudiod — the audio daemon "
        "restarts\n     immediately and drops every tap and aggregate whose "
        "owner is gone.",
        "  3. If Poise then captures nothing, the grant may be denied or "
        "stale:",
    ]
    lines += ["     " + line for line in _grant_fix().splitlines()]
    return ok, "\n".join(lines)


# ---------------------------------------------------------------------------
# Doctor entry point
# ---------------------------------------------------------------------------

def run_doctor() -> Tuple[bool, List[CheckResult]]:
    """Run the Linux startup checks. Returns (all_ok, results).

    macOS has its own set (run_macos_doctor): different failure modes, and
    advice that does not mention pactl. The two are kept apart because the
    checks are platform-specific by construction (tests/test_health.py also
    pins this list), and cli.py picks one by platform.
    """
    results = [check_execstack(), check_pulse_backend(),
               check_pipewire_node()]
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
