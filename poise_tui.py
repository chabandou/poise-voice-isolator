#!/usr/bin/env python3
"""
Poise Voice Isolator - TUI Entry Point

This is the top-level entry script for Nuitka builds.
"""
import os
import shutil


def unpack_dirs():
    """(this binary's unpack folder, the folder all versions unpack to)."""
    here = os.path.dirname(os.path.realpath("/proc/self/exe"))
    cache = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return here, os.path.realpath(os.path.join(cache, "poise", "onefile"))


def _in_use(path: str) -> bool:
    """True if a running process was started from inside ``path``."""
    for pid in os.listdir("/proc"):
        try:
            if os.readlink(f"/proc/{pid}/exe").startswith(path + os.sep):
                return True
        except OSError:
            pass
    return False


def prune_old_unpacks(here: str, root: str) -> None:
    """Delete other versions' unpacked copies of the onefile binary.

    Each version unpacks to <root>/<version> and keeps it for the next
    start (see build-linux.sh). A folder a running Poise came from stays:
    it spawns its audio process from there.
    """
    if os.path.dirname(here) != root:
        return  # not the cached onefile build: a dev run or an older build
    for name in os.listdir(root):
        path = os.path.join(root, name)
        if path != here and not _in_use(path):
            shutil.rmtree(path, ignore_errors=True)


def main(argv=None):
    try:
        prune_old_unpacks(*unpack_dirs())
    except OSError:
        pass
    # Single entry logic lives in stream_denoiser.tui:main (TUI plus
    # one-shot --doctor/--reset-audio/--fix-execstack). Do NOT duplicate
    # flag handling here: this script once swallowed those flags with
    # parse_known_args and launched the TUI instead (e.g. `poise --doctor`
    # opened the app rather than printing checks).
    from stream_denoiser.tui import main as tui_main
    tui_main(argv)

if __name__ == "__main__":
    main()
