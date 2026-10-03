"""Tests for Linux-only file logging (no system changes)."""
import logging
import sys

import pytest

from stream_denoiser import logging_config
from stream_denoiser.logging_config import (
    default_log_dir,
    ensure_file_logging,
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


def test_status_line_shows_only_warnings_and_above():
    mod = _import_status_line_without_textual()

    class _FakeStatusLine:
        def __init__(self):
            self.calls = []

        def notify(self, message, level="info"):
            self.calls.append((level, message))

    widget = _FakeStatusLine()
    handler = mod.TUIStatusHandler(widget)
    logger = logging.getLogger("test-poise-status-line")
    logger.handlers = []
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)

    logger.debug("debug chatter")
    logger.info("routine info")
    logger.warning("something odd")
    logger.error("boom")
    logger.critical("critical boom")

    levels = [level for level, _ in widget.calls]
    assert "info" not in levels
    assert "debug" not in levels
    assert "warning" in levels
    assert levels.count("error") == 2  # error + critical mapped to error
    assert any("boom" in msg for _, msg in widget.calls)
