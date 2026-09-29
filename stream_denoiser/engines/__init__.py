"""
Denoising engines

A DenoiseEngine wraps one model (DeepFilterNet via ONNX Runtime, RNNoise via
librnnoise) behind a common frame-based interface used by DenoiserAudioProcessor.
"""
from typing import List, Optional

from .base import DenoiseEngine
from .deepfilternet3 import (
    DeepFilterNet3Engine,
    DEFAULT_DF3_ONNX,
)
from .rnnoise import RNNoiseEngine
from ..constants import (
    ALL_MODELS,
    DEFAULT_MODEL,
    MODEL_DEEPFILTERNET3,
    MODEL_RNNOISE,
)


def available_models() -> List[str]:
    """Model names usable on this machine (needs model files / native lib)."""
    models = []
    if DeepFilterNet3Engine.is_available():
        models.append(MODEL_DEEPFILTERNET3)
    if RNNoiseEngine.is_available():
        models.append(MODEL_RNNOISE)
    return models


def model_unavailable_reason(name: str) -> Optional[str]:
    """
    Why a model cannot be used on this machine, or None if available.

    Used by the UI to explain unavailable entries (with install hints).
    """
    key = (name or "").strip().lower()
    if key == MODEL_DEEPFILTERNET3 and not DeepFilterNet3Engine.is_available():
        return ("model files not found "
                "(denoiser_model_df3.onnx + denoiser_model_df3_states.npz)")
    if key == MODEL_RNNOISE and not RNNoiseEngine.is_available():
        return "librnnoise not installed (e.g. 'sudo pacman -S rnnoise' on Arch)"
    return None


def create_engine(name: str = DEFAULT_MODEL,
                  onnx_path: str = DEFAULT_DF3_ONNX,
                  atten_lim_db: float = -60.0) -> DenoiseEngine:
    """
    Create a denoising engine by model name.

    Args:
        name: "deepfilternet3" or "rnnoise"
        onnx_path: Path to the ONNX model file (deepfilternet3 only).
            The default selects the vendored DF3 model; pass a custom DF3
            .onnx to use a <stem>_states.npz sibling next to it.
            Ignored for rnnoise.
        atten_lim_db: Attenuation limit in dB

    Raises:
        ValueError: Unknown model name
        FileNotFoundError: Model file not found
        RuntimeError: RNNoise library unavailable
    """
    key = (name or DEFAULT_MODEL).strip().lower()
    if key == MODEL_DEEPFILTERNET3:
        if onnx_path == DEFAULT_DF3_ONNX:
            # Untouched default: use the vendored DF3 model files.
            return DeepFilterNet3Engine.from_path(atten_lim_db=atten_lim_db)
        return DeepFilterNet3Engine.from_path(onnx_path, atten_lim_db=atten_lim_db)
    if key == MODEL_RNNOISE:
        return RNNoiseEngine(atten_lim_db=atten_lim_db)
    raise ValueError(f"Unknown model '{name}'. Choose from: {', '.join(ALL_MODELS)}")


__all__ = [
    "DenoiseEngine",
    "DeepFilterNet3Engine",
    "RNNoiseEngine",
    "create_engine",
    "available_models",
    "model_unavailable_reason",
    "DEFAULT_DF3_ONNX",
]
