"""Update controller and its UI (gui/updater.py; needs Qt).

The network side is stubbed: updates.fetch_latest / download /
launch_installer are replaced, so nothing here reaches GitHub.
"""
import os
import time

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from stream_denoiser import updates  # noqa: E402
from stream_denoiser.gui import updater as upd  # noqa: E402

NEW = updates.Release(version="99.0.0", page_url="https://example.invalid/r",
                      asset_url="https://example.invalid/core",
                      asset_size=3, sha256="0" * 64)


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _pump(app, until, secs=3.0):
    end = time.time() + secs
    while time.time() < end:
        app.processEvents()
        if until():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture()
def settings():
    from stream_denoiser.gui.settings import get_settings
    s = get_settings()
    for key in (s.KEY_UPDATE_NOTIFIED, s.KEY_LAST_UPDATE_CHECK,
                s.KEY_UPDATE_FROM, s.KEY_UPDATE_RESUME):
        s.remove(key)
    yield s
    for key in (s.KEY_UPDATE_NOTIFIED, s.KEY_LAST_UPDATE_CHECK,
                s.KEY_UPDATE_FROM, s.KEY_UPDATE_RESUME):
        s.remove(key)


@pytest.fixture()
def controller(app, settings, monkeypatch, tmp_path):
    # A folder of its own: the controller clears it on start.
    monkeypatch.setattr(upd, "DOWNLOAD_DIR", str(tmp_path / "dl"))
    return upd.UpdateController(settings)


def test_check_finds_a_newer_release_once(app, controller, monkeypatch):
    monkeypatch.setattr(updates, "fetch_latest", lambda: NEW)
    found = []
    controller.found.connect(found.append)
    controller.check(manual=True)
    assert controller.state == upd.CHECKING
    assert _pump(app, lambda: controller.state == upd.AVAILABLE)
    assert controller.release == NEW and found == ["99.0.0"]
    controller.check(manual=False)
    assert _pump(app, lambda: not controller._busy)
    assert found == ["99.0.0"]        # same version: no second notice


def test_check_when_current(app, controller, monkeypatch):
    current = updates.Release(version="0.0.1", page_url="x")
    monkeypatch.setattr(updates, "fetch_latest", lambda: current)
    controller.check(manual=True)
    assert _pump(app, lambda: controller.state == upd.CURRENT)
    assert controller.release is None


def test_failed_check_is_quiet_in_the_background(app, controller,
                                                 monkeypatch):
    def fail():
        raise updates.UpdateError("Couldn't reach GitHub")
    monkeypatch.setattr(updates, "fetch_latest", fail)
    controller.check(manual=False)
    assert _pump(app, lambda: not controller._busy)
    assert controller.state == upd.IDLE
    controller.check(manual=True)
    assert _pump(app, lambda: controller.state == upd.ERROR)
    assert "Couldn't reach GitHub" in controller.message


def test_background_check_waits_a_day(app, controller, settings,
                                      monkeypatch):
    calls = []
    monkeypatch.setattr(controller, "check",
                        lambda manual=True: calls.append(manual))
    settings.check_updates = True
    try:
        settings.set(settings.KEY_LAST_UPDATE_CHECK, time.time())
        controller._maybe_check()
        assert calls == []
        settings.set(settings.KEY_LAST_UPDATE_CHECK, time.time() - 90000)
        controller._maybe_check()
        assert calls == [False]
        settings.check_updates = False
        controller._maybe_check()
        assert calls == [False]
    finally:
        settings.check_updates = False


def _available(controller):
    controller.release = NEW
    controller._set(upd.AVAILABLE)


class _Proc:
    def __init__(self):
        self.returncode = None

    def poll(self):
        return self.returncode


def _stub_install(monkeypatch, tmp_path):
    proc = _Proc()
    monkeypatch.setattr(updates, "can_self_update", lambda: True)
    def download(release, dest, progress=None, cancelled=None):
        progress(3, 3)
        os.makedirs(dest, exist_ok=True)
        core = os.path.join(dest, "PoiseCore-99.0.0.exe")
        with open(core, "wb") as f:
            f.write(b"exe")
        return core
    monkeypatch.setattr(updates, "download", download)
    launched = []

    def launch(path, signal, log):
        launched.append((path, signal))
        return proc
    monkeypatch.setattr(updates, "launch_installer", launch)
    return proc, launched


def test_install_hands_over_once_the_installer_signals(
        app, controller, monkeypatch, tmp_path):
    proc, launched = _stub_install(monkeypatch, tmp_path)
    quits = []
    controller.quit_requested.connect(lambda: quits.append(1))
    _available(controller)
    controller.install()
    assert _pump(app, lambda: controller.state == upd.WAITING)
    path, signal = launched[0]
    assert path.endswith("PoiseCore-99.0.0.exe")
    app.processEvents()
    assert quits == []                 # not before the UAC prompt is past
    with open(signal, "w") as f:
        f.write("started")
    assert _pump(app, lambda: quits == [1])


def test_declined_prompt_leaves_poise_running(
        app, controller, monkeypatch, tmp_path):
    proc, _ = _stub_install(monkeypatch, tmp_path)
    quits = []
    controller.quit_requested.connect(lambda: quits.append(1))
    _available(controller)
    controller.install()
    assert _pump(app, lambda: controller.state == upd.WAITING)
    proc.returncode = 1223             # ERROR_CANCELLED
    assert _pump(app, lambda: controller.state == upd.AVAILABLE)
    assert controller.message == "The update was cancelled."
    assert quits == []


def test_failed_download_offers_the_release_page(
        app, controller, monkeypatch):
    monkeypatch.setattr(updates, "can_self_update", lambda: True)

    def download(*args, **kwargs):
        raise updates.UpdateError("The download didn't match its checksum")
    monkeypatch.setattr(updates, "download", download)
    _available(controller)
    controller.install()
    assert _pump(app, lambda: controller.state == upd.ERROR)
    assert "checksum" in controller.message


def test_without_an_installed_copy_update_opens_the_page(
        app, controller, monkeypatch):
    opened = []
    monkeypatch.setattr(updates, "can_self_update", lambda: False)
    monkeypatch.setattr(controller, "open_release_page",
                        lambda: opened.append(1))
    _available(controller)
    controller.install()
    assert opened == [1] and controller.state == upd.AVAILABLE


# -- the window ---------------------------------------------------------------------
needs_updates = pytest.mark.skipif(not upd.ENABLED,
                                   reason="in-app updates are Windows-only")


@pytest.fixture()
def window(app, settings, monkeypatch, tmp_path):
    monkeypatch.setattr(upd, "DOWNLOAD_DIR", str(tmp_path / "dl"))
    from stream_denoiser.gui.main_window import MainWindow
    win = MainWindow()
    win.resize(1180, 760)
    win.show()
    app.processEvents()
    yield win
    win.close()


@needs_updates
def test_about_line_follows_the_controller(app, window, monkeypatch):
    u = window.updater
    label = window.update_label
    assert "Check for updates" in label.text()
    assert window.update_btn.isHidden()     # nothing to install yet

    monkeypatch.setattr(updates, "can_self_update", lambda: True)
    _available(u)
    assert "Poise 99.0.0 is available" in label.text()
    assert "What's new" in label.text()
    assert not window.update_btn.isHidden()
    assert window.update_btn.text() == "Update"
    assert window.sidebar._update_pill.isVisible()
    assert window.sidebar._update_pill.text() == "Update to 99.0.0"
    assert window.tray._update_action.isVisible()

    u.progress = 42
    u.state = upd.DOWNLOADING
    u.changed.emit()
    assert label.text().startswith("Downloading 99.0.0… 42%")
    assert window.LINK_CANCEL in label.text()
    assert window.update_btn.isHidden()

    u._set(upd.WAITING)
    assert label.text().startswith("Installing")

    u.release = None
    u._set(upd.CURRENT)
    assert "Check again" in label.text()
    assert not window.sidebar._update_pill.isVisible()
    assert not window.tray._update_action.isVisible()


@needs_updates
def test_about_links_act(app, window, monkeypatch):
    calls = []
    monkeypatch.setattr(window.updater, "check",
                        lambda manual=True: calls.append("check"))
    monkeypatch.setattr(window.updater, "cancel",
                        lambda: calls.append("cancel"))
    window._on_update_link(window.LINK_CHECK)
    window._on_update_link(window.LINK_CANCEL)
    assert calls == ["check", "cancel"]


@needs_updates
def test_portable_copy_points_to_github(app, window, monkeypatch):
    monkeypatch.setattr(updates, "can_self_update", lambda: False)
    _available(window.updater)
    assert "Get it on GitHub" in window.update_label.text()
    assert window.update_btn.isHidden()


@needs_updates
def test_failed_update_falls_back_to_github(app, window):
    u = window.updater
    u.release = NEW
    u.message = "The download was interrupted"
    u._set(upd.ERROR)
    text = window.update_label.text()
    assert text.startswith("The download was interrupted")
    assert NEW.page_url in text and "Get it on GitHub" in text


@needs_updates
def test_settings_switch_controls_the_checks(app, window, settings):
    window.updates_switch.setChecked(True)
    assert settings.check_updates
    window.updates_switch.setChecked(False)
    assert not settings.check_updates


@needs_updates
def test_quitting_for_an_update_remembers_isolation(app, window, settings,
                                                    monkeypatch):
    from stream_denoiser import __version__
    quit_calls = []
    monkeypatch.setattr(window, "_quit_app", lambda: quit_calls.append(1))
    window.updater.quit_requested.emit()
    assert quit_calls == [1]
    assert settings.get(settings.KEY_UPDATE_FROM) == __version__
    assert settings.get(settings.KEY_UPDATE_RESUME) is False


@needs_updates
def test_first_start_after_an_update(app, settings, monkeypatch, tmp_path):
    monkeypatch.setattr(upd, "DOWNLOAD_DIR", str(tmp_path / "dl"))
    settings.set(settings.KEY_UPDATE_FROM, "0.0.1")
    settings.set(settings.KEY_UPDATE_RESUME, False)
    from stream_denoiser.gui.main_window import MainWindow
    notes = []
    from stream_denoiser.gui import system_tray
    monkeypatch.setattr(system_tray.SystemTray, "notify",
                        lambda self, title, msg, is_error=False:
                        notes.append(title))
    win = MainWindow()
    try:
        assert notes == ["Poise is up to date"]
        assert not settings.contains(settings.KEY_UPDATE_FROM)
        assert not settings.contains(settings.KEY_UPDATE_RESUME)
    finally:
        win.close()


def test_download_dir_is_cleared_on_start(app, settings, monkeypatch,
                                          tmp_path):
    folder = tmp_path / "Poise-update"
    folder.mkdir()
    (folder / "PoiseCore-1.0.0.exe").write_bytes(b"old")
    monkeypatch.setattr(upd, "DOWNLOAD_DIR", str(folder))
    upd.UpdateController(settings)
    assert not os.path.exists(folder)
