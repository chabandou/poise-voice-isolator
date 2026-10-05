"""Tests for Linux-only file logging (no system changes)."""
import logging
import sys

import pytest

from stream_denoiser import logging_config
from stream_denoiser.logging_config import (
    add_log_args,
    candidate_log_dirs,
    default_log_dir,
    ensure_file_logging,
    ensure_from_log_args,
    get_log_file_path,
    get_logger,
    set_tui_mode,
)


@pytest.fixture(autouse=True)
def _clean_logging():
    yield
    logging_config._reset_file_logging_for_tests()
    # Leave TUI mode off for other tests
    set_tui_mode(False)


def test_explicit_log_file_writes_record(tmp_path):
    path = tmp_path / "poise.log"
    result = ensure_file_logging(log_file=path)
    assert result == str(path)
    assert get_log_file_path() == str(path)

    logger = get_logger("test-poise-logging-explicit")
    logger.info("hello-weak-pc")
    for h in logger.handlers:
        try:
            h.flush()
        except Exception:
            pass
    assert "hello-weak-pc" in path.read_text()


def test_file_handler_survives_tui_mode(tmp_path):
    ensure_file_logging(log_file=tmp_path / "poise.log")
    logger = get_logger("test-poise-logging-tui")
    assert any(isinstance(h, logging.FileHandler) for h in logger.handlers)

    set_tui_mode(True)
    assert any(isinstance(h, logging.FileHandler) for h in logger.handlers)
    # Console handlers must be gone in TUI mode
    assert not any(
        isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.FileHandler)
        for h in logger.handlers
    )


def test_late_logger_gets_file_handler(tmp_path):
    ensure_file_logging(log_file=tmp_path / "poise.log")
    logger = get_logger("test-poise-logging-late")
    assert any(isinstance(h, logging.FileHandler) for h in logger.handlers)


def test_non_linux_no_file_without_explicit(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert ensure_file_logging() is None
    assert get_log_file_path() is None


def test_default_log_dir_is_fixed_share_path():
    assert default_log_dir().as_posix().endswith(".local/share/poise/logs")


def test_empty_home_still_produces_writable_log(monkeypatch, tmp_path):
    """HOME='' (desktop-file/sudo quirks) must not log under '/.local'."""
    monkeypatch.setenv("HOME", "")
    path = ensure_file_logging()
    assert path, "expected a fallback log file, got None"
    assert not path.startswith("/.local/"), path
    logger = get_logger("test-poise-logging-empty-home")
    logger.warning("empty-home-line")
    for h in logger.handlers:
        h.flush()
    from pathlib import Path
    assert "empty-home-line" in Path(path).read_text()


def test_readonly_home_falls_back_to_per_user_tmp(monkeypatch, tmp_path):
    """Read-only home with no XDG set -> per-user /tmp dir, never None."""
    ro_home = tmp_path / "ro-home"
    ro_home.mkdir()
    ro_home.chmod(0o555)
    monkeypatch.setenv("HOME", str(ro_home))
    for var in ("XDG_STATE_HOME", "XDG_DATA_HOME", "XDG_RUNTIME_DIR"):
        monkeypatch.delenv(var, raising=False)
    try:
        path = ensure_file_logging()
    finally:
        ro_home.chmod(0o755)
    assert path, "expected a fallback log file, got None"
    assert str(ro_home) not in path
    # Per-user dir avoids collisions with root-owned /tmp/poise-logs leftovers.
    assert "/tmp/poise-" in path, path


def test_readonly_home_prefers_xdg_state_home(monkeypatch, tmp_path):
    ro_home = tmp_path / "ro-home"
    ro_home.mkdir()
    ro_home.chmod(0o555)
    xdg_state = tmp_path / "xdg-state"
    xdg_state.mkdir()
    monkeypatch.setenv("HOME", str(ro_home))
    monkeypatch.setenv("XDG_STATE_HOME", str(xdg_state))
    try:
        path = ensure_file_logging()
    finally:
        ro_home.chmod(0o755)
    assert path and path.startswith(str(xdg_state)), path


def test_unwritable_explicit_path_falls_back_on_linux(tmp_path):
    """A bad --log-file must not silently disable logging on Linux."""
    if not sys.platform.startswith("linux"):
        pytest.skip("Linux-only fallback chain")
    bad = tmp_path / "ro-dir"
    bad.mkdir()
    bad.chmod(0o555)
    try:
        path = ensure_file_logging(log_file=bad / "poise.log")
    finally:
        bad.chmod(0o755)
    assert path and not path.startswith(str(bad)), path


def test_candidate_dirs_cover_xdg_and_tmp(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    dirs = [str(d) for d in candidate_log_dirs()]
    assert any(str(tmp_path / "state") in d for d in dirs)
    assert any(d.startswith("/tmp/poise-") for d in dirs)


def test_log_args_roundtrip_writes_file(tmp_path):
    """Shared --log-file/--level flags work via ensure_from_log_args."""
    import argparse
    parser = argparse.ArgumentParser()
    add_log_args(parser)
    log_file = tmp_path / "args.log"
    args = parser.parse_args(
        ["--log-file", str(log_file), "--log-level", "DEBUG"]
    )
    path = ensure_from_log_args(args)
    assert path == str(log_file)
    logger = get_logger("test-poise-logging-args")
    logger.debug("args-debug-line")
    for h in logger.handlers:
        h.flush()
    assert "args-debug-line" in log_file.read_text()


def test_no_file_log_disables_file_logging(tmp_path):
    import argparse
    parser = argparse.ArgumentParser()
    add_log_args(parser)
    args = parser.parse_args(["--no-file-log"])
    assert ensure_from_log_args(args) is None
    assert get_log_file_path() is None


def test_processor_diagnostics_exposes_resampler():
    from stream_denoiser.processor import DenoiserAudioProcessor
    from stream_denoiser.engines.base import DenoiseEngine
    import numpy as np

    class _FakeEngine(DenoiseEngine):
        name = "fake"
        required_frame_size = 480

        def __init__(self):
            self.speech_prob = None

        def process_frame(self, frame):
            return frame

        def reset(self):
            pass

        def close(self):
            pass

    proc = DenoiserAudioProcessor(_FakeEngine(), frame_size=480)
    diag = proc.get_diagnostics()
    assert diag["frame_count"] == 0
    assert diag["resampler_active"] is False
    assert "vad_total" in diag


def _import_status_line_without_textual():
    """Import the status_line module with minimal textual stubs."""
    import types
    if "stream_denoiser.tui.widgets.status_line" in sys.modules:
        return sys.modules["stream_denoiser.tui.widgets.status_line"]
    if "textual.widgets" not in sys.modules:
        textual = types.ModuleType("textual")
        widgets = types.ModuleType("textual.widgets")

        class Static:
            def __init__(self, *args, **kwargs):
                pass

        widgets.Static = Static
        reactive_mod = types.ModuleType("textual.reactive")

        class _Reactive:
            def __new__(cls, default=None):
                return default

            def __class_getitem__(cls, item):
                return cls

        reactive_mod.reactive = _Reactive
        textual.widgets = widgets
        sys.modules["textual"] = textual
        sys.modules["textual.widgets"] = widgets
        sys.modules["textual.reactive"] = reactive_mod
    # Load status_line.py directly by path: the real
    # stream_denoiser.tui/__init__ imports the Textual app (not installed
    # here), which we don't need.
    import importlib.util
    from pathlib import Path
    name = "stream_denoiser.tui.widgets.status_line"
    if name in sys.modules:
        return sys.modules[name]
    path = (
        Path(__file__).resolve().parent.parent
        / "stream_denoiser" / "tui" / "widgets" / "status_line.py"
    )
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_status_line_never_receives_log_records():
    """The status line is notify()-only: no logging.Handler lives in the
    widget module and no log-to-status wiring remains in the TUI app."""
    mod = _import_status_line_without_textual()
    assert not any(
        isinstance(obj, type) and issubclass(obj, logging.Handler)
        for obj in vars(mod).values()
    ), "status_line module must not define a logging handler"

    from pathlib import Path
    app_src = (
        Path(__file__).resolve().parent.parent
        / "stream_denoiser" / "tui" / "app.py"
    ).read_text()
    for token in ("TUIStatusHandler", "log_handler", "set_widget"):
        assert token not in app_src, f"app.py still references {token}"

    # notify() remains the only way to update the widget: log traffic on
    # the app logger leaves the widget untouched.
    widget = mod.StatusLine()
    widget.notify("Starting audio processing...")
    assert widget.current_message == "Starting audio processing..."
    logger = logging.getLogger("test-poise-status-line-unwired")
    logger.handlers = []
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    logger.warning("something odd")
    logger.error("boom")
    assert widget.current_message == "Starting audio processing..."
