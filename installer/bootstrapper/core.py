"""
Poise Setup - the Qt-free half of the engine.

Install plan, the command line handed to the hidden Inno core, and the
parsing of that core's log. Standard library only, so the installer's
decisions are testable where PyQt6 is not installed (the project's CI
runs Qt-free) and so the setup window's logic can be reasoned about
without a screen.

The contract with setup.iss is deliberately narrow: the script logs
`POISE:phase=<name>` and `POISE:driver=<event>` lines (see [Code]), and
nothing here reads Inno's own log format.
"""
from __future__ import annotations

import codecs
import ntpath
import os
import sys
from dataclasses import dataclass

CORE_NAME = "PoiseCore.exe"
APP_EXE = "Poise.exe"
APP_NAME = "Poise Voice Isolator"

#: Inno's uninstall key for setup.iss's AppId ("{GUID}_is1").
UNINSTALL_KEY = r"{D37E2F8B-563C-4D2A-B96E-6F8FA7D3F6A7}_is1"
_UNINSTALL_ROOT = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
_MMDEVICES_RENDER = (
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render")
#: Device friendly-name property, as probed by setup.iss.
_DEVICE_NAME_PROP = r"{a45c254e-df1c-4efd-8020-67d146a850e0},2"

MARKER = "POISE:"

#: Inno's silent-run exit codes (Setup Help: "Setup exit codes").
_OK = 0
_REBOOT_CODES = (3010, 1641)      # installed, reboot needed / reboot started
_CANCELLED_CODES = (2, 5, 6)      # wizard cancel, install cancel, abort

OK = "ok"
REBOOT = "reboot"
CANCELLED = "cancelled"
FAILED = "failed"

#: Phases the core announces, in order.
PHASES = ("prepare", "files", "driver", "finish")
PHASE_ORDER = {name: index for index, name in enumerate(PHASES)}

#: Driver events on the audio step.
DRIVER_EVENTS = ("install", "skip", "done", "reboot", "failed")


@dataclass
class InstallPlan:
    """Everything one silent core run needs."""

    target_dir: str
    desktop_icon: bool = True
    log_path: str = ""
    core_path: str = ""


@dataclass
class Existing:
    """A Poise already registered in Add/Remove Programs."""

    version: str = ""
    location: str = ""


def default_dir() -> str:
    """{autopf}\\Poise Voice Isolator, as the core resolves it.

    setup.iss runs Inno in 32-bit mode (no ArchitecturesInstallIn64BitMode),
    where {autopf} is Program Files (x86) on 64-bit Windows. This window is
    64-bit Python, whose %ProgramFiles% is the 64-bit folder, so it asks
    for the x86 one first to keep installs where the plain installer put
    them.
    """
    base = (os.environ.get("ProgramFiles(x86)")
            or os.environ.get("ProgramFiles") or r"C:\Program Files")
    return os.path.join(base, APP_NAME)


def default_log_path() -> str:
    """A unique per-run log in %TEMP%, so a failed install leaves evidence."""
    import tempfile
    handle, path = tempfile.mkstemp(prefix="poise-setup-", suffix=".log")
    os.close(handle)
    return path


def build_args(plan: InstallPlan) -> list[str]:
    """The core's command line.

    /VERYSILENT keeps Inno's own UI off the screen; /NORESTART leaves the
    reboot decision to the setup window; /SUPPRESSMSGBOXES turns any core
    dialog into an exit code. /LOG is how progress is observed at all.
    """
    args = [
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/LOG=" + plan.log_path,
        "/DIR=" + plan.target_dir,
    ]
    # The task is unchecked by default, so silence means "no shortcut".
    if plan.desktop_icon:
        args.append("/TASKS=desktopicon")
    return args


def exit_status(code: int) -> str:
    """Classify an Inno exit code as ok / reboot / cancelled / failed."""
    if code == _OK:
        return OK
    if code in _REBOOT_CODES:
        return REBOOT
    if code in _CANCELLED_CODES:
        return CANCELLED
    return FAILED


def parse_marker(line: str) -> tuple[str, str] | None:
    """('phase', 'files') from a 'POISE:phase=files' log line, else None."""
    index = line.find(MARKER)
    if index < 0:
        return None
    payload = line[index + len(MARKER):].strip()
    key, sep, value = payload.partition("=")
    if not sep:
        return None
    return key.strip(), value.strip()


def driver_text(event: str) -> str:
    """One line of detail for the audio step."""
    return {
        "install": "Installing the VB-Cable audio driver - this can take a minute.",
        "skip": "VB-Cable is already present - reusing it.",
        "done": "Audio routing is ready.",
        "reboot": "Windows must restart once to activate the driver.",
        "failed": ("The audio driver could not be installed - Poise can "
                   "install it later from its error dialog."),
    }.get(event, "")


class LogTail:
    """Incrementally read lines from the core's log.

    Inno writes its log in the system codepage (or UTF-8/UTF-16 depending
    on version); the encoding is sniffed once from the BOM. Partial lines
    stay buffered until their newline arrives.
    """

    def __init__(self, path: str):
        self.path = path
        self._offset = 0
        self._decoder = None
        self._buffer = ""

    def _sniff(self, fh) -> str:
        head = fh.read(4)
        fh.seek(0)
        if head.startswith(codecs.BOM_UTF8):
            return "utf-8-sig"
        if head.startswith(codecs.BOM_UTF16_LE) or head.startswith(codecs.BOM_UTF16_BE):
            return "utf-16"
        return "utf-8"

    def read(self) -> list[str]:
        """New complete lines since the previous call."""
        try:
            fh = open(self.path, "rb")
        except OSError:
            return []
        with fh:
            if self._decoder is None:
                encoding = self._sniff(fh)
                self._decoder = codecs.getincrementaldecoder(encoding)("replace")
            fh.seek(self._offset)
            chunk = fh.read()
            self._offset = fh.tell()
        if not chunk:
            return []
        self._buffer += self._decoder.decode(chunk)
        lines = self._buffer.splitlines()
        if self._buffer.endswith(("\n", "\r")):
            self._buffer = ""
        else:
            self._buffer = lines.pop() if lines else self._buffer
        return lines


def core_candidates() -> list[str]:
    """Where PoiseCore.exe may live, in search order."""
    if getattr(sys, "frozen", False):
        # A onefile build: the core is unpacked into _MEIPASS.
        base = os.path.dirname(sys.executable)
    else:
        # Source checkout: installer/bootstrapper/core.py -> installer/.
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [os.path.join(base, CORE_NAME)]
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        candidates.append(os.path.join(bundled, CORE_NAME))
    return candidates


def resolve_core(explicit: str | None = None) -> str | None:
    """Path of the Inno core, or None.

    Order: an explicit --core, installer/PoiseCore.exe beside the sources
    (development) or beside the exe, then the copy PyInstaller unpacked
    into _MEIPASS (a normal build).
    """
    if explicit:
        return explicit if os.path.isfile(explicit) else None
    for candidate in core_candidates():
        if os.path.isfile(candidate):
            return candidate
    return None


def existing_install() -> Existing | None:
    """The registered installation, when there is one (best effort)."""
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:
        return None
    # The core is 32-bit Inno, so its HKLM entry lands in the 32-bit view
    # (WOW6432Node), which a 64-bit process does not see by default.
    views = (
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_CURRENT_USER, 0),
    )
    for root, view in views:
        try:
            key = winreg.OpenKey(root, _UNINSTALL_ROOT + "\\" + UNINSTALL_KEY,
                                 0, winreg.KEY_READ | view)
        except OSError:
            continue
        with key:
            version = _read_value(key, "DisplayVersion")
            # Inno stores the folder with a trailing backslash.
            location = _read_value(key, "InstallLocation")
            location = os.path.normpath(location) if location else ""
        return Existing(version=version, location=location)
    return None


def same_exe(path: str, target_dir: str) -> bool:
    """`path` is the Poise.exe of an install in `target_dir`. Windows
    path rules (ntpath) on every platform: these are Windows paths."""
    if not path or not target_dir:
        return False
    norm = lambda p: ntpath.normcase(ntpath.normpath(p))  # noqa: E731
    return norm(path) == norm(ntpath.join(target_dir, APP_EXE))


def running_poise(target_dir: str) -> list[int]:
    """Pids of Poise processes (window and audio) started from the folder
    about to be installed over. Replacing files under a running Poise
    fails part-way, and the core's own "Poise is running" prompt is off
    in a silent run, so the window has to see to it. [] off Windows."""
    if sys.platform != "win32":
        return []
    return [pid for pid, path in _process_images()
            if same_exe(path, target_dir)]


def _process_images() -> list[tuple[int, str]]:
    """(pid, full exe path) of every process this one may query."""
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD),
                    ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.OpenProcess.restype = wintypes.HANDLE
    snapshot = kernel32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if not snapshot or snapshot == wintypes.HANDLE(-1).value:
        return []
    found = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        more = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            # Only Poise.exe by name: everything else needs no path.
            if entry.szExeFile.lower() == APP_EXE.lower():
                handle = kernel32.OpenProcess(
                    0x1000, False, entry.th32ProcessID)  # QUERY_LIMITED
                if handle:
                    try:
                        size = wintypes.DWORD(1024)
                        buf = ctypes.create_unicode_buffer(size.value)
                        if kernel32.QueryFullProcessImageNameW(
                                handle, 0, buf, ctypes.byref(size)):
                            found.append((entry.th32ProcessID, buf.value))
                    finally:
                        kernel32.CloseHandle(handle)
            more = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return found


def _read_value(key, name: str) -> str:
    import winreg
    try:
        value, _ = winreg.QueryValueEx(key, name)
    except OSError:
        return ""
    return str(value)


def vbcable_present() -> bool | None:
    """True when a CABLE Input render endpoint exists; None if unknown.

    Mirrors the probe in setup.iss: read the friendly-name property of
    every render endpoint and look for "CABLE Input".
    """
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:
        return None
    try:
        base = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _MMDEVICES_RENDER)
    except OSError:
        return None
    try:
        with base:
            index = 0
            while True:
                try:
                    name = winreg.EnumKey(base, index)
                except OSError:
                    return False
                index += 1
                try:
                    with winreg.OpenKey(base, name + r"\Properties") as props:
                        friendly, _ = winreg.QueryValueEx(props, _DEVICE_NAME_PROP)
                except OSError:
                    continue
                if isinstance(friendly, str) and friendly.startswith("CABLE Input"):
                    return True
    except OSError:
        return None


def tail(path: str, lines: int = 40) -> str:
    """Last `lines` lines of the core's log, for the failure screen."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return ""
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        text = data.decode("utf-16", "replace")
    elif data.startswith(codecs.BOM_UTF8):
        text = data.decode("utf-8-sig", "replace")
    else:
        text = data.decode("utf-8", "replace")
    return "\n".join(text.splitlines()[-lines:])
