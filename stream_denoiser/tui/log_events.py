"""
The app's log in the events box.

Every record still goes to the log file whole. On screen each becomes one
short line, or nothing when the screen already says it more cleanly:
the perf snapshots (box 1 shows those numbers), the lines the app's own
notes cover (model ready, session start and stop, routing), and the
model loading chatter. A backend's periodic "sync:" summary is one line
updated in place rather than a new line every few seconds.

Records arrive from any thread (the audio process's are re-emitted on
the AudioHost reader thread), so the handler only posts a message.
"""
import logging
import re
from typing import Callable, NamedTuple, Optional

# Said better elsewhere on screen (prefix of the record's message).
_COVERED = (
    "perf:", "engine ready:", "session start:", "run start:", "run stop:",
    "backend:", "file log:", "Denoise engine:", "AAD enabled",
    "VAD enabled", "audio process started", "audio process ready", "gc:",
    "Model load failed", "Cannot start:", "Loading ", "RNNoise engine ready",
    # Routing: the "routed via ..." and "session stopped" notes.
    "Default sink:", "Set default sink", "Restored default sink",
    "Original default sink", "Created null sink", "Unloaded null sink",
    "Found null sink monitor", "Reusing existing null sink",
)
_COVERED_RE = re.compile(r"model loaded with optimizations$")
_PAIR_RE = re.compile(r"(\w+)=([-\d.]+)")

SYNC_KEY = "sync"
MAX_LEN = 120


class LogLine(NamedTuple):
    message: str
    level: str          # "info", "warning", "error"
    key: Optional[str]  # set: one line, updated in place


def _level(record: logging.LogRecord) -> str:
    if record.levelno >= logging.ERROR:
        return "error"
    if record.levelno >= logging.WARNING:
        return "warning"
    return "info"


def _sync_summary(text: str) -> str:
    """'latency=76.0ms (delay=...) wet=9 dry=0 late=2 ...' ->
    'sync  latency 76 ms · 2 late'."""
    pairs = dict(_PAIR_RE.findall(text))
    parts = []
    if "latency" in pairs:
        parts.append(f"latency {float(pairs['latency']):.0f} ms")
    for key, what in (("dry", "dry"), ("late", "late"),
                      ("dropped", "ms dropped"), ("stalls", "stalls")):
        try:
            if float(pairs.get(key, 0)) > 0:
                parts.append(f"{float(pairs[key]):.0f} {what}")
        except ValueError:
            pass
    return "sync  " + (" · ".join(parts) if parts else "ok")


def clean(record: logging.LogRecord) -> Optional[LogLine]:
    """The record's line for the events box, or None to leave it out."""
    if record.levelno < logging.INFO:
        return None
    try:
        text = record.getMessage()
    except Exception:
        return None
    lines = text.strip().splitlines()
    if not lines:
        return None
    text = lines[0].strip()
    if text.startswith(_COVERED) or _COVERED_RE.search(text):
        return None
    level = _level(record)
    key = None
    if text.startswith("sync: "):
        rest = text[len("sync: "):]
        if "=" in rest:
            if level == "info":
                # A periodic summary: one line, kept current.
                text, key = _sync_summary(rest), SYNC_KEY
            else:
                text = "sync  " + rest
        else:
            # An event ("12 frames (120 ms) played unprocessed; ..."):
            # the part before the details.
            text = "sync  " + rest.split(";")[0]
    if len(text) > MAX_LEN:
        text = text[:MAX_LEN - 1] + "…"
    return LogLine(text, level, key)


class EventLogHandler(logging.Handler):
    """Hands each record's clean line to ``post`` (any thread)."""

    def __init__(self, post: Callable[[LogLine], None]):
        super().__init__(logging.INFO)
        self._post = post

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = clean(record)
            if line is not None:
                self._post(line)
        except Exception:
            pass  # never log from a log handler
