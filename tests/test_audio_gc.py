"""The audio loop runs with the cyclic garbage collector off (audio_gc).

That is only safe while the hot path creates no reference cycles:
anything cyclic it allocated would stay in memory until the run stops.
"""
import gc
import logging
import time

import numpy as np
import pytest

from stream_denoiser import audio_gc
from stream_denoiser.audio_gc import gc_paused


@pytest.fixture
def gc_log():
    lines = []
    handler = logging.Handler(logging.INFO)
    handler.emit = lambda record: lines.append(record.getMessage())
    audio_gc._logger.addHandler(handler)
    yield lines
    audio_gc._logger.removeHandler(handler)


def test_paused_turns_the_collector_off_and_back_on(gc_log):
    assert gc.isenabled()
    with gc_paused():
        assert not gc.isenabled()
        assert gc.get_freeze_count() > 0
    assert gc.isenabled()
    assert gc.get_freeze_count() == 0
    assert len(gc_log) == 1 and gc_log[0].startswith("gc: off for the run")


def test_paused_restores_a_collector_that_was_off():
    gc.disable()
    try:
        with gc_paused():
            pass
        assert not gc.isenabled()
    finally:
        gc.enable()


def test_paused_reports_cycles_the_run_left(gc_log):
    with gc_paused():
        a = []
        a.append(a)
        del a
        kept = [[]]
    assert "objects, 1 of them unreachable" in gc_log[0]
    left = int(gc_log[0].split("the run left ")[1].split()[0])
    assert left >= 3  # the cycle and the two kept lists
    del kept


def test_disabled_changes_nothing(gc_log):
    with gc_paused(False):
        assert gc.isenabled()
    assert gc_log == []


def _speech_like(frame: int, frames: int) -> np.ndarray:
    """A vowel-ish tone with silent stretches: the AAD switches between
    engine and bypass, and resuming re-primes the engine."""
    t = np.arange(frame * frames) / 48000.0
    x = 0.2 * np.sin(2 * np.pi * 180 * t) * (1 + np.sin(2 * np.pi * 900 * t))
    for start in range(40, frames, 80):
        x[start * frame:(start + 40) * frame] = 0.0
    return x.astype(np.float32)


@pytest.mark.parametrize("model", ["deepfilternet3", "rnnoise"])
def test_processing_makes_no_reference_cycles(model):
    from stream_denoiser.engines import create_engine, model_unavailable_reason
    from stream_denoiser.processor import DenoiserAudioProcessor
    reason = model_unavailable_reason(model)
    if reason:
        pytest.skip(reason)
    engine = create_engine(model)
    frame = engine.required_frame_size or 480
    processor = DenoiserAudioProcessor(engine, target_sr=48000,
                                       frame_size=frame, enable_aad=True)
    audio = _speech_like(frame, 400)
    try:
        for i in range(50):  # warm-up: lazy allocations happen once
            processor.process_chunk(audio[i * frame:(i + 1) * frame].copy())
        gc.collect()
        gc.freeze()
        gc.disable()
        try:
            for i in range(400):
                processor.process_chunk(
                    audio[i * frame:(i + 1) * frame].copy())
                processor.get_diagnostics()
            assert gc.collect() == 0
        finally:
            gc.unfreeze()
            gc.enable()
    finally:
        processor.close()


def test_pipewire_worker_loop_makes_no_reference_cycles(monkeypatch):
    """The loop around the processor: frame exchange, event and stats
    checks, and the stats callback, all on every frame here."""
    from stream_denoiser.backends import node_loop
    from stream_denoiser.backends import pipewire_backend as pwb
    from stream_denoiser.backends.delay_core import (
        STAT_NAMES, WAIT_STOPPED, WAIT_TIMEOUT)
    monkeypatch.setattr(node_loop, "EVENT_CHECK_SEC", 0.0)

    class Node:
        frame = 4
        delay_samples = latency_samples = 0

        def __init__(self, script):
            self.script = script
            self.calls = 0

        def wait_frame(self, buf, timeout_ms):
            if not self.script:
                return WAIT_STOPPED
            k = self.script.pop()
            if k >= 0:
                buf[:] = 0.1
            return k

        def put_frame(self, k, out):
            pass

        def stats(self):
            self.calls += 1
            return dict.fromkeys(STAT_NAMES, 0)

        def error(self):
            return None

    class Processor:
        def process_chunk(self, x):
            return x * 2.0

        def get_stats(self):
            return {"frame_count": 1, "rtf": 0.1}

    sent = []
    script = [WAIT_TIMEOUT if i % 7 == 0 else i for i in range(3000)]
    node = Node(script)
    # Warm-up pass, then the measured one.
    node_loop.worker_loop(Node(list(script[:50])), Processor(), None,
                          lambda s, e: sent.append(len(s)), 0.0, time.time(),
                          log_sync=pwb._log_sync)
    gc.collect()
    gc.freeze()
    gc.disable()
    try:
        node_loop.worker_loop(node, Processor(), None,
                              lambda s, e: sent.append(len(s)), 0.0,
                              time.time(), log_sync=pwb._log_sync)
        assert gc.collect() == 0
    finally:
        gc.unfreeze()
        gc.enable()
    assert node.calls > 1 and sent
