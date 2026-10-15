"""
The audio loop in a process of its own.

The UI and the audio loop used to share one interpreter, so one GIL and
one garbage collector. A Textual redraw, or a collection pass over the
UI's much larger heap, could hold the loop long enough for the PipeWire
node to play frames unprocessed (on pulse-simple: lag that stayed). Here
the loop runs in a child process with only the audio modules in it, and
its garbage collector is off while a run lasts (audio_gc.gc_paused).

The child lives as long as the UI and runs one session per start, like
the audio daemon planned for the native rewrite, which can take its
place behind the same messages. Every message is one JSON object, so
nothing Python-specific crosses the boundary:

UI -> audio   {"cmd": "start", "config": {...}}     (see AudioHost.start)
              {"cmd": "set", "aad_threshold_db": x}  also "atten_lim_db"
              {"cmd": "stop"}   {"cmd": "quit"}
audio -> UI   {"event": "ready", "pid": n}
              {"event": "running", "backend": "pipewire"|"pulse"|"portaudio"|"wasapi"}
              {"event": "stats", "stats": {...}, "elapsed": s}
              {"event": "error", "message": "...", "notice": "..."}
              {"event": "stopped", "stats": {...}}   ends every session
              {"event": "log", "name": "...", "level": n, "msg": "...",
               "created": t}
"""
import json
import logging
import multiprocessing
import os
import signal
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from typing import Callable, Optional

from .constants import (
    DEFAULT_AAD_THRESHOLD_DB,
    DEFAULT_FRAME_SIZE,
    DEFAULT_MODEL,
    PULSE_TARGET_SR,
)
from .logging_config import (
    get_crash_log_path,
    get_file_handler,
    get_logger,
    get_memory_handler,
)

_logger = get_logger(__name__)

# How long stop() waits for the session to clean up before killing it.
STOP_TIMEOUT_SEC = 3.0
# How often a running session sends stats.
STATS_INTERVAL_SEC = 0.5

AUDIO_ERROR_NOTICE = "Audio error. See log for details."
CAPTURE_NOTICE = "Capture device not found. See log for fixes."
PLAYBACK_NOTICE = "Playback device not found. See log for fixes."
CRASH_NOTICE = "Audio process stopped unexpectedly. See log for details."


def _plain(value):
    """JSON fallback: numpy scalars and arrays to Python values."""
    for attr in ("item", "tolist"):
        convert = getattr(value, attr, None)
        if callable(convert):
            try:
                return convert()
            except (TypeError, ValueError):
                pass
    return str(value)


class _Channel:
    """JSON messages over a multiprocessing connection."""

    def __init__(self, conn):
        self.conn = conn
        self._lock = threading.Lock()

    def send(self, msg: dict) -> bool:
        """Send one message; False once the other side is gone."""
        data = json.dumps(msg, default=_plain).encode()
        try:
            with self._lock:
                self.conn.send_bytes(data)
            return True
        except (OSError, ValueError):
            return False

    def recv(self) -> dict:
        """Next message (blocks). EOFError once the other side is gone."""
        return json.loads(self.conn.recv_bytes())

    def poll(self) -> bool:
        return self.conn.poll(0)


# ---------------------------------------------------------------------------
# UI side
# ---------------------------------------------------------------------------

@contextmanager
def _real_stderr():
    """Put the real stderr back while spawning.

    multiprocessing starts its resource tracker with sys.stderr's file
    descriptor. Inside a Textual app sys.stderr is a print capture whose
    fileno() is -1, and the spawn fails ("bad value(s) in fds_to_keep").
    """
    current = sys.stderr
    try:
        valid = current.fileno() >= 0
    except Exception:
        valid = False
    if valid or sys.__stderr__ is None:
        yield
        return
    sys.stderr = sys.__stderr__
    try:
        yield
    finally:
        sys.stderr = current


def _emit_log(msg: dict) -> None:
    """Hand a record from the audio process to this process's loggers."""
    name = str(msg.get("name") or "stream_denoiser")
    level = int(msg.get("level", logging.INFO))
    created = float(msg.get("created") or time.time())
    record = logging.makeLogRecord({
        "name": name, "levelno": level,
        "levelname": logging.getLevelName(level),
        "msg": str(msg.get("msg", "")), "args": None,
        "created": created, "msecs": (created - int(created)) * 1000.0,
    })
    get_logger(name).handle(record)


class AudioHost:
    """The UI's handle on the audio process.

    ``on_event(msg)`` runs on a reader thread for each event other than
    "log" (re-emitted into this process's loggers, so the log file keeps
    one writer) and "stats" (kept in ``stats``). A session that ends on
    its own, through an error or a crash, ends with "stopped" like any
    other.
    """

    def __init__(self, on_event: Optional[Callable[[dict], None]] = None):
        self._on_event = on_event
        self._proc = None
        self._channel: Optional[_Channel] = None
        self._stopped = threading.Event()
        self._stopped.set()
        self.stats: dict = {}
        self.final_stats: dict = {}

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.is_alive()

    @property
    def running(self) -> bool:
        """A session is running (from start() until "stopped")."""
        return not self._stopped.is_set()

    @property
    def pid(self) -> Optional[int]:
        return self._proc.pid if self._proc is not None else None

    def launch(self) -> None:
        """Start the audio process unless it is up. Its imports take about
        a second, so the UI calls this early instead of on Start."""
        if self.alive:
            return
        self.close()
        ctx = multiprocessing.get_context("spawn")
        ours, theirs = ctx.Pipe()
        options = {
            "log_level": self._log_level(),
            "crash_log": get_crash_log_path(),
        }
        proc = ctx.Process(target=_child_main, args=(theirs, options),
                           name="poise-audio", daemon=True)
        try:
            with _real_stderr():
                proc.start()
        finally:
            theirs.close()
        self._proc = proc
        self._channel = channel = _Channel(ours)
        threading.Thread(target=self._read, args=(proc, channel),
                         name="poise-audio-events", daemon=True).start()
        _logger.info("audio process started (pid %d)", proc.pid)

    def start(self, config: dict) -> None:
        """Start a session.

        config keys: model, backend ("pipewire", "pulse"; on Windows
        "auto", "wasapi" or "portaudio"),
        output_device, aad_threshold_db, atten_lim_db (optional);
        pipewire only, optional: route_default, node_name, description;
        pulse only: routed (the UI set up the null sink), monitor_source,
        fallback_sink; Windows ("auto": the native path, PortAudio if it
        cannot start), optional: input_device and output_device
        (PortAudio IDs; names for "wasapi"), realtime (PortAudio loop
        under MMCSS, default on). Optional everywhere: onnx_path (a custom
        DF3 model), aad_enabled (default on).
        """
        if self.running:
            raise RuntimeError("audio session already running")
        self.stats = {}
        self.final_stats = {}
        msg = {"cmd": "start", "config": config}
        for attempt in range(2):
            # A process that died after the last check fails the send:
            # then once more with a new one.
            if attempt:
                self.close()
            self.launch()
            self._stopped.clear()
            if self._channel.send(msg):
                return
            self._stopped.set()
        raise RuntimeError("audio process is not reachable")

    def set(self, **values) -> None:
        """Change live settings of the running session."""
        if self.running and self._channel is not None:
            self._channel.send({"cmd": "set", **values})

    def stop(self, timeout: float = STOP_TIMEOUT_SEC) -> dict:
        """End the session and wait until the audio process has cleaned
        up (routing restored, node gone). Returns the final stats."""
        if self.running:
            self._channel.send({"cmd": "stop"})
            if not self._stopped.wait(timeout):
                _logger.warning("audio process did not stop within %.1fs; "
                                "killing it", timeout)
                self._kill()
                self._stopped.wait(1.0)
                self._stopped.set()
        return self.final_stats

    def shutdown(self, timeout: float = STOP_TIMEOUT_SEC) -> None:
        """End any session and the audio process."""
        proc = self._proc
        if proc is None:
            return
        self.stop(timeout)
        self._channel.send({"cmd": "quit"})
        proc.join(timeout)
        if proc.is_alive():
            self._kill()
        self.close()

    def close(self) -> None:
        if self._channel is not None:
            try:
                self._channel.conn.close()
            except OSError:
                pass
        self._proc = None
        self._channel = None

    def _kill(self) -> None:
        proc = self._proc
        if proc is None:
            return
        proc.terminate()
        proc.join(1.0)
        if proc.is_alive():
            proc.kill()
            proc.join(1.0)

    @staticmethod
    def _log_level() -> int:
        """Lowest level anything here records, so the audio process does
        not send records nobody keeps."""
        levels = [h.level for h in logging.getLogger("stream_denoiser").handlers
                  if not isinstance(h, logging.NullHandler)]
        for handler in (get_file_handler(), get_memory_handler()):
            if handler is not None:
                levels.append(handler.level)
        return min(levels) if levels else logging.INFO

    def _read(self, proc, channel: _Channel) -> None:
        while True:
            try:
                msg = channel.recv()
            except (EOFError, OSError):
                break
            except ValueError as e:
                _logger.warning("audio process sent a bad message: %s", e)
                continue
            self._dispatch(msg)
        proc.join(1.0)
        if self.running and proc is self._proc:
            _logger.error("audio process exited during a session "
                          "(exit code %s)", proc.exitcode)
            self._dispatch({"event": "error", "notice": CRASH_NOTICE,
                            "message": f"exit code {proc.exitcode}"})
            self._dispatch({"event": "stopped", "stats": self.stats})

    def _dispatch(self, msg: dict) -> None:
        kind = msg.get("event")
        if kind == "log":
            _emit_log(msg)
            return
        if kind == "ready":
            _logger.info("audio process ready (pid %s)", msg.get("pid"))
        if kind == "stats":
            self.stats = msg.get("stats") or {}
            return
        if kind == "stopped":
            self.final_stats = msg.get("stats") or self.stats
            self._stopped.set()
        if self._on_event is not None:
            try:
                self._on_event(msg)
            except Exception as e:
                _logger.debug(f"audio event handler failed: {e!r}")


# ---------------------------------------------------------------------------
# Audio process side
# ---------------------------------------------------------------------------

class _ForwardHandler(logging.Handler):
    """Sends records to the UI process, which writes them."""

    def __init__(self, channel: _Channel, level: int):
        super().__init__(level)
        self._channel = channel

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
            if record.exc_info:
                msg += "\n" + logging.Formatter().formatException(
                    record.exc_info)
        except Exception:
            return
        self._channel.send({"event": "log", "name": record.name,
                            "level": record.levelno, "msg": msg,
                            "created": record.created})


def _isolate(channel: _Channel, options: dict) -> None:
    """Detach from the UI's terminal and route logging to the UI.

    Own session: terminal signals (Ctrl+C, hangup) reach the UI only,
    which stops this process; if the UI dies first, the pipe closes and
    the session stops on its own. stdout/stderr were the UI's terminal:
    a stray print or a native library's warning would draw over the TUI,
    so stdout goes nowhere and stderr (Python fatal errors, native
    aborts, faulthandler) to the crash log.
    """
    if hasattr(os, "setsid"):
        try:
            os.setsid()
        except OSError:
            pass
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    from .logging_config import forward_records, set_tui_mode
    set_tui_mode(True)  # no console handlers
    forward_records(_ForwardHandler(
        channel, int(options.get("log_level", logging.INFO))))

    try:
        devnull = os.open(os.devnull, os.O_RDWR)
        err = devnull
        crash_log = options.get("crash_log")
        if crash_log:
            try:
                err = os.open(crash_log,
                              os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
                os.write(err, (
                    f"--- poise audio process start "
                    f"{time.strftime('%Y-%m-%dT%H:%M:%S')} "
                    f"pid={os.getpid()} ---\n").encode())
            except OSError:
                err = devnull
        os.dup2(devnull, 0)
        os.dup2(devnull, 1)
        os.dup2(err, 2)
        import faulthandler
        faulthandler.enable(all_threads=True)
    except Exception as e:
        _logger.debug(f"audio process: stdio not redirected: {e!r}")


def _child_main(conn, options: dict) -> None:
    """Audio process entry point (AudioHost.launch)."""
    channel = _Channel(conn)
    _isolate(channel, options)
    channel.send({"event": "ready", "pid": os.getpid()})
    while True:
        try:
            msg = channel.recv()
        except (EOFError, OSError):
            return  # the UI is gone
        except ValueError:
            continue
        cmd = msg.get("cmd")
        if cmd == "start":
            if _run_session(channel, msg.get("config") or {}):
                return
        elif cmd == "quit":
            return


class _SessionError(RuntimeError):
    """A session cannot run; ``notice`` is the UI's short message."""

    def __init__(self, message: str, notice: str):
        super().__init__(message)
        self.notice = notice


class _Control:
    """The session's end of the pipe: the loop's should_stop and on_stats."""

    def __init__(self, channel: _Channel):
        self.channel = channel
        self.processor = None
        self.stop = False
        self.quit = False
        self._pending: dict = {}

    def should_stop(self) -> bool:
        """Called once per frame (or wait timeout): one poll() call."""
        try:
            while not self.stop and self.channel.poll():
                self._handle(self.channel.recv())
        except (EOFError, OSError):
            self.stop = self.quit = True  # the UI is gone
        except ValueError:
            pass
        return self.stop

    def _handle(self, msg: dict) -> None:
        cmd = msg.get("cmd")
        if cmd == "stop":
            self.stop = True
        elif cmd == "quit":
            self.stop = self.quit = True
        elif cmd == "set":
            self._pending.update(
                (k, v) for k, v in msg.items() if k != "cmd")
            self.apply_pending()

    def apply_pending(self) -> None:
        processor = self.processor
        if processor is None:
            return
        for key, value in self._pending.items():
            if key == "aad_threshold_db" and processor.aad is not None:
                processor.aad.set_threshold(float(value))
            elif key == "atten_lim_db":
                processor.engine.set_atten_lim_db(float(value))
        self._pending.clear()

    def on_stats(self, stats: dict, elapsed: float) -> None:
        """The processor's diagnostics, plus whatever the loop adds (the
        native node's counters)."""
        self.channel.send({"event": "stats", "elapsed": elapsed,
                           "stats": {**(stats or {}),
                                     **self.processor.get_diagnostics()}})

    @contextmanager
    def signals(self):
        """SIGTERM/SIGHUP end the session cleanly (routing restored)."""
        def handler(signum, frame):
            self.stop = self.quit = True

        previous = {}
        for name in ("SIGTERM", "SIGHUP"):
            sig = getattr(signal, name, None)
            if sig is not None:
                previous[sig] = signal.signal(sig, handler)
        try:
            yield
        finally:
            for sig, old in previous.items():
                signal.signal(sig, old)


def _build_processor(config: dict):
    from .engines import create_engine
    from .processor import DenoiserAudioProcessor

    kwargs = {}
    if config.get("atten_lim_db") is not None:
        kwargs["atten_lim_db"] = float(config["atten_lim_db"])
    # A fresh engine per session: engines hold streaming state.
    engine_kwargs = dict(kwargs)
    if config.get("onnx_path"):
        engine_kwargs["onnx_path"] = config["onnx_path"]
    engine = create_engine(config.get("model") or DEFAULT_MODEL,
                           **engine_kwargs)
    try:
        return DenoiserAudioProcessor(
            engine,
            target_sr=PULSE_TARGET_SR,
            frame_size=engine.required_frame_size or DEFAULT_FRAME_SIZE,
            enable_aad=bool(config.get("aad_enabled", True)),
            aad_threshold_db=float(config.get("aad_threshold_db",
                                              DEFAULT_AAD_THRESHOLD_DB)),
            **kwargs)
    except Exception:
        engine.close()
        raise


def _pulse_endpoints(config: dict):
    """(source, sink) names for pulse-simple. Fails fast rather than
    capturing the default input, which would record silence while the
    default sink points at the null sink (100% AAD bypass)."""
    from .backends.platform.linux import (
        find_monitor_source_pulsectl, get_default_sink_name, wait_for_source)

    monitor = config.get("monitor_source")
    if config.get("routed"):
        if not monitor:
            raise _SessionError(
                "Audio routing did not provide a monitor source.",
                CAPTURE_NOTICE)
        source = wait_for_source(monitor)
        if source is None:
            raise _SessionError(
                f"Null sink monitor '{monitor}' not visible at the "
                "PulseAudio level. Not starting: capturing the default "
                "input instead would record silence. Fixes: check "
                "pavucontrol/PipeWire Pulse backend, or restart without "
                "auto-routing.", CAPTURE_NOTICE)
    else:
        # No router: capture the default sink's monitor.
        found = find_monitor_source_pulsectl()
        source = found.name if found else None
        if source is None:
            raise _SessionError("No PulseAudio monitor source found.",
                                CAPTURE_NOTICE)
    # Explicit selection, else the real sink saved at routing setup, else
    # the current default.
    sink = (config.get("output_device") or config.get("fallback_sink")
            or get_default_sink_name())
    if not sink:
        raise _SessionError("No PulseAudio sink found for playback.",
                            PLAYBACK_NOTICE)
    return source, sink


def _run_backend(processor, config: dict, ctl: _Control) -> dict:
    """Run the loop until stopped; returns extra final stats."""
    backend = config.get("backend")
    if backend == "pipewire":
        from .backends.pipewire_backend import run_pipewire_loop
        options = {key: config[key] for key in
                   ("route_default", "node_name", "description")
                   if config.get(key) is not None}
        ctl.channel.send({"event": "running", "backend": backend})
        run_pipewire_loop(processor, config.get("output_device") or None,
                          should_stop=ctl.should_stop, on_stats=ctl.on_stats,
                          stats_interval_sec=STATS_INTERVAL_SEC,
                          pause_gc=True, **options)
        return {}
    if backend == "pulse":
        from .backends.pulse_backend import run_pulse_loop
        source, sink = _pulse_endpoints(config)
        ctl.channel.send({"event": "running", "backend": backend})
        _final, empty_reads = run_pulse_loop(
            processor, source, sink, should_stop=ctl.should_stop,
            on_stats=ctl.on_stats, stats_interval_sec=STATS_INTERVAL_SEC,
            pause_gc=True)
        return {"empty_reads": empty_reads}
    if backend in ("auto", "wasapi", "portaudio") and sys.platform == "win32":
        _run_windows(processor, config, ctl, backend)
        return {}
    raise ValueError(f"unknown audio backend {backend!r}")


def _run_windows(processor, config: dict, ctl: _Control, backend: str) -> None:
    """The native path ("wasapi"), PortAudio ("portaudio"), or the native
    path with PortAudio as the fallback when it cannot start ("auto", as
    the CLI does). "running" goes out once audio flows."""
    from .backends.wasapi_backend import (
        WasapiStartError, run_wasapi_loop, select_windows_backend)
    from .constants import WIN_PROCESS_MARGIN_SAMPLES

    def running(name):
        return lambda *_: ctl.channel.send({"event": "running",
                                            "backend": name})

    chosen, reason = select_windows_backend(backend)
    _logger.info("Windows backend: %s (%s)", chosen, reason)
    if chosen == "wasapi":
        try:
            # Nothing else holds this process's GIL: inference needs far
            # less time per frame than in the UI's process (see constants).
            run_wasapi_loop(
                processor, _device_name(config.get("input_device"), "input"),
                _device_name(config.get("output_device"), "output"),
                should_stop=ctl.should_stop, on_stats=ctl.on_stats,
                stats_interval_sec=STATS_INTERVAL_SEC,
                on_started=running("wasapi"),
                margin=WIN_PROCESS_MARGIN_SAMPLES, pause_gc=True)
            return
        except WasapiStartError as e:
            if backend == "wasapi":
                raise
            _logger.warning(
                "Native audio path did not start (%s); using PortAudio", e)
    from .backends.sounddevice_backend import run_portaudio_loop
    run_portaudio_loop(
        processor, config.get("input_device"), config.get("output_device"),
        should_stop=ctl.should_stop, on_stats=ctl.on_stats,
        stats_interval_sec=STATS_INTERVAL_SEC,
        on_started=running("portaudio"), pause_gc=True,
        realtime=bool(config.get("realtime", True)))


def _device_name(device, kind: str) -> Optional[str]:
    """A WASAPI endpoint name for the native path: names pass through,
    PortAudio IDs are looked up; None finds CABLE Output (input) or keeps
    the default (output)."""
    if isinstance(device, str) or (device is None and kind == "output"):
        return device or None
    import sounddevice as sd
    if device is None:
        from .device_utils import find_loopback_device
        device = find_loopback_device(None)
    return sd.query_devices(int(device))["name"]


def _run_session(channel: _Channel, config: dict) -> bool:
    """One start..stop. True when the process should exit afterwards."""
    ctl = _Control(channel)
    processor = None
    extra: dict = {}
    try:
        with ctl.signals():
            try:
                processor = _build_processor(config)
                ctl.processor = processor
                ctl.apply_pending()
                if not ctl.should_stop():
                    extra = _run_backend(processor, config, ctl)
            except _SessionError as e:
                _logger.error("%s", e)
                channel.send({"event": "error", "message": str(e),
                              "notice": e.notice})
            except Exception as e:
                _logger.error(f"Processing error: {e}")
                _logger.debug(traceback.format_exc())
                channel.send({"event": "error", "message": str(e),
                              "notice": AUDIO_ERROR_NOTICE})
            finally:
                final = {}
                if processor is not None:
                    try:
                        final = processor.get_diagnostics()
                        processor.close()
                    except Exception as e:
                        _logger.debug(f"processor close failed: {e!r}")
                final.update(extra)
                channel.send({"event": "stopped", "stats": final})
    except Exception as e:
        # Signal handler setup or a send that raised: nothing to report to.
        _logger.debug(f"audio session teardown failed: {e!r}")
    return ctl.quit
