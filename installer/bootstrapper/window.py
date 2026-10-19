"""
Poise Setup - the setup window and its state machine.

One window, four screens, one hidden core process:

    welcome  ->  progress  ->  finish
                       \\-->  error

The window owns the run: it builds the plan, starts the installer, eases
the bar between the phases the core announces, and decides what a given
exit means. engine.py never touches widgets and pages never touch the
installer.
"""
from __future__ import annotations

import os

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QTimer, Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QGraphicsOpacityEffect, QHBoxLayout,
    QStackedWidget, QVBoxLayout, QWidget,
)

from . import brand, core, engine
from .pages import ErrorPage, FinishPage, ProgressPage, WelcomePage
from .widgets import Rail, WindowButton

#: Design size; the window is not resizable, so the layout never reflows.
WIDTH = 912
HEIGHT = 612

#: Where the bar may travel per phase, in percent. The core reports
#: phases, not bytes, so the bar eases to each mark and waits there
#: rather than inventing a precise number.
PHASE_TARGETS = {"prepare": 12.0, "files": 64.0, "driver": 88.0, "finish": 97.0}

FADE_MS = 170

_SAMPLE_LOG = """\
2026-10-19 14:32:07.921   Log opened. (Time zone: UTC+01:00)
2026-10-19 14:32:07.921   Setup version: Inno Setup version 6.4.3
2026-10-19 14:32:08.104   Starting the installation process.
2026-10-19 14:32:08.180   Creating directory: C:\\Program Files\\Poise Voice Isolator
2026-10-19 14:32:08.203   POISE:phase=files
2026-10-19 14:32:09.512   Dest filename: C:\\Program Files\\Poise Voice Isolator\\Poise.exe
2026-10-19 14:32:11.884   POISE:phase=driver
2026-10-19 14:32:11.902   POISE:driver=install
2026-10-19 14:32:12.006   Poise: running vendored VB-Cable setup (silent)
2026-10-19 14:32:12.884   Poise: VB-Cable setup exited with code 5
2026-10-19 14:32:12.912   POISE:driver=done
2026-10-19 14:32:12.930   Installation process succeeded.
"""


class SetupWindow(QWidget):
    """The setup window. `installer` may be None for --screenshot."""

    def __init__(self, installer=None, target_dir: str = "",
                 core_path: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("shell")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # No Windows title bar: the rail and the page headers are the frame.
        self.setWindowFlags(Qt.WindowType.Window
                            | Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle("Poise Setup")
        self.setWindowIcon(QIcon(brand.asset("icon.ico")))
        self.setFixedSize(WIDTH, HEIGHT)

        self._installer = installer
        self._core_path = core_path
        self._installing = False
        self._value = 0.0
        self._target = 0.0
        self._log_path = ""
        self._fade = None
        self._animation = None
        self._drag_offset = None

        self._existing = core.existing_install()
        if not target_dir:
            target_dir = ((self._existing.location if self._existing else "")
                          or core.default_dir())

        self._build(target_dir, self._existing)
        self._connect()
        self._show_now(self.welcome)

    # -- construction ------------------------------------------------------

    def _build(self, target_dir: str, existing) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(Rail())

        panel = QWidget()
        panel.setObjectName("panel")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(40, 34, 40, 28)
        panel_layout.setSpacing(0)

        self.stack = QStackedWidget()
        self.welcome = WelcomePage(target_dir, existing=existing,
                                   cable=core.vbcable_present())
        self.progress = ProgressPage()
        self.finish = FinishPage()
        self.error = ErrorPage()
        for page in (self.welcome, self.progress, self.finish, self.error):
            self.stack.addWidget(page)
        panel_layout.addWidget(self.stack, 1)
        root.addWidget(panel, 1)

        self._fade = QGraphicsOpacityEffect(self.stack)
        self._fade.setOpacity(1.0)
        self.stack.setGraphicsEffect(self._fade)

        # The frameless window's only control, floated over the page margin.
        self.close_button = WindowButton(self)
        self.close_button.move(WIDTH - 38 - self.close_button.width(), 14)

        self._pump = QTimer(self)
        self._pump.setInterval(16)
        self._pump.timeout.connect(self._advance)

    def _connect(self) -> None:
        self.welcome.browse_clicked.connect(self._choose_dir)
        self.welcome.install_clicked.connect(self.start_install)
        self.welcome.cancel_clicked.connect(self.close)
        self.close_button.clicked.connect(self._request_close)
        self.finish.done_clicked.connect(self._done)
        self.error.retry_clicked.connect(self.start_install)
        self.error.close_clicked.connect(self.close)
        self.error.open_log_clicked.connect(self._open_log)

        if self._installer is not None:
            self._installer.phase_changed.connect(self._on_phase)
            self._installer.driver_event.connect(self._on_driver)
            self._installer.finished.connect(self._on_finished)

    # -- the run -----------------------------------------------------------

    def start_install(self) -> None:
        """Build a plan and hand it to the engine."""
        if self._installer is None or self._installing:
            return
        self._log_path = core.default_log_path()
        plan = core.InstallPlan(
            target_dir=self.welcome.target_dir() or core.default_dir(),
            desktop_icon=self.welcome.desktop_icon(),
            log_path=self._log_path,
            core_path=self._core_path or "",
        )
        self.progress.reset()
        self.welcome.set_installing(True)
        self.close_button.setEnabled(False)
        self._value = 0.0
        self._target = 8.0
        self._installing = True
        self._show(self.progress)
        self._pump.start()
        self._installer.start(plan)

    def _advance(self) -> None:
        if abs(self._target - self._value) < 0.05:
            return
        self._value += (self._target - self._value) * 0.12
        if abs(self._target - self._value) < 0.2:
            self._value = self._target
        self.progress.set_value(self._value)

    def _on_phase(self, name: str) -> None:
        if not self._installing:
            return
        self.progress.set_phase(name)
        if name in PHASE_TARGETS:
            self._target = PHASE_TARGETS[name]

    def _on_driver(self, event: str) -> None:
        if self._installing:
            self.progress.set_driver(event)

    def _on_finished(self, status: str) -> None:
        self._installing = False
        self._pump.stop()
        self.welcome.set_installing(False)
        self.close_button.setEnabled(True)

        if status in (core.OK, core.REBOOT):
            self._value = 100.0
            self.progress.complete()
            self.finish.configure(self.welcome.target_dir(),
                                  reboot=(status == core.REBOOT))
            QTimer.singleShot(360, lambda: self._show(self.finish))
        elif status == core.CANCELLED:
            self.welcome.set_note("Setup was cancelled. Nothing was changed.")
            self._show(self.welcome)
        else:
            message = (getattr(self._installer, "error_message", "")
                       or "The installer stopped before finishing.")
            self.error.set_error(message, core.tail(self._log_path))
            self._show(self.error)

    def _done(self, launch: bool, restart: bool) -> None:
        if restart:
            engine.reboot_now()
        elif launch:
            engine.launch_app(self.welcome.target_dir())
        self.close()

    def _request_close(self) -> None:
        """The custom close control, with the same guard as the window X."""
        if self._installing:
            self.progress.set_note(
                "Setup is still running - please let it finish.")
            return
        self.close()

    def _choose_dir(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose install location", self.welcome.target_dir(),
            QFileDialog.Option.ShowDirsOnly)
        if chosen:
            self.welcome.set_target_dir(os.path.normpath(chosen))

    def _open_log(self) -> None:
        if self._log_path and os.path.isfile(self._log_path):
            from PyQt6.QtCore import QUrl
            from PyQt6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._log_path))

    # -- presentation ------------------------------------------------------

    def _show(self, page: QWidget) -> None:
        self.stack.setCurrentWidget(page)
        page.focus_primary()
        if self._fade is None:
            return
        self._fade.setOpacity(0.0)
        animation = QPropertyAnimation(self._fade, b"opacity", self)
        animation.setDuration(FADE_MS)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._animation = animation

    def _show_now(self, page: QWidget) -> None:
        self.stack.setCurrentWidget(page)
        page.focus_primary()
        if self._fade is not None:
            self._fade.setOpacity(1.0)

    def closeEvent(self, event):  # noqa: N802 (Qt override)
        if self._installing:
            event.ignore()
            self.progress.set_note(
                "Setup is still running - please let it finish.")
            return
        event.accept()

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key.Key_Escape and not self._installing:
            self.close()
            return
        super().keyPressEvent(event)

    # A borderless window has to move itself: dragging the background,
    # the rail or any non-interactive label moves the window.
    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.windowHandle()
            try:
                if handle is not None and handle.startSystemMove():
                    event.accept()
                    return
            except Exception:
                pass
            self._drag_offset = (event.globalPosition().toPoint()
                                 - self.frameGeometry().topLeft())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        if (self._drag_offset is not None
                and event.buttons() & Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        from .chrome import apply_window_chrome
        apply_window_chrome(self)

    # -- previews ----------------------------------------------------------

    def render_pages(self, out_dir: str) -> list[str]:
        """Write one PNG per screen (used by --screenshot and the tests)."""
        os.makedirs(out_dir, exist_ok=True)
        self.show()
        written = []

        def snap(name: str) -> None:
            for _ in range(3):
                QApplication.processEvents()
            path = os.path.join(out_dir, name)
            self.grab().save(path, "PNG")
            written.append(path)

        self._show_now(self.welcome)
        snap("01-welcome.png")

        self.progress.reset()
        self.progress.set_phase("files")
        self.progress.rows["prepare"].set_state("done")
        self.progress.rows["files"].set_state("done")
        self.progress.rows["driver"].set_state("active")
        self.progress.set_value(64)
        self.progress.detail.setText(core.driver_text("install"))
        self._show_now(self.progress)
        snap("02-progress.png")

        self.progress.set_driver("done")
        self.progress.set_phase("finish")
        self.progress.set_value(97)
        self.progress.detail.setText("Finishing up...")
        self._show_now(self.progress)
        snap("03-progress-finish.png")

        self.finish.configure(self.welcome.target_dir(), reboot=False)
        self._show_now(self.finish)
        snap("04-finish.png")

        self.finish.configure(self.welcome.target_dir(), reboot=True)
        self._show_now(self.finish)
        snap("05-finish-reboot.png")

        self.error.set_error(
            "Windows could not copy Poise.exe into Program Files.",
            _SAMPLE_LOG)
        self._show_now(self.error)
        snap("06-error.png")

        self._show_now(self.welcome)
        return written
