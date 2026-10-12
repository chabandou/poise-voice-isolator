"""Integration tests for the pulse-simple backend (gated on a live server).

All tests skip unless a Pulse-compatible server is reachable AND
libpulse-simple loads. Run locally with a headless PulseAudio or
PipeWire+pipewire-pulse server.
"""
import os
import shutil
import signal
import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.integration


def _server_available():
    try:
        from stream_denoiser.backends.pulse_simple import _load_library
        _load_library()
    except Exception:
        return False
    try:
        import pulsectl
        # Unit tests stub pulsectl when it is not installed; a stub is
        # not a server.
        if getattr(pulsectl, "_is_stub", False):
            return False
    except ImportError:
        return False
    try:
        with pulsectl.Pulse("poise-probe"):
            return True
    except Exception:
        return False


needs_server = pytest.mark.skipif(
    not _server_available(),
    reason="needs a running Pulse-compatible server + libpulse-simple",
)

NULL_SINK = "poise-test-null"


def _pactl(*args):
    if not shutil.which("pactl"):
        pytest.skip("pactl not available")
    proc = subprocess.run(["pactl", *args], capture_output=True, text=True,
                          timeout=10)
    return proc


@needs_server
def test_capture_tone_rms_and_frequency():
    """Play a tone into the null sink and assert RMS/frequency on capture."""
    import numpy as np
    pytest.importorskip("pulsectl")
    from stream_denoiser.backends.pulse_simple import (
        PulseCapture, PulsePlayback, PULSE_SAMPLE_RATE,
    )
    # Create an isolated null sink for the test.
    proc = _pactl("load-module", "module-null-sink",
                  f"sink_name={NULL_SINK}")
    if proc.returncode != 0:
        pytest.skip(f"could not create null sink: {proc.stderr}")
    module_id = proc.stdout.strip()
    try:
        import threading
        frames = 480
        freq = 440.0
        nplay = 32
        t = np.arange(frames * nplay, dtype=np.float32) / PULSE_SAMPLE_RATE
        tone = (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
        stereo = np.column_stack([tone, tone])
        tone_blocks = []

        def _play():
            with PulsePlayback(NULL_SINK, frames) as play:
                for i in range(0, len(stereo), frames):
                    play.write(stereo[i:i + frames])

        # Capture concurrently: the monitor only carries audio while the
        # tone is actually playing, and stream startup skew puts silence
        # on both ends — so gate on per-block RMS and analyse only blocks
        # that actually contain the tone.
        with PulseCapture(f"{NULL_SINK}.monitor", frames) as cap:
            thread = threading.Thread(target=_play, daemon=True)
            thread.start()
            for _ in range(64):
                got, overflowed = cap.read()
                assert overflowed is False
                assert got.shape == (frames, 1)
                if float(np.sqrt(np.mean(got.astype(np.float64) ** 2))) > 0.1:
                    tone_blocks.append(got.copy())
                    if len(tone_blocks) == 8:
                        break
            thread.join(timeout=15)
        assert len(tone_blocks) == 8, "tone never arrived at the monitor"
        got = np.concatenate(tone_blocks)
        rms = float(np.sqrt(np.mean(got.astype(np.float64) ** 2)))
        assert rms > 0.05, f"captured silence? rms={rms}"
        # Frequency check via zero-crossing estimate.
        x = got[:, 0].astype(np.float64)
        x -= x.mean()
        crossings = np.sum((x[:-1] < 0) != (x[1:] < 0))
        est = crossings * PULSE_SAMPLE_RATE / (2 * len(x))
        assert abs(est - freq) < freq * 0.15, f"freq {est} != {freq}"
    finally:
        _pactl("unload-module", module_id)


@needs_server
def test_start_stop_cycles_no_crash():
    """50 open/close cycles must exit 0 (regression test for this crash)."""
    env = dict(os.environ)
    env.setdefault("MALLOC_CHECK_", "3")
    env.setdefault("MALLOC_PERTURB_", "165")
    preload = shutil.which("libc_malloc_debug.so.0")
    code = (
        "from stream_denoiser.backends.pulse_simple import "
        "PulseCapture, PulsePlayback;"
        f"import pulsectl;"
        f"src=[s.name for s in pulsectl.Pulse('t').source_list()];"
        f"sink=[s.name for s in pulsectl.Pulse('t').sink_list()][0];"
        f"src0=[s for s in src if s.endswith('.monitor')][0];"
        "frames=480;"
        "from stream_denoiser.backends.platform.linux import get_default_sink_name;"
        "sink=get_default_sink_name();"
        "import pulsectl;"
        "snks=[s.name for s in pulsectl.Pulse('t').sink_list()];"
        "sink=next((s for s in snks if 'null' not in s.lower()), snks[0]);"
        "exec('for _ in range(50):\\n"
        " c=PulseCapture(src0,frames);c.close();c.close();\\n"
        " p=PulsePlayback(sink,frames);p.close();p.close()\\n')"
    )
    if preload and os.path.exists(preload):
        env["LD_PRELOAD"] = preload
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                          text=True, timeout=120, env=env)
    assert proc.returncode == 0, f"cycles crashed: {proc.stderr[-2000:]}"


@needs_server
def test_playback_stays_on_named_sink_after_default_flip():
    """Playback stream stays on its named sink after the default flips."""
    pytest.importorskip("pulsectl")
    import pulsectl
    from stream_denoiser.backends.pulse_simple import PulsePlayback
    with pulsectl.Pulse("poise-test-default") as pulse:
        sinks = [s.name for s in pulse.sink_list()
                 if "null" not in s.name.lower()]
        if len(sinks) < 1:
            pytest.skip("need at least one non-null sink")
        target = sinks[0]
        original_default = pulse.server_info().default_sink_name
        try:
            with PulsePlayback(target, 480) as play:
                # Flip the default (to itself or another sink); the
                # stream's sink name must not change.
                assert play.sink == target
                others = [s for s in pulse.sink_list() if s.name != target]
                if others:
                    pulse.sink_default_set(others[0])
                    time.sleep(0.2)
                assert play.sink == target
        finally:
            # Put back the user's default, which need not be `target`.
            for s in pulse.sink_list():
                if s.name == original_default:
                    pulse.sink_default_set(s)


SIGTERM_SINK = "poise-test-sigterm"
SIGTERM_OUT_SINK = "poise-test-sigterm-out"

# Runs the real CLI audio path with a passthrough engine (no model to
# load), routed through its own null sink so it can't collide with a
# running Poise or a leftover Poise_Capture, and playing into a null sink
# instead of the speakers.
_SIGTERM_HELPER = f"""
from stream_denoiser import cli
from stream_denoiser.backends.platform.linux import LinuxAudioRouter
from stream_denoiser.engines.base import DenoiseEngine

class Passthrough(DenoiseEngine):
    name = "passthrough"
    def process_frame(self, frame):
        return frame
    def reset(self):
        pass

LinuxAudioRouter.SINK_NAME = {SIGTERM_SINK!r}
cli._interrupt_on_termination_signals()
cli.process_system_audio_realtime(Passthrough(), enable_aad=False,
                                  sink={SIGTERM_OUT_SINK!r}, backend="pulse")
"""


def _sinks():
    """{name: index} of every sink."""
    out = _pactl("list", "sinks", "short").stdout
    return {f[1]: f[0] for f in (l.split("\t") for l in out.splitlines())
            if len(f) > 1}


def _null_sink_modules(sink_name):
    """Ids of the module-null-sink modules backing ``sink_name``."""
    out = _pactl("list", "modules", "short").stdout
    return [f[0] for f in (l.split("\t") for l in out.splitlines())
            if len(f) > 2 and f[1] == "module-null-sink"
            and f"sink_name={sink_name}" in f[2].split()]


def _sink_has_stream(sink_name):
    index = _sinks().get(sink_name)
    out = _pactl("list", "sink-inputs", "short").stdout
    return index is not None and any(
        l.split("\t")[1:2] == [index] for l in out.splitlines())


def _wait_until(cond, timeout):
    deadline = time.monotonic() + timeout
    while not cond():
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)
    return True


@needs_server
def test_sinks_restored_after_sigterm(tmp_path):
    """SIGTERM mid-run unloads the null sink and restores the default."""
    from stream_denoiser.backends.platform.linux import get_default_sink_name
    for module_id in _null_sink_modules(SIGTERM_SINK):  # earlier crash
        _pactl("unload-module", module_id)
    proc = _pactl("load-module", "module-null-sink",
                  f"sink_name={SIGTERM_OUT_SINK}")
    if proc.returncode != 0:
        pytest.skip(f"could not create null sink: {proc.stderr}")
    out_module = proc.stdout.strip()
    before = get_default_sink_name()
    log_path = tmp_path / "helper.log"
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    helper = None
    try:
        with open(log_path, "w") as log:
            helper = subprocess.Popen(
                [sys.executable, "-c", _SIGTERM_HELPER], cwd=repo_root,
                stdout=log, stderr=subprocess.STDOUT)

        def log_tail():
            return log_path.read_text()[-2000:]

        # SIGTERM only once audio is flowing, like a real stop.
        running = _wait_until(
            lambda: helper.poll() is not None
            or _sink_has_stream(SIGTERM_OUT_SINK), timeout=20)
        assert helper.poll() is None, f"helper exited early:\n{log_tail()}"
        assert running, f"audio loop never started:\n{log_tail()}"
        assert get_default_sink_name() == SIGTERM_SINK

        helper.send_signal(signal.SIGTERM)
        try:
            helper.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pytest.fail(f"helper did not exit on SIGTERM:\n{log_tail()}")

        assert _wait_until(lambda: SIGTERM_SINK not in _sinks(), 3), (
            f"null sink left loaded after SIGTERM:\n{log_tail()}")
        assert _wait_until(lambda: get_default_sink_name() == before, 3), (
            f"default sink is {get_default_sink_name()!r}, "
            f"expected {before!r}")
    finally:
        if helper is not None and helper.poll() is None:
            helper.kill()
            helper.wait()
        for module_id in _null_sink_modules(SIGTERM_SINK):
            _pactl("unload-module", module_id)
        if before and get_default_sink_name() != before:
            _pactl("set-default-sink", before)
        _pactl("unload-module", out_module)
