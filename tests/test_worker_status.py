"""The worker's status steps for the status bar (needs Qt; skipped without
it): which model loads, and where playback went back to on stop."""
import os

import pytest

pytest.importorskip("PyQt6.QtWidgets")


@pytest.fixture(scope="module")
def app():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class _Switcher:
    def __init__(self, original, restored=True):
        self.original_device = original
        self._restored = restored

    def restore_original_device(self):
        return self._restored


def _worker_and_log():
    from stream_denoiser.gui.worker import AudioWorker
    worker = AudioWorker()
    said = []
    worker.status_changed.connect(said.append)
    return worker, said


def test_loading_names_the_model(app):
    from stream_denoiser.constants import MODEL_INFO
    worker, _ = _worker_and_log()
    for model_id, info in MODEL_INFO.items():
        worker.model = model_id
        assert worker._model_label() == info.get("label", "model")
    worker.model = "no-such-model"
    assert worker._model_label() == "model"


def test_stopping_says_where_playback_went_back(app):
    worker, said = _worker_and_log()
    worker._vb_cable_switcher = _Switcher("Speakers (Realtek(R) Audio)")
    worker._cleanup()
    assert said == ["Restored playback to Speakers (Realtek(R) Audio)",
                    "Stopped"]
    assert worker._vb_cable_switcher is None


@pytest.mark.parametrize("switcher", [
    None,                                            # never switched
    _Switcher("Speakers", restored=False),           # restore failed
    _Switcher(None),                                 # original unknown
    _Switcher("CABLE Input (VB-Audio Virtual Cable)"),   # was already CABLE
])
def test_no_restore_message_when_nothing_was_restored(app, switcher):
    worker, said = _worker_and_log()
    worker._vb_cable_switcher = switcher
    worker._cleanup()
    assert said == ["Stopped"]
