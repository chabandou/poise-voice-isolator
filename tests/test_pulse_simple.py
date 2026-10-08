"""Unit tests for the pulse-simple backend (fake CDLL, no server needed)."""
import ctypes
import sys
import types

import numpy as np
import pytest

from stream_denoiser.backends import pulse_simple as ps


class FakeLib:
    """Minimal fake libpulse-simple honouring the ctypes call shapes."""

    def __init__(self, frames=480, channels=2, pattern=None, fail_new=False,
                 fail_code=1):
        self.frames = frames
        self.channels = channels
        self.fail_new = fail_new
        self.fail_code = fail_code
        self.new_attrs = []
        self.freed = []
        self.flushed = []
        self.written = []
        self.latency_usec = 10670
        if pattern is None:
            # Stereo pattern: L=+0.5, R=-0.5 -> mono mean 0.0; tests override.
            self.pattern = np.tile(np.array([0.5, -0.5], dtype=np.float32),
                                   frames)
        else:
            self.pattern = np.ascontiguousarray(pattern, dtype=np.float32)

    # -- pa_simple_new -----------------------------------------------------
    def pa_simple_new(self, server, app, direction, dev, stream, ss, mapping,
                      attr, err):
        # Record buffer attrs for starting-value assertions.
        try:
            a = ctypes.cast(attr, ctypes.POINTER(ps.pa_buffer_attr)).contents
            self.new_attrs.append(
                (a.maxlength, a.tlength, a.prebuf, a.minreq, a.fragsize))
        except Exception:
            self.new_attrs.append(None)
        if self.fail_new:
            try:
                ctypes.cast(err, ctypes.POINTER(ctypes.c_int)).contents.value = self.fail_code
            except Exception:
                pass
            return 0
        try:
            ctypes.cast(err, ctypes.POINTER(ctypes.c_int)).contents.value = 0
        except Exception:
            pass
        return 0xABCD

    def pa_strerror(self, code):
        return f"fake pulse error {code}".encode("utf-8")

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _addr(ptr):
        if isinstance(ptr, int):
            return ptr
        try:
            return ptr.value
        except AttributeError:
            pass
        try:
            return ctypes.cast(ptr, ctypes.c_void_p).value
        except Exception:
            return int(ptr)

    # -- pa_simple_read ----------------------------------------------------
    def pa_simple_read(self, handle, data, nbytes, err):
        addr = self._addr(data)
        n = int(nbytes) if not hasattr(nbytes, "value") else int(nbytes.value)
        src = np.ascontiguousarray(self.pattern[:n // 4], dtype=np.float32)
        ctypes.memmove(addr, src.ctypes.data, src.nbytes)
        try:
            ctypes.cast(err, ctypes.POINTER(ctypes.c_int)).contents.value = 0
        except Exception:
            pass
        return 0

    # -- pa_simple_write ---------------------------------------------------
    def pa_simple_write(self, handle, data, nbytes, err):
        addr = self._addr(data)
        n = int(nbytes) if not hasattr(nbytes, "value") else int(nbytes.value)
        buf = (ctypes.c_char * n).from_address(addr)
        self.written.append(bytes(buf))
        try:
            ctypes.cast(err, ctypes.POINTER(ctypes.c_int)).contents.value = 0
        except Exception:
            pass
        return 0

    def pa_simple_flush(self, handle, err):
        self.flushed.append(handle)
        try:
            ctypes.cast(err, ctypes.POINTER(ctypes.c_int)).contents.value = 0
        except Exception:
            pass
        return 0

    def pa_simple_get_latency(self, handle, err):
        try:
            ctypes.cast(err, ctypes.POINTER(ctypes.c_int)).contents.value = 0
        except Exception:
            pass
        return self.latency_usec

    def pa_simple_free(self, handle):
        self.freed.append(handle)


def _patch(monkeypatch, fake):
    monkeypatch.setattr(ps, "_lib", None)
    monkeypatch.setattr(ps, "_load_library", lambda: fake)
    return fake


def test_capture_shape_and_contiguity(monkeypatch):
    frames = 480
    pattern = np.tile(np.array([1.0, 3.0], dtype=np.float32), frames)
    fake = _patch(monkeypatch, FakeLib(frames=frames, pattern=pattern))
    cap = ps.PulseCapture("Poise_Capture.monitor", frames)
    audio, overflowed = cap.read()
    assert overflowed is False
    assert audio.shape == (frames, 1)
    assert audio.dtype == np.float32
    assert audio.flags["C_CONTIGUOUS"]
    # (L+R)/2 downmix.
    np.testing.assert_allclose(audio[:, 0], 2.0, atol=1e-6)
    cap.close()


def test_capture_mono_passthrough(monkeypatch):
    frames = 256
    pattern = np.full(frames, 0.25, dtype=np.float32)
    fake = _patch(monkeypatch, FakeLib(frames=frames, channels=1,
                                       pattern=pattern))
    cap = ps.PulseCapture("src", frames, channels=1)
    audio, overflowed = cap.read()
    assert overflowed is False
    assert audio.shape == (frames, 1)
    np.testing.assert_allclose(audio[:, 0], 0.25, atol=1e-6)
    cap.close()


def test_capture_buffer_attr_fragsize_one_block(monkeypatch):
    frames = 512
    fake = _patch(monkeypatch, FakeLib(frames=frames))
    cap = ps.PulseCapture("src", frames)
    assert fake.new_attrs, "pa_simple_new was not called"
    maxlength, tlength, prebuf, minreq, fragsize = fake.new_attrs[0]
    assert fragsize == frames * 2 * 4  # 1 block stereo float32
    cap.close()


def test_playback_buffer_attrs_and_write(monkeypatch):
    frames = 480
    fake = _patch(monkeypatch, FakeLib(frames=frames))
    play = ps.PulsePlayback("my-sink", frames)
    maxlength, tlength, prebuf, minreq, fragsize = fake.new_attrs[0]
    block = frames * 2 * 4
    assert tlength == 3 * block
    assert prebuf == 1 * block
    mono = np.full((frames, 1), 0.1, dtype=np.float32)
    play.write(mono)
    assert len(fake.written) == 1
    back = np.frombuffer(fake.written[0], dtype=np.float32).reshape(frames, 2)
    np.testing.assert_allclose(back[:, 0], 0.1, atol=1e-6)
    np.testing.assert_allclose(back[:, 1], 0.1, atol=1e-6)
    # Wrong size raises.
    with pytest.raises(ValueError):
        play.write(np.zeros((frames - 1, 1), dtype=np.float32))
    play.close()


def test_error_mapping_uses_pa_strerror(monkeypatch):
    fake = _patch(monkeypatch, FakeLib(fail_new=True, fail_code=7))
    with pytest.raises(ps.PulseError, match="fake pulse error 7"):
        ps.PulseCapture("nope", 480)


def test_close_idempotent_flushes(monkeypatch):
    fake = _patch(monkeypatch, FakeLib())
    cap = ps.PulseCapture("src", 480)
    cap.close()
    cap.close()
    assert len(fake.freed) == 1
    assert len(fake.flushed) == 1  # flush, never blocking drain


def test_latency_ms(monkeypatch):
    fake = _patch(monkeypatch, FakeLib())
    fake.latency_usec = 10670
    cap = ps.PulseCapture("src", 480)
    assert cap.latency_ms() == pytest.approx(10.67, abs=0.01)
    cap.close()
    assert cap.latency_ms() == -1.0


def test_context_manager(monkeypatch):
    fake = _patch(monkeypatch, FakeLib())
    with ps.PulsePlayback("sink", 128) as play:
        play.write(np.zeros((128, 2), dtype=np.float32))
    assert len(fake.freed) == 1
