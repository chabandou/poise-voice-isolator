"""Session Qt harness (import-safe without Qt).

Creates one QApplication for the whole test session and — critically —
keeps a process-global reference to it. Without this, the last Python
reference can drop between test files, destroying the C++ QApplication;
anything created under it (including the shared QSettings backend) then
dies with "wrapped C/C++ object has been deleted" in later files.

QSettings is also redirected to a per-run temp dir: tests must neither
read the user's real config (geometry history makes sizes
nondeterministic; on Windows that is the registry, which the tests
used to read and write) nor pop the minimize-to-tray question or quit
the shared app on window close. The close path is pre-seeded to plain
hide, so closes are side-effect free.

Importing this module without PyQt6 installed is a no-op so the Qt-free
tests keep running anywhere. Without PyQt6, a test module that cannot
even be imported because PyQt6 is missing is reported as skipped rather
than as a collection error (CI deliberately runs without Qt), so GUI
tests need no per-file importorskip guard.
"""
import importlib.util
import os
import tempfile

import pytest

_HAS_PYQT6 = importlib.util.find_spec("PyQt6") is not None

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
    # On Windows the native format is the registry, which setPath cannot
    # move: Settings opens QSettings in defaultFormat(), so make that INI
    # files under the temp dir on every platform.
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    for _fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(_fmt, QSettings.Scope.UserScope, _TEST_CONFIG_HOME)
    # Pre-seed the close path: hide quietly, never ask, never quit.
    _seed = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                      "Poise", "VoiceIsolator")
    _seed.setValue("behavior/minimize_to_tray_asked", True)
    _seed.setValue("behavior/minimize_to_tray", True)
    _seed.sync()
    del _seed
except Exception:
    _SESSION_APP = None


def session_app():
    """The session QApplication, or None when Qt is unavailable."""
    return _SESSION_APP


@pytest.hookimpl(wrapper=True)
def pytest_make_collect_report(collector):
    """Skip, don't error, a test module whose only problem is no PyQt6."""
    report = yield
    if (not _HAS_PYQT6 and report.failed
            and isinstance(collector, pytest.Module)
            and "No module named 'PyQt6" in str(report.longrepr)):
        report.outcome = "skipped"
        report.longrepr = (str(collector.path), None,
                           "Skipped: PyQt6 not installed")
    return report
