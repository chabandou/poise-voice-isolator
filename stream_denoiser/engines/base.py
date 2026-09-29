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

    def close(self) -> None:
        """Release any native resources. Safe to call more than once."""
