"""
Poise Setup - the running half of the engine.

Runs the hidden Inno core and turns its log into signals the window can
draw. All decisions live in core.py; this module only owns the process,
the thread and the timers.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

from . import core
from .core import InstallPlan, LogTail, parse_marker

#: Windows: no console flash for the core.
CREATE_NO_WINDOW = 0x08000000

#: How often the core's log is polled, in seconds.
POLL_SECONDS = 0.12

#: A core that runs longer than this is considered wedged.
MAX_RUNTIME_SECONDS = 20 * 60


class _Worker(QThread):
    """One silent core run, observed through its log file."""

    phase = pyqtSignal(str)
    event = pyqtSignal(str)
    done = pyqtSignal(int)
    failed = pyqtSignal(str)

    def __init__(self, plan: InstallPlan, parent=None):
        super().__init__(parent)
        self.plan = plan
        self._stopping = False

    def run(self):  # noqa: D102 (QThread entry point)
        args = core.build_args(self.plan)
        try:
            proc = subprocess.Popen(
                [self.plan.core_path, *args],
                cwd=os.path.dirname(self.plan.core_path) or None,
                creationflags=(CREATE_NO_WINDOW if sys.platform == "win32" else 0),
            )
        except OSError as exc:
            self.failed.emit(f"Setup could not start: {exc}")
            return

        tail = LogTail(self.plan.log_path)
        deadline = time.monotonic() + MAX_RUNTIME_SECONDS
        while True:
            self._drain(tail)
            code = proc.poll()
            if code is not None:
                break
            if time.monotonic() > deadline:
                proc.kill()
                proc.wait(5000)
                self.failed.emit("Setup stopped responding and was closed.")
                return
            time.sleep(POLL_SECONDS)
        # The core is gone; pick up whatever it wrote just before exiting.
        self._drain(tail)
        self.done.emit(code)

    def _drain(self, tail: LogTail) -> None:
        for line in tail.read():
            marker = parse_marker(line)
            if marker is None:
                continue
            key, value = marker
            if key == "phase":
                self.phase.emit(value)
            elif key == "driver":
                self.event.emit(value)


class Installer(QObject):
    """Runs the real core. Same signals as MockInstaller."""

    phase_changed = pyqtSignal(str)
    driver_event = pyqtSignal(str)
    finished = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self.plan = None
        self.error_message = ""

    @property
    def running(self) -> bool:
        return self._worker is not None

    def start(self, plan: InstallPlan) -> None:
        """Begin installing. `finished` always follows, on this thread."""
        if self._worker is not None:
            raise RuntimeError("setup is already running")
        plan.log_path = plan.log_path or core.default_log_path()
        plan.core_path = plan.core_path or core.resolve_core() or ""
        self.plan = plan
        self.error_message = ""
        if not plan.core_path or not os.path.isfile(plan.core_path):
            self.error_message = (
                "This build is missing its installer core "
                f"({core.CORE_NAME}).")
            QTimer.singleShot(0, lambda: self.finished.emit(core.FAILED))
            return
        worker = _Worker(plan)
        worker.phase.connect(self.phase_changed)
        worker.event.connect(self.driver_event)
        worker.done.connect(self._on_done)
        worker.failed.connect(self._on_failed)
        self._worker = worker
        worker.start()

    def _on_done(self, code: int) -> None:
        self._release()
        status = core.exit_status(code)
        if status == core.FAILED:
            self.error_message = f"Setup stopped with error code {code}."
        self.finished.emit(status)

    def _on_failed(self, message: str) -> None:
        self.error_message = message
        self._release()
        self.finished.emit(core.FAILED)

    def _release(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.wait(5000)
            worker.deleteLater()


class MockInstaller(QObject):
    """A timed rehearsal of a run, for UI work and --screenshot."""

    phase_changed = pyqtSignal(str)
    driver_event = pyqtSignal(str)
    finished = pyqtSignal(str)

    def __init__(self, outcome: str = core.OK, parent=None):
        super().__init__(parent)
        self.outcome = outcome
        self.plan = None
        self.error_message = ""

    @property
    def running(self) -> bool:
        return False

    def start(self, plan: InstallPlan) -> None:
        self.plan = plan
        self.error_message = ""
        steps = [
            (350, lambda: self.phase_changed.emit("prepare")),
            (900, lambda: self.phase_changed.emit("files")),
            (1900, lambda: self.phase_changed.emit("driver")),
            (2150, lambda: self.driver_event.emit("install")),
            (3000, lambda: self.driver_event.emit("done")),
            (3300, lambda: self.phase_changed.emit("finish")),
            (3700, lambda: self.finished.emit(self.outcome)),
        ]
        if self.outcome == core.FAILED:
            steps = steps[:4] + [
                (2900, lambda: self.finished.emit(core.FAILED))]
            self.error_message = "The audio driver could not be installed."
        for delay, action in steps:
            QTimer.singleShot(delay, action)


def launch_app(target_dir: str) -> bool:
    """Start the installed Poise, detached from this process."""
    exe = os.path.join(target_dir, core.APP_EXE)
    if not os.path.isfile(exe):
        return False
    flags = 0x00000008 | (CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    try:
        subprocess.Popen([exe], cwd=target_dir, creationflags=flags,
                         close_fds=True)
    except OSError:
        return False
    return True


def reboot_now() -> None:
    """Restart Windows in a few seconds, letting the user save work."""
    try:
        subprocess.Popen(["shutdown", "/r", "/t", "5"],
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError:
        pass
