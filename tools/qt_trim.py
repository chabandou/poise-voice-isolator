"""Drop the parts of PyQt6 that PyInstaller bundles but Poise never loads.

Shared by poise_windows.spec (the app) and installer/PoiseSetup.spec (the
setup window). PyInstaller's PyQt6 hooks collect generously; each rule
below names a file group, its size in the 6.x wheels, and why it can go.

    from tools.qt_trim import trim
    a.binaries, a.datas = trim(a.binaries, a.datas)

Networking stays: QtNetwork's Schannel backend (Windows' own TLS) and
Python's ssl module are kept, so an update check can use either.
"""
from __future__ import annotations

import posixpath

QT = "PyQt6/Qt6/"

#: Image formats either program actually decodes. PNG is built into
#: QtGui; SVG and ICO are the app's icons and the setup window's mark.
KEEP_IMAGEFORMATS = {"qsvg.dll", "qico.dll"}

#: Exact files to drop, by bundle path.
DROP_FILES = {
    # Mesa's software OpenGL (~20 MB): a fallback for machines without a
    # GL driver. Qt Quick draws through Direct3D 11 on Windows and the
    # widgets never use OpenGL, so nothing loads it.
    QT + "bin/opengl32sw.dll",
    # Only reachable through the PDF image-format plugin dropped below.
    QT + "bin/Qt6Pdf.dll",
    # A test platform; Windows uses qwindows.dll.
    QT + "plugins/platforms/qminimal.dll",
    # Qt's OpenSSL TLS backend, and the OpenSSL it would load. PyInstaller
    # picks those DLLs up from whatever is on PATH (Git for Windows' copy
    # on a dev machine). Qt's Schannel backend does TLS without them, and
    # Python's ssl module carries its own libssl-3/libcrypto-3.
    QT + "plugins/tls/qopensslbackend.dll",
    "libssl-3-x64.dll",
    "libcrypto-3-x64.dll",
}

#: Whole directories to drop.
DROP_DIRS = (
    # Qt's own UI strings in 30-odd languages (~8.5 MB); Poise is English.
    QT + "translations/",
    # Touch-input and network-reachability plugins nothing asks for.
    QT + "plugins/generic/",
    QT + "plugins/networkinformation/",
)


def _path(entry) -> str:
    return entry[0].replace("\\", "/")


def wanted(entry) -> bool:
    """False for a bundled file Poise never loads."""
    path = _path(entry)
    if path in DROP_FILES:
        return False
    if any(path.startswith(prefix) for prefix in DROP_DIRS):
        return False
    folder, name = posixpath.split(path)
    if folder == QT + "plugins/imageformats":
        return name.lower() in KEEP_IMAGEFORMATS
    return True


def trim(binaries, datas):
    """The TOCs without the dropped files (order kept)."""
    return ([e for e in binaries if wanted(e)],
            [e for e in datas if wanted(e)])
