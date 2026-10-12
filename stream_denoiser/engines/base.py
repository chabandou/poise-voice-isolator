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
