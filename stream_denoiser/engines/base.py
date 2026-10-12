"""
Denoise Engine Base Class

Common interface implemented by every denoising model backend
(DeepFilterNet via ONNX Runtime, RNNoise via librnnoise, ...).
"""
from abc import ABC, abstractmethod
from typing import Optional

import numpy as np


class DenoiseEngine(ABC):
    """
    A stateful, frame-based denoiser.

    Engines receive mono float32 frames in the [-1.0, 1.0] range and return
    frames of the same shape and range. Any model-specific scaling, state
    handling or native memory management stays inside the engine.
    """

    #: Short identifier used by the CLI flag, settings and stats (e.g. "rnnoise")
    name: str = "base"

    #: Frame size (in samples) the engine requires, or None if it is flexible
    required_frame_size: Optional[int] = None

    #: Input-to-output delay of the model itself (samples): output sample n
    #: corresponds to input sample n - latency_samples. The dry mix, the
    #: processor's AAD bypass and the PipeWire node's unprocessed fallback
    #: are all delayed by this much to stay aligned with processed audio.
    latency_samples: int = 0

    #: Latest speech probability in [0, 1] if the model provides one, else None
    speech_prob: Optional[float] = None

    @abstractmethod
    def process_frame(self, frame: np.ndarray) -> np.ndarray:
        """
        Denoise a single frame.

        Args:
            frame: Mono float32 samples in [-1.0, 1.0]

        Returns:
            Enhanced samples (float32, nominally the same length as `frame`)
        """

    @abstractmethod
    def reset(self) -> None:
        """Reset all streaming state (call between unrelated audio streams)."""

    def set_atten_lim_db(self, atten_lim_db: Optional[float]) -> None:
        """
        Change the attenuation limit while streaming.

        Safe to call from another thread: engines read the new value once
        at the start of the next frame and ramp to it across that frame.
        The default only records the value (for engines without a limit).
        """
        self.atten_lim_db = atten_lim_db

    def close(self) -> None:
        """Release any native resources. Safe to call more than once."""


class DelayLine:
    """
    Fixed whole-sample delay for a stream of frames (any frame length).

    process() returns its input `delay` samples late, starting with
    silence. The line also remembers `history` samples beyond the delay,
    so recent() can return up to `delay + history` samples of past input.
    """

    def __init__(self, delay: int, history: int = 0):
        if delay < 0 or history < 0:
            raise ValueError("delay and history must be >= 0")
        self.delay = int(delay)
        self._buf = np.zeros(self.delay + int(history), dtype=np.float32)

    def process(self, frame: np.ndarray) -> np.ndarray:
        """Push `frame`; return the same number of samples, delayed."""
        n = frame.shape[0]
        size = self._buf.shape[0]
        joined = np.concatenate(
            (self._buf, np.asarray(frame, dtype=np.float32)))
        start = size - self.delay
        out = joined[start:start + n].copy()
        self._buf = joined[n:]
        return out

    def recent(self, n: int) -> np.ndarray:
        """The last `n` samples pushed (zeros before the first push)."""
        if not 0 <= n <= self._buf.shape[0]:
            raise ValueError(f"only {self._buf.shape[0]} samples are kept")
        return self._buf[self._buf.shape[0] - n:].copy()

    def reset(self) -> None:
        self._buf = np.zeros_like(self._buf)


def mix_dry(wet: np.ndarray, dry: np.ndarray,
            start: float, end: float) -> np.ndarray:
    """
    Blend dry input back into the enhanced frame: y = f*dry + (1-f)*wet.

    f ramps linearly from `start` to `end` across the frame, so a changed
    attenuation limit fades in instead of stepping (no click).
    """
    if start == end:
        return end * dry + (1.0 - end) * wet
    f = np.linspace(start, end, wet.shape[0] + 1, dtype=np.float32)[1:]
    return f * dry + (1.0 - f) * wet
