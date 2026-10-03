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
