"""
Logging Configuration Module

Console output only in development; file logging (Linux only) is
always available via ensure_file_logging() so weak machines can be
diagnosed remotely. File handlers survive set_tui_mode(True).
"""
import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional, Union

# Cache configured loggers to avoid duplicate handlers
_loggers: dict[str, logging.Logger] = {}

# Flag to indicate TUI mode (suppress console output when TUI is running)
_tui_mode: bool = False

# File-logging state (Linux only). A single shared RotatingFileHandler is
# attached to every logger obtained via get_logger().
_file_handler: Optional[logging.handlers.RotatingFileHandler] = None
_log_file_path: Optional[str] = None

DEFAULT_MAX_BYTES = 1_000_000  # 1 MB
DEFAULT_BACKUP_COUNT = 3


def _is_linux() -> bool:
    return sys.platform.startswith("linux")


def default_log_dir() -> Path:
    """Default log directory: ~/.local/share/poise/logs (fixed, easy to support)."""
    return Path.home() / ".local" / "share" / "poise" / "logs"


def get_log_file_path() -> Optional[str]:
    """Path of the active file log, or None if file logging is off."""
    return _log_file_path


def _coerce_level(level: Union[int, str]) -> int:
    if isinstance(level, int):
        return level
    return getattr(logging, str(level).upper(), logging.INFO)


def ensure_file_logging(
    log_file: Optional[Union[str, Path]] = None,
    log_dir: Optional[Union[str, Path]] = None,
    level: Union[int, str] = logging.INFO,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
) -> Optional[str]:
    """
    Enable file logging (Linux only) and attach it to all known loggers.

    Safe to call multiple times: the first call wins (same file reused).
    Never raises: on any failure (read-only home, /tmp fallback) returns None.

    Args:
        log_file: Explicit file path (honoured even on non-Linux, for tests).
        log_dir: Directory for the default poise.log (default: default_log_dir()).
        level: Handler level (default INFO; pass DEBUG via --verbose).
        max_bytes: Rotation size. backup_count: rotated files kept.

    Returns:
        Log file path, or None if file logging is disabled/unavailable.
    """
    global _file_handler, _log_file_path

    if _file_handler is not None and _log_file_path is not None:
        # Upgrade level if caller asked for more verbosity.
        wanted = _coerce_level(level)
        if wanted < _file_handler.level:
            _file_handler.setLevel(wanted)
            for logger in _loggers.values():
                if logger.level > wanted:
                    logger.setLevel(wanted)
        return _log_file_path

    explicit = log_file is not None
    if not explicit and not _is_linux():
        return None

    try:
        path = Path(log_file) if explicit else (Path(log_dir) if log_dir else default_log_dir()) / "poise.log"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            # Last resort for locked-down homes (still Linux-only unless explicit).
            if not explicit and not _is_linux():
                return None
            path = Path("/tmp") / "poise-logs" / "poise.log"
            path.parent.mkdir(parents=True, exist_ok=True)

        handler = logging.handlers.RotatingFileHandler(
            str(path), maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        handler.setLevel(_coerce_level(level))
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )
        handler.setFormatter(formatter)

        _file_handler = handler
        _log_file_path = str(path)

        for logger in _loggers.values():
            if handler not in logger.handlers:
                logger.addHandler(handler)
            if logger.level > handler.level:
                logger.setLevel(handler.level)
        return _log_file_path
    except Exception:
        _file_handler = None
        _log_file_path = None
        return None


def _reset_file_logging_for_tests() -> None:
    """Detach and close the shared file handler (tests only)."""
    global _file_handler, _log_file_path
    if _file_handler is not None:
        for logger in _loggers.values():
            try:
                logger.removeHandler(_file_handler)
            except Exception:
                pass
        try:
            _file_handler.close()
        except Exception:
            pass
    _file_handler = None
    _log_file_path = None


def set_tui_mode(enabled: bool) -> None:
    """Enable/disable TUI mode. Suppresses console output; file logs are kept."""
    global _tui_mode
    _tui_mode = enabled

    # Update existing loggers (file handlers are always preserved)
    for logger in _loggers.values():
        for handler in logger.handlers[:]:
            if isinstance(handler, logging.FileHandler):
                continue
            if isinstance(handler, logging.StreamHandler) and handler.stream in (sys.stdout, sys.stderr):
                logger.removeHandler(handler)
        if not enabled and not getattr(sys, 'frozen', False):
            # Re-add console handler if leaving TUI mode
            handler = logging.StreamHandler(sys.stdout)
            handler.setLevel(logging.DEBUG)
            formatter = logging.Formatter('[%(levelname)s] %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """
    Get a configured logger for the given module name.

    In frozen (Nuitka/exe) builds, console logging is disabled to avoid
    console window pop-ups, but file logging (ensure_file_logging) still
    applies. When TUI mode is enabled, console output is suppressed but
    file handlers are preserved.

    Args:
        name: Logger name (typically __name__ of the calling module)

    Returns:
        Configured Logger instance
    """
    if name in _loggers:
        logger = _loggers[name]
        # Attach the shared file handler to pre-existing loggers created
        # before ensure_file_logging() was called.
        if _file_handler is not None and _file_handler not in logger.handlers:
            logger.addHandler(_file_handler)
            if logger.level > _file_handler.level:
                logger.setLevel(_file_handler.level)
        return logger

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # Prevent propagation to root logger to avoid duplicate logs
    logger.propagate = False

    # Only add console handler in development (not frozen builds) and not in TUI mode
    if not getattr(sys, 'frozen', False) and not _tui_mode:
        if not logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setLevel(logging.DEBUG)
            formatter = logging.Formatter(
                '[%(levelname)s] %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
    else:
        # Frozen build or TUI mode: add null handler to suppress all output
        if not logger.handlers:
            logger.addHandler(logging.NullHandler())

    # File logging always applies (Linux Nuitka onefile included).
    if _file_handler is not None and _file_handler not in logger.handlers:
        logger.addHandler(_file_handler)
        if logger.level > _file_handler.level:
            logger.setLevel(_file_handler.level)

    _loggers[name] = logger
    return logger
