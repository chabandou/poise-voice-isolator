"""The UI process stays free of numpy (and of the audio stack).

The audio runs in its own process (audio_host); the UI only lists models,
picks devices and hands the session over. numpy there cost ~16 MB of
working set and about a fifth of a second of startup, pulled in by imports
the UI never needed (see engines/availability.py, backends/choice.py).
Checked in a fresh interpreter: this test process has numpy loaded.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("PyQt6.QtWidgets")

ROOT = Path(__file__).resolve().parent.parent

_UI_RUN = """
import os, sys, tempfile, time
sys.path.insert(0, {root!r})
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                  tempfile.mkdtemp(prefix="poise-test-config-"))
app = QApplication([])
from stream_denoiser.gui.main_window import MainWindow
win = MainWindow()
win.show()
end = time.time() + 0.5
while time.time() < end:
    app.processEvents()
# What Start loads in the UI before the audio process takes over.
from stream_denoiser.gui.worker import AudioWorker
worker = AudioWorker()
from stream_denoiser.device_utils import find_loopback_device
from stream_denoiser.backends.choice import windows_backend_preference
windows_backend_preference()
heavy = [m for m in ("numpy", "onnxruntime", "stream_denoiser.processor",
                     "stream_denoiser.engines.base")
         if m in sys.modules]
print("heavy:", ",".join(heavy))
"""


def test_the_ui_process_loads_no_numpy():
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    run = subprocess.run([sys.executable, "-c", _UI_RUN.format(root=str(ROOT))],
                         capture_output=True, text=True, timeout=120, env=env)
    lines = [l for l in run.stdout.splitlines() if l.startswith("heavy:")]
    assert run.returncode == 0 and lines, run.stderr[-2000:]
    assert lines[-1] == "heavy: ", lines[-1]


def test_the_engines_package_is_light_until_an_engine_is_used():
    code = ("import sys; sys.path.insert(0, %r)\n"
            "import stream_denoiser.engines as e\n"
            "e.available_models(); e.model_unavailable_reason('gtcrn')\n"
            "light = 'numpy' not in sys.modules\n"
            "e.RNNoiseEngine\n"
            "print(light, 'numpy' in sys.modules)" % str(ROOT))
    run = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, timeout=60)
    assert run.stdout.split() == ["True", "True"], run.stderr[-2000:]
