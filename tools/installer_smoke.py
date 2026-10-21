#!/usr/bin/env python3
"""Installer smoke test: install, update in place, uninstall (Windows, CI).

Drives the Inno core (PoiseCore.exe, ISCC /DCORE) the way Poise_Setup.exe
and the in-app updater do, on a throwaway install folder:

1. install --core silently into --dir, check the files that matter and
   that VB-Cable is there afterwards (setup.iss installs it when missing);
2. with --next-core: start the installed Poise.exe, then take the
   updater's path (stream_denoiser.updates against a local stand-in for
   GitHub's release API: fetch, download, verify, run the core with the
   app's own arguments) and check the new version is installed and
   Poise was started again;
3. uninstall silently and check the folder is cleared.

Needs an elevated shell (the core installs per machine) and the
repository's requirements. Usage:

    python tools/installer_smoke.py --core installer/PoiseCore.exe \
        --dir %RUNNER_TEMP%/PoiseInstall \
        [--next-core PoiseCore-next.exe --next-version 1.5.1]
"""
import argparse
import ctypes
import hashlib
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

INSTALL_TIMEOUT = 600   # includes the VB-Cable setup on a clean machine
MUTEX = "PoiseVoiceIsolatorRunning"


def fail(message: str, log: Path = None) -> None:
    if log is not None and log.exists():
        print(f"---- {log} (last 60 lines)")
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        print("\n".join(lines[-60:]))
    raise SystemExit(f"FAIL: {message}")


def step(message: str) -> None:
    print(f"== {message}", flush=True)


def installed_version(folder: Path) -> str:
    with open(folder / "_internal" / "pyproject.toml", "rb") as f:
        return tomllib.load(f)["project"]["version"]


def mutex_held() -> bool:
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenMutexW(0x00100000, False, MUTEX)  # SYNCHRONIZE
    if handle:
        kernel32.CloseHandle(handle)
    return bool(handle)


def wait_for(what: str, check, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while not check():
        if time.monotonic() > deadline:
            fail(f"timed out after {timeout:.0f} s waiting for {what}")
        time.sleep(0.5)


def run_core(core: Path, args: list, log: Path) -> None:
    print(" ".join([str(core)] + args), flush=True)
    try:
        code = subprocess.run([str(core)] + args,
                              timeout=INSTALL_TIMEOUT).returncode
    except subprocess.TimeoutExpired:
        fail(f"{core.name} did not finish in {INSTALL_TIMEOUT} s", log)
    if code != 0:
        fail(f"{core.name} exited with {code}", log)


def check_install(folder: Path, version: str, log: Path) -> None:
    for rel in ("Poise.exe", "unins000.exe", "_internal/pyproject.toml",
                "_internal/poise_wasapi.dll", "_internal/rnnoise.dll",
                "_internal/stream_denoiser/models",
                "vbcable/VBCABLE_Setup_x64.exe"):
        if not (folder / rel).exists():
            fail(f"{rel} missing from the install", log)
    have = installed_version(folder)
    if have != version:
        fail(f"installed version is {have}, expected {version}", log)
    text = log.read_text(encoding="utf-8", errors="replace")
    for marker in ("POISE:phase=files", "POISE:phase=finish"):
        if marker not in text:
            fail(f"{marker} not in the setup log", log)
    driver = [line for line in text.splitlines() if "POISE:driver=" in line]
    print("driver:", driver[-1].split("POISE:")[-1] if driver else "?")


def check_vbcable(log: Path) -> None:
    from stream_denoiser.backends.platform.windows import is_vbcable_installed
    # The endpoints show up a moment after the driver setup returns.
    wait_for("CABLE Input and CABLE Output after the install",
             is_vbcable_installed, 60)


class _Release(http.server.BaseHTTPRequestHandler):
    """GitHub's /releases/latest and the asset, for one release."""
    core: bytes = b""
    version: str = ""

    def do_GET(self):
        base = f"http://127.0.0.1:{self.server.server_port}"
        if self.path == "/latest":
            body = json.dumps({
                "tag_name": f"v{self.version}",
                "html_url": f"{base}/page",
                "draft": False, "prerelease": False,
                "assets": [{
                    "name": "PoiseCore-update.exe",
                    "browser_download_url": f"{base}/core",
                    "size": len(self.core),
                    "digest": "sha256:" + hashlib.sha256(self.core).hexdigest(),
                }],
            }).encode()
        elif self.path == "/core":
            body = self.core
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print("server:", fmt % args, flush=True)


def update(folder: Path, next_core: Path, next_version: str,
           work: Path) -> None:
    step("start the installed Poise")
    poise = subprocess.Popen([str(folder / "Poise.exe")],
                             env={**os.environ, "POISE_LOG_FILE":
                                  str(work / "poise-before.log")})
    wait_for("Poise to hold its running mutex", mutex_held, 60)

    step("updater path against a stand-in release")
    _Release.core = next_core.read_bytes()
    _Release.version = next_version
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Release)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    # Read when stream_denoiser.updates is imported.
    os.environ["POISE_UPDATE_API"] = \
        f"http://127.0.0.1:{server.server_port}/latest"
    from stream_denoiser import updates

    release = updates.fetch_latest()
    if release is None or release.version != next_version:
        fail(f"the check offered {release}, expected {next_version}")
    if not updates.is_newer(release.version, installed_version(folder)):
        fail(f"{release.version} is not newer than the installed version")
    core = Path(updates.download(release, str(work / "download")))
    print("downloaded and verified:", core)

    signal = work / "update-signal.txt"
    log = work / "update.log"
    # The app's own arguments, with the running Poise's pid (the GUI
    # passes its own): setup waits for it to quit, then closes it.
    run_core(core, updates.installer_args(str(signal), str(log),
                                          pid=poise.pid), log)
    server.shutdown()
    if poise.poll() is None:
        fail("the old Poise is still running after the update", log)
    if not signal.exists():
        fail("setup did not write the update signal", log)
    have = installed_version(folder)
    if have != next_version:
        fail(f"installed version is {have} after the update", log)
    text = log.read_text(encoding="utf-8", errors="replace")
    if "Poise: started again after the update" not in text:
        fail("setup did not start Poise again", log)
    wait_for("the relaunched Poise to hold its mutex", mutex_held, 60)
    print("updated to", have, "and Poise is running again")


def stop_poise() -> None:
    subprocess.run(["taskkill", "/F", "/T", "/IM", "Poise.exe"],
                   capture_output=True)
    wait_for("Poise to exit", lambda: not mutex_held(), 30)


def uninstall(folder: Path, work: Path) -> None:
    step("uninstall")
    stop_poise()
    log = work / "uninstall.log"
    code = subprocess.run([str(folder / "unins000.exe"), "/VERYSILENT",
                           "/SUPPRESSMSGBOXES", "/NORESTART",
                           f"/LOG={log}"], timeout=300).returncode
    if code != 0:
        fail(f"unins000.exe exited with {code}", log)
    # The uninstaller hands over to a copy of itself in %TEMP% and
    # returns: wait for the files to go.
    wait_for("the install folder to be cleared",
             lambda: not (folder / "Poise.exe").exists()
             and not (folder / "unins000.exe").exists(), 120)
    left = [p for p in folder.rglob("*")] if folder.exists() else []
    print(f"uninstalled ({len(left)} entries left in the folder)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--core", type=Path, required=True)
    parser.add_argument("--dir", type=Path, required=True)
    parser.add_argument("--version",
                        help="expected installed version (default: "
                             "pyproject.toml's)")
    parser.add_argument("--next-core", type=Path)
    parser.add_argument("--next-version")
    parser.add_argument("--no-vbcable-check", action="store_true",
                        help="skip checking VB-Cable after the install")
    args = parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("Windows only")
    if args.next_core and not args.next_version:
        parser.error("--next-core needs --next-version")
    version = args.version or tomllib.loads(
        (ROOT / "pyproject.toml").read_text())["project"]["version"]
    work = Path(tempfile.mkdtemp(prefix="poise-installer-smoke-"))

    step(f"install {version} into {args.dir}")
    log = work / "install.log"
    run_core(args.core, ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                         f"/DIR={args.dir}", f"/LOG={log}"], log)
    check_install(args.dir, version, log)
    if not args.no_vbcable_check:
        check_vbcable(log)
    print("installed")

    if args.next_core:
        update(args.dir, args.next_core.resolve(), args.next_version, work)

    uninstall(args.dir, work)
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
