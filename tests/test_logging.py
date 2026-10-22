"""Tests for Linux-only file logging (no system changes)."""
import logging
import os
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
    logging_config._reset_memory_log_for_tests()
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


# Without an explicit path, file logging is Linux-only: elsewhere
# ensure_file_logging() returns None and the default/XDG//tmp chain
# is never walked.
_linux_only = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="default log locations are Linux-only")


@_linux_only
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


_skip_as_root = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root ignores directory permissions (e.g. CI containers)")


@_linux_only
@_skip_as_root
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


@_linux_only
@_skip_as_root
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


@_skip_as_root
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


@_linux_only
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
    assert "aad_total" in diag


def _record(msg, level=logging.INFO, name="stream_denoiser"):
    return logging.makeLogRecord({"name": name, "levelno": level,
                                  "levelname": logging.getLevelName(level),
                                  "msg": msg, "args": None})


def test_log_lines_for_the_events_box():
    """One short line per record, or none when the screen says it
    already; a periodic sync summary is one sticky line."""
    from stream_denoiser.tui.log_events import SYNC_KEY, LogLine, clean

    for covered in ("perf: frames=1 avg_ms=1.0", "engine ready: model=x",
                    "run stop: frames=1", "backend: pipewire (1.4)",
                    "Default sink: Poise_Isolator (was alsa)",
                    "DeepFilterNet3 model loaded with optimizations"):
        assert clean(_record(covered)) is None, covered
    assert clean(_record("something", logging.DEBUG)) is None

    assert clean(_record(
        "sync: latency=76.0ms (delay=3648 engine=1536 samples) wet=900 "
        "dry=0 late=2 skipped=0")) == LogLine(
            "sync  latency 76 ms · 2 late", "info", SYNC_KEY)
    assert clean(_record(
        "sync: 12 frames (120 ms) played unprocessed; longest gap 40 ms"
    )) == LogLine("sync  12 frames (120 ms) played unprocessed", "info",
                  None)
    assert clean(_record("Processing error: boom\nTraceback ...",
                         logging.ERROR)) == LogLine(
        "Processing error: boom", "error", None)


def test_the_tui_shows_its_log_and_lets_go_of_it():
    pytest.importorskip("textual.app")
    import asyncio
    from stream_denoiser.logging_config import _forward_handlers, get_logger
    from stream_denoiser.tui import app as app_mod
    from stream_denoiser.tui.widgets import EventsPanel

    class Bare(app_mod.PoiseApp):
        # Relative paths resolve next to the subclass's module.
        CSS_PATH = __import__("pathlib").Path(app_mod.__file__).with_name(
            "styles.tcss")

        def _setup_logging(self):
            pass

        def _setup_cleanup_handlers(self):
            pass

        def _load_model(self):
            self.engine = True

    async def run():
        app = Bare()
        app.audio.launch = lambda: None
        async with app.run_test() as pilot:
            await pilot.pause()
            log = get_logger("stream_denoiser.backends.pipewire_backend")
            for n in (1, 2):
                log.info(f"sync: latency=7{n}.0ms dry=0 late=0")
            log.warning("sink busy, retry")
            log.warning("sink busy, retry")
            log.info("perf: frames=1")
            await pilot.pause()
            events = list(app.query_one(EventsPanel).events)
            assert events[0].message == "sink busy, retry"
            assert events[0].count == 2 and events[0].tag == "warn"
            syncs = [e for e in events if e.message.startswith("sync")]
            assert [e.message for e in syncs] == ["sync  latency 72 ms"]
            assert not any("perf" in e.message for e in events)
            handler = app._log_handler
            await pilot.press("q")
        assert handler not in _forward_handlers
        assert handler not in log.handlers

    asyncio.run(run())


_REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]


def _run_crashing_child(code: str):
    """Run `code` in a fresh interpreter (a real abort must not kill pytest)."""
    import subprocess
    import os as _os
    env = dict(_os.environ, PYTHONPATH=str(_REPO_ROOT))
    return subprocess.run(
        [sys.executable, "-c", code], cwd=str(_REPO_ROOT), env=env,
        capture_output=True, text=True, timeout=120,
    )


@pytest.mark.skipif(not sys.platform.startswith("linux"),
                    reason="crash log is part of Linux file logging")
def test_crash_traceback_records_python_stack_on_abort(tmp_path):
    """A native abort (e.g. glibc heap-corruption) leaves every thread's
    Python stack in poise-crash.log, next to poise.log."""
    import signal
    log = tmp_path / "poise.log"
    code = (
        "import os, threading\n"
        "from stream_denoiser.logging_config import "
        "ensure_file_logging, enable_crash_traceback\n"
        f"assert ensure_file_logging(log_file={str(log)!r})\n"
        "assert enable_crash_traceback()\n"
        "def worker_that_crashes():\n"
        "    os.abort()\n"
        "t = threading.Thread(target=worker_that_crashes, name='proc-thread')\n"
        "t.start(); t.join()\n"
    )
    proc = _run_crashing_child(code)
    # faulthandler re-raises the signal, so the core dump is still produced
    assert proc.returncode == -signal.SIGABRT, proc.stderr
    crash = (tmp_path / "poise-crash.log").read_text()
    assert "--- poise start" in crash
    assert "worker_that_crashes" in crash


@pytest.mark.skipif(not sys.platform.startswith("linux"),
                    reason="crash log is part of Linux file logging")
def test_crash_traceback_off_without_file_logging():
    code = (
        "from stream_denoiser.logging_config import enable_crash_traceback\n"
        "assert enable_crash_traceback() is None\n"
    )
    proc = _run_crashing_child(code)
    assert proc.returncode == 0, proc.stderr


# -- in-memory session log (GUI Logs page) ---------------------------------------
@pytest.fixture()
def memory_log():
    handler = logging_config.enable_memory_log()
    yield handler
    logging_config._reset_memory_log_for_tests()


def test_memory_log_reaches_existing_and_late_loggers():
    early = get_logger("test-poise-memory-early")      # exists before enabling
    memory_log = logging_config.enable_memory_log()
    early.info("from-early")
    late = get_logger("test-poise-memory-late")         # created after
    late.warning("from-late")
    _, entries = memory_log.entries_since(0)
    texts = [text for _, text in entries]
    assert any("from-early" in t for t in texts)
    assert any("from-late" in t and "[WARNING]" in t for t in texts)
    assert logging_config.get_memory_handler() is memory_log
    assert logging_config.enable_memory_log() is memory_log   # idempotent


def test_memory_log_returns_only_new_entries(memory_log):
    logger = get_logger("test-poise-memory-seq")
    logger.info("one")
    seq, first = memory_log.entries_since(0)
    logger.error("two")
    seq2, second = memory_log.entries_since(seq)
    assert seq2 == seq + 1
    assert [(lvl, "two" in text) for lvl, text in second] == [(logging.ERROR, True)]
    assert memory_log.entries_since(seq2) == (seq2, [])
    assert memory_log.text().endswith(second[0][1])


def test_memory_log_skips_debug_and_stays_bounded():
    handler = logging_config.MemoryLogHandler(capacity=3)
    logger = logging.getLogger("test-poise-memory-bounded")
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        logger.debug("hidden")
        for i in range(5):
            logger.info(f"line-{i}")
        seq, entries = handler.entries_since(0)
        assert seq == 5
        assert [t.split(": ")[-1] for _, t in entries] == ["line-2", "line-3", "line-4"]
    finally:
        logger.removeHandler(handler)


def test_memory_log_detaches_on_reset():
    handler = logging_config.enable_memory_log()
    logger = get_logger("test-poise-memory-reset")
    assert handler in logger.handlers
    logging_config._reset_memory_log_for_tests()
    assert handler not in logger.handlers
    assert logging_config.get_memory_handler() is None


def test_qt_messages_reach_the_session_log_without_font_noise():
    """Qt's own warnings used to bypass the log (stderr only); the benign
    QFont::setPointSize(-1) one is dropped."""
    pytest.importorskip("PyQt6.QtCore")
    from PyQt6.QtCore import qInstallMessageHandler, qWarning
    from stream_denoiser.gui import install_qt_message_handler
    memory = logging_config.enable_memory_log()
    install_qt_message_handler()
    try:
        qWarning("poise-qt-warning-probe")
        qWarning("QFont::setPointSize: Point size <= 0 (-1), must be greater than 0")
    finally:
        qInstallMessageHandler(None)
    text = memory.text()
    assert "[WARNING] qt: poise-qt-warning-probe" in text
    assert "setPointSize" not in text
