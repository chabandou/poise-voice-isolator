"""
Poise Voice Isolator - Update controller

Drives stream_denoiser.updates from the GUI: a quiet daily check, then,
when the user asks, download -> silent install -> quit. Network work runs
on a plain thread; results come back through queued signals.

    idle -> checking -> current | available | error
    available -> downloading -> waiting (UAC) -> quit_requested
                     |               |
                     +---- error <---+  (failed, or the prompt declined)
"""
import os
import shutil
import sys
import tempfile
import threading
import time
from typing import Optional

from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices

from .. import __version__, updates
from ..logging_config import get_logger

_logger = get_logger(__name__)

#: Windows only for now: Linux installs come from the AUR or a binary.
ENABLED = sys.platform == "win32"

IDLE = "idle"
CHECKING = "checking"
CURRENT = "current"
AVAILABLE = "available"
DOWNLOADING = "downloading"
WAITING = "waiting"
ERROR = "error"

FIRST_CHECK_MS = 20_000          # after launch, once the window settled
TICK_MS = 60 * 60 * 1000         # Poise lives in the tray for days
CHECK_EVERY_S = 24 * 60 * 60
POLL_MS = 250                    # installer handshake

DOWNLOAD_DIR = os.path.join(tempfile.gettempdir(), "Poise-update")


class UpdateController(QObject):
    changed = pyqtSignal()               # state, progress or message
    found = pyqtSignal(str)              # a newer version, first sighting
    quit_requested = pyqtSignal()        # the installer runs: quit now

    _checked = pyqtSignal(object, str, bool)    # release, error, manual
    _progress = pyqtSignal(int)
    _downloaded = pyqtSignal(str, str)          # path, error

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.state = IDLE
        self.release: Optional[updates.Release] = None
        self.progress = -1               # percent, -1 when unknown
        self.message = ""
        self._busy = False
        self._cancel = False
        self._proc = None
        self._signal_path = ""

        self._checked.connect(self._on_checked)
        self._progress.connect(self._on_progress)
        self._downloaded.connect(self._on_downloaded)

        self._tick = QTimer(self)
        self._tick.setInterval(TICK_MS)
        self._tick.timeout.connect(self._maybe_check)
        self._poll = QTimer(self)
        self._poll.setInterval(POLL_MS)
        self._poll.timeout.connect(self._poll_installer)

        # Leftovers of the last update (or a failed one).
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)

    # -- public ---------------------------------------------------------------
    @property
    def can_install(self) -> bool:
        """This copy can replace itself (an installed Windows build)."""
        return updates.can_self_update()

    @property
    def page_url(self) -> str:
        return self.release.page_url if self.release else updates.RELEASES_URL

    def start(self) -> None:
        """Begin the daily background checks (if the user wants them)."""
        QTimer.singleShot(FIRST_CHECK_MS, self._maybe_check)
        self._tick.start()

    def check(self, manual: bool = True) -> None:
        if self._busy or self.state in (DOWNLOADING, WAITING):
            return
        self._busy = True
        if manual:
            self._set(CHECKING)
        threading.Thread(target=self._check_worker, args=(manual,),
                         name="poise-update-check", daemon=True).start()

    def install(self) -> None:
        """Download the release and hand over to its installer."""
        if self.release is None or self.state not in (AVAILABLE, ERROR):
            return
        if not self.can_install or not self.release.asset_url:
            self.open_release_page()
            return
        self._cancel = False
        self.progress = 0
        self._set(DOWNLOADING)
        threading.Thread(target=self._download_worker, args=(self.release,),
                         name="poise-update-download", daemon=True).start()

    def cancel(self) -> None:
        """Stop a download (the installer, once started, cannot be)."""
        if self.state == DOWNLOADING:
            self._cancel = True

    def open_release_page(self) -> None:
        QDesktopServices.openUrl(QUrl(self.page_url))

    # -- checking -------------------------------------------------------------
    def _maybe_check(self) -> None:
        if not self.settings.check_updates:
            return
        last = float(self.settings.get(self.settings.KEY_LAST_UPDATE_CHECK))
        if time.time() - last >= CHECK_EVERY_S:
            self.check(manual=False)

    def _check_worker(self, manual: bool) -> None:
        try:
            release = updates.fetch_latest()
            error = ""
        except updates.UpdateError as e:
            release, error = None, str(e)
        except Exception as e:   # never let a check take Poise down
            release, error = None, "The update check failed"
            _logger.exception(f"Update check crashed: {e}")
        self._checked.emit(release, error, manual)

    def _on_checked(self, release, error: str, manual: bool) -> None:
        self._busy = False
        if error:
            _logger.info(f"Update check: {error}")
            # A quiet background failure leaves the page as it was.
            if manual:
                self.message = error
                self._set(ERROR)
            return
        self.settings.set(self.settings.KEY_LAST_UPDATE_CHECK, time.time())
        if release is None or not updates.is_newer(release.version):
            _logger.info(f"Update check: {__version__} is current")
            self.release = None
            if manual or self.state != IDLE:
                self._set(CURRENT)
            return
        _logger.info(f"Update available: {release.version}")
        self.release = release
        self.message = ""
        self._set(AVAILABLE)
        key = self.settings.KEY_UPDATE_NOTIFIED
        if self.settings.get(key) != release.version:
            self.settings.set(key, release.version)
            self.found.emit(release.version)

    # -- downloading ----------------------------------------------------------
    def _download_worker(self, release) -> None:
        last = [-1]

        def progress(done: int, total: int) -> None:
            pct = int(done * 100 / total) if total else -1
            if pct != last[0]:
                last[0] = pct
                self._progress.emit(pct)

        try:
            path = updates.download(release, DOWNLOAD_DIR, progress,
                                    cancelled=lambda: self._cancel)
            self._downloaded.emit(path, "")
        except updates.UpdateError as e:
            self._downloaded.emit("", str(e))
        except Exception as e:
            _logger.exception(f"Update download crashed: {e}")
            self._downloaded.emit("", "The download failed")

    def _on_progress(self, pct: int) -> None:
        if self.state == DOWNLOADING:
            self.progress = pct
            self.changed.emit()

    def _on_downloaded(self, path: str, error: str) -> None:
        if error:
            _logger.warning(f"Update download: {error}")
            self.message = "" if self._cancel else error
            self._set(AVAILABLE if self._cancel else ERROR)
            return
        self._launch(path)

    # -- handing over to the installer -----------------------------------------
    def _launch(self, core_path: str) -> None:
        self._signal_path = os.path.join(DOWNLOAD_DIR, "started")
        log_path = os.path.join(DOWNLOAD_DIR, "install.log")
        try:
            self._proc = updates.launch_installer(
                core_path, self._signal_path, log_path)
        except OSError as e:
            _logger.error(f"Could not start the installer: {e}")
            self.message = "Couldn't start the installer"
            self._set(ERROR)
            return
        _logger.info(f"Installer started ({core_path}), waiting for it")
        self._set(WAITING)
        self._poll.start()

    def _poll_installer(self) -> None:
        if os.path.exists(self._signal_path):
            # Elevated and running: it waits for this Poise to quit.
            self._poll.stop()
            _logger.info("Installer is running; quitting for the update")
            self.quit_requested.emit()
            return
        if self._proc is not None and self._proc.poll() is not None:
            # Gone before it signalled: the prompt was declined (or it
            # failed outright). Poise carries on as it was.
            self._poll.stop()
            _logger.info(f"Installer exited early "
                         f"(code {self._proc.returncode})")
            self.message = "The update was cancelled."
            self._set(AVAILABLE)

    def _set(self, state: str) -> None:
        self.state = state
        if state != DOWNLOADING:
            self.progress = -1
        self.changed.emit()
