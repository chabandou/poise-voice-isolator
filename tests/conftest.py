"""Session Qt harness (import-safe without Qt).

Creates one QApplication for the whole test session and — critically —
keeps a process-global reference to it. Without this, the last Python
reference can drop between test files, destroying the C++ QApplication;
anything created under it (including the shared QSettings backend) then
dies with "wrapped C/C++ object has been deleted" in later files.

QSettings is also redirected to a per-run temp dir: tests must neither
read the user's real config (geometry history makes sizes
nondeterministic) nor pop the minimize-to-tray question or quit the
shared app on window close. The close path is pre-seeded to plain
hide, so closes are side-effect free.

Importing this module without PyQt6 installed is a no-op so the Qt-free
tests keep running anywhere.
"""
import os
import tempfile

_SESSION_APP = None

try:
    # Forced offscreen (not setdefault): the session shell may export a
    # native platform (e.g. wayland;xcb), under which grabs come back
    # scaled, the tiling WM manages test windows, and popups misbehave.
    # Deterministic headless runs need offscreen unconditionally.
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication

    _SESSION_APP = QApplication.instance()
    if _SESSION_APP is None:
        _SESSION_APP = QApplication([])

    _TEST_CONFIG_HOME = tempfile.mkdtemp(prefix="poise-test-config-")
    QSettings.setPath(QSettings.Format.NativeFormat,
                      QSettings.Scope.UserScope, _TEST_CONFIG_HOME)
    # Pre-seed the close path: hide quietly, never ask, never quit.
    _seed = QSettings("Poise", "VoiceIsolator")
    _seed.setValue("behavior/minimize_to_tray_asked", True)
    _seed.setValue("behavior/minimize_to_tray", True)
    _seed.sync()
    del _seed
except Exception:
    _SESSION_APP = None


def session_app():
    """The session QApplication, or None when Qt is unavailable."""
    return _SESSION_APP
