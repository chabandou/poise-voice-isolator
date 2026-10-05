"""
Logging Configuration Module

Console output only in development; file logging (Linux only) is
always available via ensure_file_logging() so weak machines can be
diagnosed remotely. File handlers survive set_tui_mode(True).

The log file location is resolved robustly so it works in the Nuitka
onefile binary and across Linux distros:

1. Explicit ``log_file`` (CLI ``--log-file`` / ``POISE_LOG_FILE``) wins.
2. ``~/.local/share/poise/logs/poise.log`` (legacy default, kept stable
   so support instructions stay valid).
3. XDG locations (``XDG_STATE_HOME``, ``XDG_DATA_HOME``,
   ``XDG_RUNTIME_DIR``) for distros/containers with non-standard homes.
4. A per-user ``/tmp`` fallback (``/tmp/poise-<uid>/logs``) so a
   read-only/locked-down home or a root-owned leftover can never leave
   the user with no log file at all.

``ensure_file_logging()`` never raises: it walks the candidates in
order and returns the first writable location, or ``None``.
"""
import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Iterator, Optional, Union

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


def _is_frozen() -> bool:
    """True inside a frozen/bundled binary (PyInstaller, cx_Freeze, Nuitka).

    Nuitka does not set ``sys.frozen``; compiled modules instead carry a
    ``__compiled__`` global, so check for that too.
    """
    if getattr(sys, "frozen", False):
        return True
    if getattr(sys, "_MEIPASS", None) is not None:
        return True
    return "__compiled__" in globals()


def _safe_home() -> Path:
    """Best-effort user home directory; never raises.

    ``Path.home()`` can raise ``RuntimeError`` (no ``HOME``, no passwd
    entry -- e.g. minimal containers, systemd DynamicUser) or resolve to
    ``/`` when ``HOME`` is empty (desktop-file/sudo quirks on some
    distros). Fall back gracefully so log setup never crashes.
    """
    home = os.environ.get("HOME")
    if home and home.strip() and home != "/":
        return Path(home)
    try:
        resolved = Path.home()
        if str(resolved) and str(resolved) != "/":
            return resolved
    except Exception:
        pass
    try:
        import pwd

        pw_home = pwd.getpwuid(os.geteuid()).pw_dir
        if pw_home and pw_home.strip() and pw_home != "/":
            return Path(pw_home)
    except Exception:
        pass
    return Path("/tmp")


def default_log_dir() -> Path:
    """Default log directory: ~/.local/share/poise/logs (fixed, easy to support)."""
    try:
        return _safe_home() / ".local" / "share" / "poise" / "logs"
    except Exception:
        return Path("/tmp") / "poise-logs"


def _per_user_tmp_dir() -> Path:
    """Per-user /tmp dir (avoids collisions/root-owned leftovers in /tmp)."""
    try:
        uid = os.geteuid()
        suffix = f"poise-{uid}"
    except Exception:
        try:
            import getpass

            suffix = f"poise-{getpass.getuser()}"
        except Exception:
            suffix = "poise-logs"
    return Path("/tmp") / suffix / "logs"


def candidate_log_dirs() -> list[Path]:
    """Ordered, de-duplicated candidate log directories (first writable wins)."""
    candidates: list[Path] = []
    try:
        candidates.append(default_log_dir())
    except Exception:
        pass
    for env_var, sub in (
        ("XDG_STATE_HOME", "poise/logs"),
        ("XDG_DATA_HOME", "poise/logs"),
        ("XDG_RUNTIME_DIR", "poise/logs"),
    ):
        value = os.environ.get(env_var)
        if value and value.strip():
            try:
                candidates.append(Path(value) / sub)
            except Exception:
                continue
    candidates.append(_per_user_tmp_dir())
    # De-duplicate while preserving order.
    seen: set[str] = set()
    unique: list[Path] = []
    for cand in candidates:
        key = str(cand)
        if key not in seen:
            seen.add(key)
            unique.append(cand)
    return unique


def get_log_file_path() -> Optional[str]:
    """Path of the active file log, or None if file logging is off."""
    return _log_file_path


def get_file_handler() -> Optional[logging.Handler]:
    """The shared file handler, if file logging is active."""
    return _file_handler


def _coerce_level(level: Union[int, str]) -> int:
    if isinstance(level, int):
        return level
    return getattr(logging, str(level).upper(), logging.INFO)


def _dir_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception:
        return False
    return os.access(str(path), os.W_OK | os.X_OK)


def _try_attach_log_file(
    path: Path,
    level: Union[int, str],
    max_bytes: int,
    backup_count: int,
) -> Optional[str]:
    """Create the handler for *path* and attach it. Returns path or None."""
    global _file_handler, _log_file_path
    try:
        if not _dir_writable(path.parent):
            return None
        if path.exists() and not path.is_file():
            return None
        if path.exists() and not os.access(str(path), os.W_OK):
            return None
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
        try:
            handler.flush()
        except Exception:
            pass
        return _log_file_path
    except Exception:
        try:
            handler.close()  # type: ignore[possibly-undefined]
        except Exception:
            pass
        return None


def _iter_candidate_files(
    log_file: Optional[Union[str, Path]],
    log_dir: Optional[Union[str, Path]],
) -> Iterator[Path]:
    """Yield candidate log files in priority order."""
    if log_file is not None:
        try:
            yield Path(log_file)
        except Exception:
            pass
    if log_dir is not None:
        try:
            yield (Path(log_dir) / "poise.log")
        except Exception:
            pass
    # Default/XDG//tmp candidates are Linux-only (explicit paths are
    # honoured anywhere, e.g. for tests).
    if not _is_linux():
        return
    for directory in candidate_log_dirs():
        yield directory / "poise.log"


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
    Never raises: walks explicit path -> default dir -> XDG dirs ->
    per-user /tmp and returns the first writable location, or None.

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

    explicit = log_file is not None or log_dir is not None
    if not explicit and not _is_linux():
        return None

    for path in _iter_candidate_files(log_file, log_dir):
        result = _try_attach_log_file(path, level, max_bytes, backup_count)
        if result is not None:
            return result

    _file_handler = None
    _log_file_path = None
    return None


def setup_file_logging_from_env(
    level: Union[int, str] = logging.INFO,
) -> Optional[str]:
    """Enable file logging from ``POISE_*`` env vars (binary/TUI entry points).

    Honours ``POISE_DISABLE_FILE_LOG=1``, ``POISE_LOG_FILE``,
    ``POISE_LOG_DIR`` and ``POISE_LOG_LEVEL``. Never raises.
    """
    try:
        if os.environ.get("POISE_DISABLE_FILE_LOG") == "1":
            return None
        log_file = os.environ.get("POISE_LOG_FILE") or None
        log_dir = os.environ.get("POISE_LOG_DIR") or None
        log_level = os.environ.get("POISE_LOG_LEVEL", level)
        return ensure_file_logging(
            log_file=log_file, log_dir=log_dir, level=log_level
        )
    except Exception:
        return None


def add_log_args(parser):
    """Attach ``--log-file/--log-level/--verbose/--no-file-log`` to a parser.

    Shared by the CLI and the TUI/binary entry points so flags behave the
    same everywhere.
    """
    parser.add_argument('--log-file', type=str, default=None,
                        help='Write a diagnostic log file (Linux default: ~/.local/share/poise/logs/poise.log)')
    parser.add_argument('--log-level', type=str, default='INFO',
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                        help='File log verbosity (default: INFO; DEBUG for per-frame detail)')
    parser.add_argument('--verbose', action='store_true',
                        help='Shortcut for --log-level DEBUG')
    parser.add_argument('--no-file-log', action='store_true',
                        help='Disable file logging')
    return parser


def ensure_from_log_args(args, default_level: Union[int, str] = 'INFO') -> Optional[str]:
    """Enable file logging from parsed args (flags win, ``POISE_*`` env fills gaps)."""
    try:
        if getattr(args, 'no_file_log', False):
            return None
        if os.environ.get("POISE_DISABLE_FILE_LOG") == "1":
            return None
        log_file = getattr(args, 'log_file', None) or os.environ.get("POISE_LOG_FILE") or None
        if getattr(args, 'verbose', False):
            level: Union[int, str] = 'DEBUG'
        else:
            level = getattr(args, 'log_level', None) or os.environ.get("POISE_LOG_LEVEL", default_level)
        return ensure_file_logging(log_file=log_file, level=level)
    except Exception:
        return None


def announce_log_path(path: Optional[str]) -> None:
    """Print the active log path (call before a fullscreen TUI takes over)."""
    if path:
        try:
            print(f"Logging to {path}", flush=True)
        except Exception:
            pass


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
        if not enabled and not _is_frozen():
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
    if not _is_frozen() and not _tui_mode:
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
