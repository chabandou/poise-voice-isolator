"""The setup window itself: screens, transitions, previews (needs PyQt6).

Without PyQt6 the module-level load raises ImportError, which conftest
turns into a skip for the whole file.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import installer_harness  # noqa: E402

window = installer_harness.load("window")
core = installer_harness.load("core")
engine = installer_harness.load("engine")

from PyQt6.QtCore import QObject, Qt, pyqtSignal  # noqa: E402
from PyQt6.QtTest import QSignalSpy, QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture()
def app():
    return QApplication.instance() or QApplication([])


class FakeInstaller(QObject):
    """Records the plan and lets a test drive the phases by hand."""

    phase_changed = pyqtSignal(str)
    driver_event = pyqtSignal(str)
    finished = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.plan = None
        self.error_message = ""

    def start(self, plan):
        self.plan = plan


def test_window_opens_on_the_welcome_page(app):
    w = window.SetupWindow()
    try:
        assert w.stack.currentWidget() is w.welcome
        assert w.welcome.target_dir()
        assert w.width() == window.WIDTH
        assert w.height() == window.HEIGHT
    finally:
        w.deleteLater()


def test_window_has_no_native_title_bar(app):
    w = window.SetupWindow()
    try:
        assert w.windowFlags() & Qt.WindowType.FramelessWindowHint
        assert w.close_button.isVisibleTo(w)
        assert w.close_button.toolTip() == "Close"
        assert w.close_button.x() + w.close_button.width() <= w.width()
    finally:
        w.deleteLater()


def test_disabled_close_control_paints(app):
    """Regression: the disabled glyph passed a QColor to rgba()."""
    w = window.SetupWindow()
    w.show()
    try:
        w.close_button.setEnabled(False)
        QTest.qWait(30)
        assert not w.close_button.grab().isNull()
    finally:
        w.deleteLater()


def test_close_control_closes_an_idle_window(app):
    w = window.SetupWindow()
    w.show()
    try:
        w.close_button.click()
        assert not w.isVisible()
    finally:
        w.deleteLater()


def test_welcome_offers_update_when_poise_is_installed(app):
    from installer_harness import load
    pages = load("pages")
    page = pages.WelcomePage("C:\\Poise", existing=core.Existing("1.1.0", "C:\\Poise"))
    try:
        assert page.install_button.text() == "Update"
        assert "already installed" in page.subtitle.text().lower()
    finally:
        page.deleteLater()


def test_welcome_install_button_says_install_on_a_clean_machine(app):
    from installer_harness import load
    pages = load("pages")
    page = pages.WelcomePage("C:\\Poise")
    try:
        assert page.install_button.text() == "Install"
    finally:
        page.deleteLater()


def test_start_install_builds_the_plan_and_shows_progress(app, tmp_path):
    fake = FakeInstaller()
    target = str(tmp_path / "Poise")
    w = window.SetupWindow(fake, target_dir=target)
    try:
        w.welcome.shortcut.setChecked(False)
        w.start_install()

        assert fake.plan.target_dir == target
        assert fake.plan.desktop_icon is False
        assert fake.plan.log_path.endswith(".log")
        assert w.stack.currentWidget() is w.progress

        fake.phase_changed.emit("files")
        assert w.progress.rows["files"].state() == "active"
        assert w.progress.rows["prepare"].state() == "done"

        fake.driver_event.emit("skip")
        assert w.progress.rows["driver"].detail() == "already present"

        fake.phase_changed.emit("finish")
        # The skip note survives the phase change.
        assert w.progress.rows["driver"].detail() == "already present"
    finally:
        w.deleteLater()


def test_success_lands_on_the_finish_page(app, tmp_path):
    fake = FakeInstaller()
    w = window.SetupWindow(fake, target_dir=str(tmp_path / "Poise"))
    try:
        w.start_install()
        fake.finished.emit("ok")
        QTest.qWait(600)
        assert w.stack.currentWidget() is w.finish
        assert w.finish.launch.isChecked()
        assert w.finish.reboot_frame.isHidden()
    finally:
        w.deleteLater()


def test_reboot_outcome_disables_launch_and_warns(app, tmp_path):
    fake = FakeInstaller()
    w = window.SetupWindow(fake, target_dir=str(tmp_path / "Poise"))
    try:
        w.start_install()
        fake.finished.emit("reboot")
        QTest.qWait(600)
        assert w.stack.currentWidget() is w.finish
        assert w.finish.reboot_frame.isVisibleTo(w.finish)
        assert w.finish.restart.isChecked()
        assert not w.finish.launch.isEnabled()
    finally:
        w.deleteLater()


def test_driver_reboot_marker_turns_a_clean_exit_into_a_restart(app, tmp_path):
    # Inno exits 0 under /NORESTART even when a restart is due; the
    # driver marker is the only signal, and it must reach the finish page.
    fake = FakeInstaller()
    w = window.SetupWindow(fake, target_dir=str(tmp_path / "Poise"))
    try:
        w.start_install()
        fake.phase_changed.emit("driver")
        fake.driver_event.emit("reboot")
        fake.finished.emit("ok")
        QTest.qWait(600)
        assert w.stack.currentWidget() is w.finish
        assert w.finish.reboot_frame.isVisibleTo(w.finish)
        assert w.finish.restart.isChecked()

        # A retry starts clean: the previous run's restart does not leak.
        w.start_install()
        fake.finished.emit("ok")
        QTest.qWait(600)
        assert not w.finish.reboot_frame.isVisibleTo(w.finish)
    finally:
        w.deleteLater()


def test_failure_shows_the_error_page_with_the_log(app, tmp_path):
    fake = FakeInstaller()
    w = window.SetupWindow(fake, target_dir=str(tmp_path / "Poise"))
    try:
        w.start_install()
        fake.error_message = "Windows could not copy Poise.exe."
        w._log_path = str(tmp_path / "setup.log")
        with open(w._log_path, "w", encoding="utf-8") as fh:
            fh.write("Log opened.\nPOISE:phase=files\n")
        fake.finished.emit("failed")
        QTest.qWait(300)
        assert w.stack.currentWidget() is w.error
        assert "could not copy" in w.error.subtitle.text()
        assert "POISE:phase=files" in w.error.log.toPlainText()
    finally:
        w.deleteLater()


def test_close_is_refused_while_installing(app, tmp_path):
    fake = FakeInstaller()
    w = window.SetupWindow(fake, target_dir=str(tmp_path / "Poise"))
    w.show()
    try:
        w.start_install()
        assert w._installing
        assert not w.close_button.isEnabled()
        w.close()
        assert w.isVisible(), "the window must stay open mid-install"
        fake.finished.emit("cancelled")
        assert not w._installing
        assert w.close_button.isEnabled()
        assert w.stack.currentWidget() is w.welcome
    finally:
        w.close()
        w.deleteLater()


def test_missing_core_fails_with_a_useful_message(app, tmp_path):
    installer = engine.Installer()
    spy = QSignalSpy(installer.finished)
    plan = core.InstallPlan(str(tmp_path / "Poise"),
                            core_path=str(tmp_path / "absent.exe"))
    installer.start(plan)
    assert spy.wait(2000), "the engine never reported a result"
    assert spy[0][0] == core.FAILED
    assert core.CORE_NAME in installer.error_message


def test_render_pages_writes_every_screen(app, tmp_path):
    w = window.SetupWindow()
    try:
        paths = w.render_pages(str(tmp_path))
        names = [os.path.basename(p) for p in paths]
        assert names == [
            "01-welcome.png", "02-progress.png", "03-progress-finish.png",
            "04-finish.png", "05-finish-reboot.png", "06-error.png",
        ]
        for path in paths:
            assert os.path.getsize(path) > 5000, path
    finally:
        w.deleteLater()
