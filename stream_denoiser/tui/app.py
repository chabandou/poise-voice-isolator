"""
Poise Voice Isolator TUI App

Main Textual application with audio processing integration.

The screen (the "Monitor" design): box 1 shows the signal in and out and
the session's numbers, box 2 the isolation controls, box 3 the output
device, box 4 recent events; the number keys focus them.
"""
import asyncio
import atexit
import logging
import signal
import time
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.message import Message
from textual.containers import Horizontal, Vertical
from textual.binding import Binding

from .log_events import EventLogHandler, LogLine
from . import palette as P
from .settings import ATTEN_MAX_DB, ATTEN_MIN_DB, AAD_MAX_DB, AAD_MIN_DB, \
    TuiSettings
from .widgets.device_list import DeviceListItem
from .widgets import (
    Box, DeviceList, EventsPanel, IsolationPanel, KeyBar, LevelScope,
    SessionStats, SignalPanel,
)
from ..audio_host import AudioHost
from ..constants import DEFAULT_AAD_THRESHOLD_DB, DEFAULT_MODEL, \
    DEFAULT_SAMPLE_RATE, MODEL_INFO, MSG_MUSIC_DISCLAIMER
from ..logging_config import set_tui_mode, get_log_file_path

# dB per key press.
STRENGTH_STEP_DB = 5.0
THRESHOLD_STEP_DB = 5.0
# Out of the box: full reduction (the GUI dial's default).
DEFAULT_STRENGTH_DB = ATTEN_MIN_DB


class LogEvent(Message):
    """A log record's line for the events box (log_events.py), posted
    from whichever thread logged it."""

    def __init__(self, line: LogLine) -> None:
        super().__init__()
        self.line = line


class AudioEvent(Message):
    """An event from the audio process (see audio_host), posted to the app
    from the host's reader thread."""

    def __init__(self, data: dict) -> None:
        super().__init__()
        self.data = data


def _clock(seconds: float) -> str:
    mins, secs = divmod(int(seconds), 60)
    hours, mins = divmod(mins, 60)
    return f"{hours}:{mins:02d}:{secs:02d}" if hours else f"{mins}:{secs:02d}"


class PoiseApp(App):
    """Poise Voice Isolator TUI Application."""

    TITLE = "Poise"
    CSS_PATH = "styles.tcss"
    ENABLE_COMMAND_PALETTE = False

    BINDINGS = [
        Binding("space", "toggle_processing", "Start/Stop", priority=True),
        Binding("1", "focus_box(1)", "Focus box", show=False),
        Binding("2", "focus_box(2)", "Focus box", show=False),
        Binding("3", "focus_box(3)", "Focus box", show=False),
        Binding("4", "focus_box(4)", "Focus box", show=False),
        Binding("m", "cycle_model", "Model"),
        Binding("t", "cycle_theme", "Theme"),
        Binding("r", "refresh_devices", "Refresh"),
        Binding("minus", "decrease_threshold", "Skip below -", show=False),
        Binding("plus", "increase_threshold", "Skip below +", show=False),
        Binding("escape", "quit", "Quit", show=False),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, model: Optional[str] = None, **kwargs):
        """model: an explicit choice (--model) for this session only;
        None uses the last model picked, else the default."""
        # Colors first: the stylesheet is built in App.__init__.
        self.settings = TuiSettings()
        self._settings_stamp = self._read_settings_stamp()
        self._color_problems = P.apply(self.settings.theme,
                                       self.settings.colors)
        super().__init__(**kwargs)
        self.model = model or self._saved_model()
        self.is_processing = False
        self.engine = None
        self.onnx_session = None  # Backward-compat alias (unused for rnnoise)
        self.linux_router = None
        self.backend: Optional[str] = None  # "pipewire" or "pulse", per run
        # The audio loop runs in its own process (own GIL and garbage
        # collector), spawned at mount so Start does not wait for imports.
        self.audio = AudioHost(on_event=self._post_audio_event)
        self.start_time = 0.0
        self._audio_error: Optional[str] = None
        self._cleanup_done = False
        self._last_perf_log = 0.0
        # Where the current burst of strength/threshold presses started.
        self._burst_from: dict = {}
        self._idle_backend: Optional[str] = None
        self._setup_logging()
        self._setup_cleanup_handlers()

    def _setup_logging(self) -> None:
        """File logging on Linux; no console output under the TUI.

        The events box shows the app's notes (``note()``) and, from mount,
        its log cleaned up to one short line per record (log_events.py);
        raw records and tracebacks stay in the file.
        """
        import logging
        import sys

        # Enable file logging first (Linux only; no-op elsewhere) so the
        # shared file handler exists before console output is suppressed.
        # Entry points (poise_tui.py / cli.py) already set this up and
        # announced the path; this is a no-op safety net for direct
        # PoiseApp() use.
        if sys.platform.startswith("linux"):
            from ..logging_config import setup_file_logging_from_env
            setup_file_logging_from_env()

        # Enable TUI mode to suppress console logging (keeps file handlers)
        set_tui_mode(True)

        # Get the stream_denoiser logger
        logger = logging.getLogger('stream_denoiser')
        # Keep it file-only: drop console handlers, keep file handlers, and
        # attach the shared file handler in case this logger predates it.
        # The events box's handler is attached at mount (_show_log).
        logger.propagate = False
        logger.handlers = [
            h for h in logger.handlers if isinstance(h, logging.FileHandler)
        ]
        try:
            from ..logging_config import get_file_handler as _get_shared_fh
            _shared_fh = _get_shared_fh()
            if _shared_fh is not None and _shared_fh not in logger.handlers:
                logger.addHandler(_shared_fh)
        except Exception:
            pass
        # Respect --verbose (file handler at DEBUG): don't filter debug out.
        try:
            _levels = [h.level for h in logger.handlers
                       if isinstance(h, logging.FileHandler)]
            logger.setLevel(min(_levels) if _levels else logging.INFO)
        except Exception:
            logger.setLevel(logging.INFO)
    
    def _setup_cleanup_handlers(self) -> None:
        """Set up signal handlers and atexit hook for graceful cleanup."""
        # Register atexit handler for cleanup on normal exit
        atexit.register(self._emergency_cleanup)
        
        # Register signal handlers for abrupt termination
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            try:
                signal.signal(sig, self._signal_handler)
            except (OSError, ValueError):
                # Some signals may not be available on all platforms
                pass
    
    def _signal_handler(self, signum, frame) -> None:
        """Handle termination signals."""
        self._emergency_cleanup()
        # Re-raise signal to allow normal termination
        signal.signal(signum, signal.SIG_DFL)
        signal.raise_signal(signum)
    
    def _emergency_cleanup(self) -> None:
        """
        Emergency cleanup for when the app is terminated abruptly.
        Restores original audio sink and removes the virtual null sink.
        """
        if self._cleanup_done:
            return
        self._cleanup_done = True

        # End the audio process (its session restores the routing it set)
        try:
            self.audio.shutdown(timeout=1.0)
        except Exception:
            pass

        # Restore audio routing
        if self.linux_router:
            try:
                self.linux_router.restore_original_sink()
            except Exception:
                pass
            self.linux_router = None
    
    def get_line_filters(self):
        """Drop Textual's ANSI→truecolor rewrite so `ansi_default`
        backgrounds reach the terminal untouched.

        Every rendered line otherwise passes through ANSIToTruecolor,
        which maps the terminal-default background to the static MONOKAI
        dark color — repainting the dark rectangle `ansi_default` is meant
        to remove. Our palette is truecolor hex throughout (only the base
        background uses an ANSI color), so nothing else changes.
        """
        try:
            from textual.filter import ANSIToTruecolor
        except ImportError:
            return super().get_line_filters()
        return [
            f for f in super().get_line_filters()
            if not isinstance(f, ANSIToTruecolor)
        ]


    def get_css_variables(self) -> dict:
        """Textual's variables plus the palette's ($poise-<role>)."""
        return {**super().get_css_variables(), **P.css_variables()}

    def action_cycle_theme(self) -> None:
        """Next built-in theme (the user's own colors stay on top)."""
        name = P.next_theme()
        P.apply(name, self.settings.colors)
        self.settings.theme = name
        self.refresh_css()
        self._repaint()
        self.note(f"theme {name}", key="theme")

    def _read_settings_stamp(self) -> Optional[int]:
        try:
            return self.settings.path.stat().st_mtime_ns
        except OSError:
            return None

    def _follow_settings_file(self) -> None:
        """Pick up tui.json edited from outside (e.g. a wallpaper palette
        written by Noctalia) and recolor live when theme or colors moved."""
        stamp = self._read_settings_stamp()
        if stamp == self._settings_stamp:
            return
        self._settings_stamp = stamp
        old = self.settings
        # Always adopt the file: the next save writes the whole of it back.
        self.settings = TuiSettings(old.path)
        if (self.settings.theme, self.settings.colors) == (old.theme,
                                                           old.colors):
            return
        for problem in P.apply(self.settings.theme, self.settings.colors):
            self.note(f"tui.json: {problem}", "warning", key="colors")
        self.refresh_css()
        self._repaint()

    def _repaint(self) -> None:
        """Redraw everything that builds its colors in Python."""
        for box in self.query(Box):
            box._draw_title()
        for widget in (IsolationPanel, SessionStats, EventsPanel, KeyBar):
            try:
                self.query_one(widget)._draw()
            except Exception:
                pass
        for item in self.query(DeviceListItem):
            item.repaint()
        self.query_one(LevelScope).refresh()
        self._draw_state()

    def on_resize(self, event) -> None:
        """Below 100 columns the boxes stack and the page scrolls."""
        try:
            self.screen.set_class(event.size.width < 100, "-narrow")
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        """Create the UI layout."""
        strength = self.settings.atten_lim_db
        threshold = self.settings.aad_threshold_db
        with Vertical(id="main"):
            yield SignalPanel(id="signal-panel")
            with Horizontal(id="bottom-row"):
                yield IsolationPanel(
                    strength_db=(DEFAULT_STRENGTH_DB if strength is None
                                 else strength),
                    threshold_db=(DEFAULT_AAD_THRESHOLD_DB if threshold is None
                                  else threshold),
                    id="isolation-panel")
                yield DeviceList(preferred=self.settings.output_device,
                                 id="device-panel")
                yield EventsPanel(id="events-panel")
        yield KeyBar(id="key-bar")

    def on_mount(self) -> None:
        """Called when app is mounted."""
        # Log session header to file (Linux only) for remote diagnosis
        self._log_session_header()
        self._show_log()
        for problem in self._color_problems:
            self.note(f"tui.json: {problem}", "warning")
        if not self.settings.disclaimer_shown:
            self.settings.disclaimer_shown = True
            self.notify(MSG_MUSIC_DISCLAIMER, title="Before you start",
                        severity="warning", timeout=20)

        try:
            self.audio.launch()
        except Exception as e:
            # Start tries again and reports the failure.
            logging.getLogger("stream_denoiser").warning(
                "Could not start the audio process: %s", e)

        self._show_backend(self._expected_backend())
        # Load ONNX model
        self._load_model()
        self._draw_state()
        # Not scrolled into view: a narrow screen opens on the scope.
        self.query_one(IsolationPanel).focus(scroll_visible=False)

        # Start stats update timer
        self.set_interval(0.5, self._update_stats)
        self.set_interval(1.0, self._follow_settings_file)

    def _show_log(self) -> None:
        """The log, cleaned up, in the events box from here on."""
        from ..logging_config import forward_records
        self._log_handler = EventLogHandler(
            lambda line: self.post_message(LogEvent(line)))
        forward_records(self._log_handler)
        # The app's own logger (set up file-only in _setup_logging).
        app_logger = logging.getLogger("stream_denoiser")
        if self._log_handler not in app_logger.handlers:
            app_logger.addHandler(self._log_handler)

    def on_unmount(self) -> None:
        handler = getattr(self, "_log_handler", None)
        if handler is not None:
            from ..logging_config import stop_forwarding
            stop_forwarding(handler)
            logging.getLogger("stream_denoiser").removeHandler(handler)
            self._log_handler = None

    def on_log_event(self, message: LogEvent) -> None:
        line = message.line
        try:
            self.query_one(EventsPanel).add(
                line.message, line.level, key=line.key,
                sticky=line.key is not None)
        except Exception:
            pass

    def action_focus_box(self, number: int) -> None:
        for box in self.query(Box):
            if box.number == number:
                box.focus_box()
                return

    def note(self, message: str, level: str = "info",
             tag: Optional[str] = None, key: Optional[str] = None) -> None:
        """Explicit, UX-friendly event on screen (app thread only)."""
        try:
            self.query_one(EventsPanel).add(message, level, tag, key)
        except Exception:
            pass

    def _expected_backend(self) -> Optional[str]:
        """The backend a start would pick now (shown while idle)."""
        try:
            from ..backends.pipewire_backend import (
                linux_backend_preference, select_linux_backend)
            return select_linux_backend(linux_backend_preference())[0]
        except Exception:
            return None

    def _show_backend(self, backend: Optional[str]) -> None:
        self._idle_backend = backend
        try:
            self.query_one(IsolationPanel).update_values(
                backend=backend or "—")
        except Exception:
            pass
        self._draw_state()

    def _draw_state(self) -> None:
        """Box 1's top right: state, run time, backend and rate."""
        backend = self.backend if self.is_processing else self._idle_backend
        where = f"{backend} · " if backend else ""
        where += f"{DEFAULT_SAMPLE_RATE // 1000} kHz"
        if self.is_processing:
            elapsed = _clock(time.time() - self.start_time)
            state = (f"[{P.GREEN}]● isolating[/]  [{P.SOFT}]{elapsed}[/]  "
                     f"[{P.MUTED}]{where}[/]")
        else:
            state = f"[{P.MUTED}]○ idle[/]  [{P.DIM}]{where}[/]"
        try:
            self.query_one(SignalPanel).set_right(state)
        except Exception:
            pass

    @staticmethod
    def _cpu_model() -> str:
        """Best-effort CPU model string (Linux /proc/cpuinfo)."""
        try:
            with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except Exception:
            pass
        return "unknown"

    def _log_session_header(self) -> None:
        """Write a one-time session header to the file log."""
        import logging
        import sys
        if not sys.platform.startswith("linux"):
            return
        logger = logging.getLogger("stream_denoiser")
        path = get_log_file_path()
        try:
            from .. import __version__ as _ver
        except Exception:
            _ver = "unknown"
        try:
            from ..engines import available_models as _avail
            models = ",".join(_avail())
        except Exception:
            models = "unknown"
        logger.info(
            "session start: poise=%s model=%s available=[%s] cpu=%s platform=%s log=%s",
            _ver, self.model, models, self._cpu_model(), sys.platform, path,
        )
    
    def _saved_model(self) -> str:
        """The last model picked, if this machine can still run it."""
        from ..engines import model_unavailable_reason
        saved = self.settings.model
        if saved and model_unavailable_reason(saved) is None:
            return saved
        return DEFAULT_MODEL

    def _load_model(self) -> None:
        """Validate the selected denoising engine is available."""
        label = MODEL_INFO.get(self.model, {}).get("label", self.model)
        try:
            from ..engines import create_engine
            from ..constants import DEFAULT_FRAME_SIZE
            engine = create_engine(self.model)
            frame_size = engine.required_frame_size or DEFAULT_FRAME_SIZE
            engine.close()
            self.engine = True  # marker: engine validated
            self._show_model(self.model, frame_size)
            self.note(label, "success", tag="ready")
            logging.getLogger("stream_denoiser").info(
                "engine ready: model=%s frame_size=%s", self.model, frame_size
            )
        except Exception as e:
            self.engine = None
            self._show_model(self.model)
            # One line on screen, the rest in the log.
            first_line = str(e).splitlines()[0] if str(e) else type(e).__name__
            self.note(f"{label} failed to load: {first_line}", "error")
            _logger = logging.getLogger("stream_denoiser")
            _logger.warning(f"Model load failed: {self.model}: {first_line}")
            _logger.debug(f"Model load failed: {e!r}")

    def _show_model(self, model_id: str, frame_size=None) -> None:
        """Model name in box 1 and box 2 (idle too)."""
        label = MODEL_INFO.get(model_id, {}).get("label", model_id)
        frame = (f"{frame_size}-frame @ {DEFAULT_SAMPLE_RATE // 1000} kHz"
                 if frame_size else "")
        try:
            self.query_one(SessionStats).set_model(label, frame)
            self.query_one(IsolationPanel).update_values(model=label)
        except Exception:
            pass

    def check_action(self, action: str, parameters) -> bool | None:
        """No model switch while processing."""
        if action == "cycle_model" and self.is_processing:
            return None
        return True

    def action_cycle_model(self) -> None:
        """Open the model picker (blocked while running)."""
        if self.is_processing:
            self.note("stop to change the model", "warning")
            return
        try:
            from .widgets import ModelPickerScreen
            self.push_screen(
                ModelPickerScreen(current=self.model),
                self._on_model_picked,
            )
        except Exception as e:
            self.note(f"model switch failed: {e}", "error")

    def _on_model_picked(self, model_id) -> None:
        """Validate and apply the model chosen in the picker."""
        if not model_id:
            return
        if model_id != self.model:
            self.model = model_id
            self._load_model()
        # Remember it only if it loads, so the next start does not fail.
        if self.engine is not None:
            self.settings.model = model_id

    def action_toggle_processing(self) -> None:
        """Toggle audio processing on/off."""
        if self.is_processing:
            self._stop_processing()
        else:
            self._start_processing()

    def action_refresh_devices(self) -> None:
        """Refresh the device list."""
        if self.is_processing:
            self.note("devices are locked while isolating", "warning")
            return
        self.query_one("#device-panel", DeviceList).refresh_devices()
        self.note("devices refreshed")

    def on_device_list_picked(self, event: DeviceList.Picked) -> None:
        self.settings.output_device = event.sink_name

    def on_isolation_panel_adjust(self, event: IsolationPanel.Adjust) -> None:
        if event.row == "strength" and event.step:
            # Right: stronger (lower limit), as the bar fills that way.
            self._adjust_strength(-event.step * STRENGTH_STEP_DB)
        elif event.row == "skip" and event.step:
            self._adjust_threshold(event.step * THRESHOLD_STEP_DB)
        elif event.row == "model":
            self.action_cycle_model()

    def action_increase_threshold(self) -> None:
        """Raise the skip-silence threshold (more is skipped)."""
        self._adjust_threshold(THRESHOLD_STEP_DB)

    def action_decrease_threshold(self) -> None:
        """Lower the skip-silence threshold (less is skipped)."""
        self._adjust_threshold(-THRESHOLD_STEP_DB)

    def _adjust_threshold(self, delta: float) -> None:
        """Adjust AAD threshold by delta dB."""
        panel = self.query_one(IsolationPanel)
        old = panel.threshold_db
        new = max(AAD_MIN_DB, min(AAD_MAX_DB, old + delta))
        if new == old:
            return
        panel.update_values(threshold_db=new)
        self.settings.aad_threshold_db = new
        # Update the running session (the next one starts with the panel's)
        self.audio.set(aad_threshold_db=new)
        self._note_change("skip below", "threshold", old, new)

    def _adjust_strength(self, delta: float) -> None:
        """Adjust the attenuation limit by delta dB."""
        panel = self.query_one(IsolationPanel)
        old = panel.strength_db
        new = max(ATTEN_MIN_DB, min(ATTEN_MAX_DB, old + delta))
        if new == old:
            return
        panel.update_values(strength_db=new)
        self.settings.atten_lim_db = new
        self.audio.set(atten_lim_db=new)
        self._note_change("strength", "strength", old, new)

    def _note_change(self, what: str, key: str, old: float,
                     new: float) -> None:
        """'strength -45 → -50 dB', one line per burst of presses."""
        if not self.query_one(EventsPanel).merges(key):
            self._burst_from[key] = old
        self.note(f"{what} {self._burst_from[key]:.0f} → {new:.0f} dB",
                  key=key)

    def _start_processing(self) -> None:
        """Start audio processing."""
        if self.engine is None:
            self.note(f"cannot start: model '{self.model}' not loaded",
                      "error")
            return

        device_list = self.query_one("#device-panel", DeviceList)
        isolation = self.query_one(IsolationPanel)
        output_device = device_list.selected_device

        # Backend: the PipeWire node when available (fixed delay; it routes
        # itself from the audio process), else pulse-simple through the
        # null sink set up here.
        try:
            from ..backends.pipewire_backend import (
                linux_backend_preference, select_linux_backend)
            self.backend, reason = select_linux_backend(
                linux_backend_preference())
        except Exception as e:
            first_line = str(e).splitlines()[0] if str(e) else type(e).__name__
            logging.getLogger("stream_denoiser").error(
                "Cannot start: %s", e)
            self.note(f"cannot start: {first_line}", "error")
            return
        logging.getLogger("stream_denoiser").info(
            "backend: %s (%s)", self.backend, reason)

        if self.backend == "pipewire":
            self.linux_router = None
            routed = "routed via the Poise node"
        else:
            routed = None
            try:
                from ..backends.platform.linux import LinuxAudioRouter
                self.linux_router = LinuxAudioRouter(auto_switch=True)
                if self.linux_router.get_monitor_source_name():
                    routed = "routed via the Poise sink"
                else:
                    self.note("using the default capture", "warning")
            except ImportError:
                self.note("Linux router not available", "warning")

        # Start the session in the audio process. Linux input is always
        # 48000 Hz; the audio process resolves pulse-simple's source and
        # sink (waiting for the null sink's monitor to appear).
        router = self.linux_router
        config = {
            "model": self.model,
            "backend": self.backend,
            "output_device": output_device or None,
            "aad_threshold_db": isolation.threshold_db,
            "atten_lim_db": isolation.strength_db,
            "routed": router is not None,
            "monitor_source": (router.get_monitor_source_name()
                               if router else None),
            "fallback_sink": router.original_sink_name if router else None,
        }
        self.start_time = time.time()
        self._last_perf_log = 0.0
        self._audio_error = None
        try:
            self.audio.start(config)
        except Exception as e:
            logging.getLogger("stream_denoiser").error(
                "Cannot start: %s", e)
            self.note("cannot start: audio process unavailable", "error")
            if self.linux_router:
                self.linux_router.restore_original_sink()
                self.linux_router = None
            return

        self.is_processing = True
        self.refresh_bindings()
        self.screen.add_class("-running")
        self.query_one(LevelScope).clear()
        self.query_one(SessionStats).set_stats({})
        isolation.update_values(running=True, backend=self.backend)
        device_list.set_locked(True)
        self.query_one(KeyBar).set_running(True)
        self._draw_state()
        self.note("session started")
        if routed:
            self.note(routed, "success")

    def _stop_processing(self) -> None:
        """Stop audio processing."""
        # End the session; returns once the audio process has closed its
        # streams and restored the routing it owns (the PipeWire node's).
        final = self.audio.stop()

        # Restore audio routing
        if self.linux_router:
            self.linux_router.restore_original_sink()
            self.linux_router = None

        self.is_processing = False
        self.refresh_bindings()
        if final.get("frame_count") is not None:
            logging.getLogger("stream_denoiser").info(
                "run stop: frames=%s avg_ms=%.2f rtf=%.3f "
                "aad_total=%s aad_bypassed=%s bypass_ratio=%.2f "
                "overflows=%s empty_reads=%s elapsed=%.1fs log=%s",
                final.get("frame_count"), final.get("avg_time_ms", 0.0),
                final.get("rtf", 0.0), final.get("aad_total"),
                final.get("aad_bypassed"),
                final.get("aad_bypass_ratio", 0.0),
                0,  # neither backend can report overruns
                final.get("empty_reads", 0),
                time.time() - self.start_time if self.start_time else 0.0,
                get_log_file_path(),
            )
        self.screen.remove_class("-running")
        self.query_one(SessionStats).set_stats(None)
        self.query_one(IsolationPanel).update_values(
            running=False, backend=self._idle_backend or "—")
        self.query_one("#device-panel", DeviceList).set_locked(False)
        self.query_one(KeyBar).set_running(False)
        self._draw_state()
        self.note(f"session stopped after "
                  f"{_clock(time.time() - self.start_time)}")

    def _post_audio_event(self, data: dict) -> None:
        """AudioHost callback (its reader thread): hand over to the app."""
        self.post_message(AudioEvent(data))

    def on_audio_event(self, message: AudioEvent) -> None:
        """Errors get a short note (the log has the detail); a session
        that ended on its own (error, crash) resets the UI."""
        kind = message.data.get("event")
        if kind == "error":
            self._audio_error = (message.data.get("notice")
                                 or "Audio error. See log for details.")
            self.note(self._audio_error, "error")
        elif kind == "stopped" and self.is_processing \
                and not self.audio.running:
            self._stop_processing()
            if self._audio_error:
                # Keep the reason on top rather than "session stopped".
                self.note(self._audio_error, "error")

    def _update_stats(self) -> None:
        """Update stats display (called periodically)."""
        if not self.is_processing:
            return
        self._draw_state()
        try:
            self.query_one(LevelScope).push(self.audio.take_levels())
        except Exception:
            pass
        # Sent by the audio process every 0.5 s; empty until the first.
        stats = self.audio.stats
        if not stats:
            return

        try:
            self.query_one(SessionStats).set_stats(stats)
            running_time = time.time() - self.start_time
            # Throttled file snapshot (~every 5s): distinguishes AAD-bypass
            # zeros (silence) from genuine slow-inference RTF on weak CPUs.
            now = time.monotonic()
            if now - getattr(self, "_last_perf_log", 0.0) >= 5.0:
                self._last_perf_log = now
                logging.getLogger("stream_denoiser").info(
                    "perf: frames=%s avg_ms=%.2f rtf=%.3f aad_total=%s "
                    "aad_active=%s aad_bypassed=%s bypass_ratio=%.2f "
                    "overflows=%s empty_reads=%s elapsed=%.1fs "
                    "in_block=%s backlog=%s dropped=%s",
                    stats.get("frame_count"), stats.get("avg_time_ms", 0.0),
                    stats.get("rtf", 0.0), stats.get("aad_total"),
                    stats.get("aad_active"), stats.get("aad_bypassed"),
                    stats.get("aad_bypass_ratio", 0.0),
                    0, 0,  # only known at the end of a run (run stop line)
                    running_time,
                    stats.get("input_block_size"),
                    stats.get("resampler_backlog"),
                    stats.get("resampler_dropped"),
                )
        except Exception:
            pass

    def action_quit(self) -> None:
        """Quit the application."""
        if self.is_processing:
            self._stop_processing()
        self.audio.shutdown()
        self.exit()
