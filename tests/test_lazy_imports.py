"""What the audio modules import: the loop they run, not PortAudio.

The audio process (audio_host) is spawned so it holds only the audio
modules. Importing any stream_denoiser.backends module runs the
package's __init__ first, and that used to import the PortAudio loop
(sounddevice_backend, and with it sounddevice where installed) into
every audio process, the PipeWire one included, which never runs it.

Each import runs in a fresh interpreter, as it does in the spawned
process: this one has long since imported everything.

On Windows sounddevice is a dependency, and backend_detection imports it
at import time for device_utils, the CLI and the GUI worker; the
PortAudio fallback imports it as well, when it runs. None of the modules
below imports those, so the same assertion holds on Windows and runs on
every platform.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]

_PORTAUDIO = ("stream_denoiser.backends.sounddevice_backend", "sounddevice")


def _portaudio_loaded_by(module: str) -> list:
    """The PortAudio modules in sys.modules after ``import module`` in a
    fresh interpreter."""
    code = (f"import sys, {module}\n"
            f"print(' '.join(m for m in {_PORTAUDIO!r} if m in sys.modules))")
    env = dict(os.environ, PYTHONPATH=str(_REPO_ROOT))
    proc = subprocess.run([sys.executable, "-c", code], cwd=str(_REPO_ROOT),
                          env=env, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.split()


@pytest.mark.parametrize("module", [
    # The audio process and the session it runs.
    "stream_denoiser.audio_host",
    "stream_denoiser.session",
    # The loops other than PortAudio: the PipeWire node, pulse-simple
    # and the native Windows path.
    "stream_denoiser.backends.pipewire_backend",
    "stream_denoiser.backends.pulse_backend",
    "stream_denoiser.backends.wasapi_backend",
])
def test_audio_modules_do_not_import_portaudio(module):
    assert _portaudio_loaded_by(module) == []


def test_package_names_resolve_on_access():
    import stream_denoiser.backends as backends
    from stream_denoiser.backends import run_portaudio_loop, run_pulse_loop
    from stream_denoiser.backends.pulse_backend import run_pulse_loop as pulse
    from stream_denoiser.backends.sounddevice_backend import (
        run_portaudio_loop as portaudio)

    assert run_portaudio_loop is portaudio
    assert run_pulse_loop is pulse
    assert set(backends.__all__) <= set(dir(backends))
    with pytest.raises(AttributeError):
        backends.no_such_loop
