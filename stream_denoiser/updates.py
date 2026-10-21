"""
In-app updates (Windows installs).

Everything comes from GitHub Releases, the one place Poise is published:

    check     GET the repo's latest release (drafts and pre-releases are
              never "latest"), compare its vX.Y.Z tag with __version__.
    download  Fetch the release's PoiseCore-update.exe - the silent Inno
              Setup core that Poise_Setup.exe wraps, published under a
              name that does not read as a second installer - and check
              its size and SHA-256 (GitHub's asset digest, or a published
              PoiseCore-update.exe.sha256).
    install   Run it silently with /POISEUPDATE=<signal file>. The core
              elevates (one UAC prompt), writes the signal file to say it
              is running, waits for this Poise to quit (RUNNING_MUTEX),
              installs over the old copy and starts Poise again.

A file Poise downloads itself is not marked as coming from the internet,
so the unsigned installer runs without the browser or SmartScreen
warnings a manual download gets. If anything here fails, the release
page is the fallback.

Qt-free: the GUI drives this from a worker thread (gui/updater.py).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

from . import __version__

REPO = "chabandou/poise-voice-isolator"
#: POISE_UPDATE_API points the check at a stand-in release (end-to-end
#: tests of an installed build); it answers like GitHub's API.
LATEST_API = (os.environ.get("POISE_UPDATE_API")
              or f"https://api.github.com/repos/{REPO}/releases/latest")
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"

#: The release asset the updater runs, and its optional checksum file.
#: Keep in step with build-windows.yml and tools/release_upload.sh.
CORE_ASSET = "PoiseCore-update.exe"
CHECKSUM_ASSET = CORE_ASSET + ".sha256"

#: Created by the GUI while it runs; setup.iss waits for it to go away
#: before replacing files. Keep the name in step with setup.iss.
RUNNING_MUTEX = "PoiseVoiceIsolatorRunning"

#: Uninstaller Inno Setup leaves next to an installed Poise.exe.
UNINSTALLER = "unins000.exe"

TIMEOUT_S = 15
CHUNK = 64 * 1024


class UpdateError(Exception):
    """A check or download failed; the message is fit to show."""


@dataclass(frozen=True)
class Release:
    version: str            # "1.6.0"
    page_url: str           # the release on GitHub
    asset_url: str = ""     # CORE_ASSET download, "" if not published
    asset_size: int = 0
    sha256: str = ""        # lowercase hex, "" if not known yet
    checksum_url: str = ""  # CHECKSUM_ASSET download, if any


def parse_version(text: str) -> Optional[tuple]:
    """(major, minor, patch) from "v1.6.0" / "1.6" / "1.6.0+local";
    None for anything else (pre-release tags included)."""
    match = re.fullmatch(r"v?(\d+)\.(\d+)(?:\.(\d+))?(?:\+[\w.]+)?",
                         text.strip())
    if not match:
        return None
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch or 0)


def is_newer(candidate: str, current: str = __version__) -> bool:
    new, old = parse_version(candidate), parse_version(current)
    return new is not None and old is not None and new > old


def _request(url: str, accept: str = "application/octet-stream"):
    return urllib.request.Request(url, headers={
        "Accept": accept,
        # GitHub's API refuses requests without a User-Agent.
        "User-Agent": f"Poise/{__version__}",
    })


def parse_release(data: dict) -> Optional[Release]:
    """A Release from GitHub's release JSON, or None if it is not one
    the updater should offer (draft, pre-release, odd tag)."""
    if data.get("draft") or data.get("prerelease"):
        return None
    tag = str(data.get("tag_name") or "")
    version = parse_version(tag)
    if version is None:
        return None
    release = {
        "version": ".".join(str(n) for n in version),
        "page_url": str(data.get("html_url") or RELEASES_URL),
    }
    for asset in data.get("assets") or ():
        name = asset.get("name")
        url = str(asset.get("browser_download_url") or "")
        if name == CORE_ASSET:
            release["asset_url"] = url
            release["asset_size"] = int(asset.get("size") or 0)
            digest = str(asset.get("digest") or "")
            if digest.startswith("sha256:"):
                release["sha256"] = digest[len("sha256:"):].lower()
        elif name == CHECKSUM_ASSET:
            release["checksum_url"] = url
    return Release(**release)


def fetch_latest(timeout: float = TIMEOUT_S) -> Optional[Release]:
    """The latest published release, or None if there is none to offer.
    Raises UpdateError when GitHub cannot be reached or answers oddly."""
    try:
        with urllib.request.urlopen(
                _request(LATEST_API, "application/vnd.github+json"),
                timeout=timeout) as response:
            data = json.load(response)
    except urllib.error.HTTPError as e:
        if e.code == 404:   # no releases yet
            return None
        raise UpdateError(f"GitHub answered {e.code}") from e
    except (OSError, ValueError) as e:
        raise UpdateError("Couldn't reach GitHub") from e
    if not isinstance(data, dict):
        raise UpdateError("GitHub sent an unexpected answer")
    return parse_release(data)


def _expected_sha256(release: Release, timeout: float) -> str:
    if release.sha256:
        return release.sha256
    if not release.checksum_url:
        raise UpdateError("The release has no checksum to verify against")
    try:
        with urllib.request.urlopen(_request(release.checksum_url),
                                    timeout=timeout) as response:
            text = response.read(4096).decode("ascii", "replace")
    except OSError as e:
        raise UpdateError("Couldn't download the checksum") from e
    # "<hex>" or sha256sum's "<hex>  PoiseCore-update.exe"
    match = re.match(r"\s*([0-9a-fA-F]{64})\b", text)
    if not match:
        raise UpdateError("The release's checksum file is malformed")
    return match.group(1).lower()


def download(release: Release, dest_dir: str,
             progress: Optional[Callable[[int, int], None]] = None,
             cancelled: Callable[[], bool] = lambda: False,
             timeout: float = TIMEOUT_S) -> str:
    """Download and verify the release's installer core into dest_dir.
    Returns its path. progress(done, total) is called as bytes arrive."""
    if not release.asset_url:
        raise UpdateError(f"Release {release.version} has no {CORE_ASSET}")
    expected = _expected_sha256(release, timeout)
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, f"PoiseCore-{release.version}.exe")
    partial = path + ".part"
    digest = hashlib.sha256()
    done = 0
    try:
        with urllib.request.urlopen(_request(release.asset_url),
                                    timeout=timeout) as response, \
                open(partial, "wb") as out:
            total = int(response.headers.get("Content-Length")
                        or release.asset_size or 0)
            while True:
                if cancelled():
                    raise UpdateError("Download cancelled")
                chunk = response.read(CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress is not None:
                    progress(done, total)
    except OSError as e:
        _remove(partial)
        raise UpdateError("The download was interrupted") from e
    except UpdateError:
        _remove(partial)
        raise
    if release.asset_size and done != release.asset_size:
        _remove(partial)
        raise UpdateError("The download is incomplete")
    if digest.hexdigest() != expected:
        _remove(partial)
        raise UpdateError("The download didn't match its checksum")
    os.replace(partial, path)
    return path


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def install_dir() -> Optional[str]:
    """The folder of an installed Windows Poise, or None when this one
    cannot update itself (source checkout, portable build, Linux)."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return None
    folder = os.path.dirname(os.path.abspath(sys.executable))
    if not os.path.isfile(os.path.join(folder, UNINSTALLER)):
        return None
    return folder


def can_self_update() -> bool:
    return install_dir() is not None


def installer_args(signal_path: str, log_path: str,
                   pid: Optional[int] = None) -> list:
    """Arguments for a silent update run of the Inno core."""
    return [
        "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
        "/CLOSEAPPLICATIONS",
        f"/LOG={log_path}",
        # Read by setup.iss: mark the run as an update (it waits for
        # Poise to quit, then starts it again) and say where to signal;
        # the pid is closed by force if it has not quit within 30 s.
        f"/POISEUPDATE={signal_path}",
        f"/POISEPID={os.getpid() if pid is None else pid}",
    ]


def launch_installer(core_path: str, signal_path: str,
                     log_path: str) -> subprocess.Popen:
    """Start the core detached from Poise, which is about to quit.
    The core elevates itself; this process stays alive (and is what
    exits early) if the user declines the UAC prompt."""
    _remove(signal_path)
    flags = 0
    if sys.platform == "win32":
        flags = (subprocess.DETACHED_PROCESS
                 | subprocess.CREATE_NEW_PROCESS_GROUP)
    return subprocess.Popen(
        [core_path] + installer_args(signal_path, log_path),
        cwd=os.path.dirname(core_path), creationflags=flags,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, close_fds=True)


_mutex_handle = None


def hold_running_mutex() -> None:
    """Mark this Poise as running for setup.iss (Windows; kept until the
    process exits, when Windows releases it)."""
    global _mutex_handle
    if sys.platform != "win32" or _mutex_handle is not None:
        return
    try:
        import ctypes
        _mutex_handle = ctypes.windll.kernel32.CreateMutexW(
            None, False, RUNNING_MUTEX) or None
    except Exception:
        _mutex_handle = None
