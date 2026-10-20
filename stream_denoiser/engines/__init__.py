"""
Denoising engines

A DenoiseEngine wraps one model (DeepFilterNet3 and GTCRN via ONNX Runtime,
RNNoise via librnnoise) behind a common frame-based interface used by
DenoiserAudioProcessor.
"""
import importlib

from .availability import available_models, model_unavailable_reason
from ..constants import (
    ALL_MODELS,
    DEFAULT_DF3_ONNX,
    DEFAULT_MODEL,
    MODEL_DEEPFILTERNET3,
    MODEL_GTCRN,
    MODEL_RNNOISE,
)

# The engines (numpy, ONNX Runtime) load on first use: importing this
# package (the UI does, to list the models) loads only the light names.
_LAZY = {
    "DenoiseEngine": ".base",
    "DeepFilterNet3Engine": ".deepfilternet3",
    "GTCRNEngine": ".gtcrn",
    "RNNoiseEngine": ".rnnoise",
}


def __getattr__(name):
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module, __name__), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(_LAZY))


def create_engine(name: str = DEFAULT_MODEL,
                  onnx_path: str = DEFAULT_DF3_ONNX,
                  atten_lim_db: float = -60.0) -> "DenoiseEngine":
    """
    Create a denoising engine by model name.

    Args:
        name: "deepfilternet3", "gtcrn" or "rnnoise"
        onnx_path: Path to the ONNX model file (deepfilternet3 only).
            The default selects the vendored DF3 model; pass a custom DF3
            .onnx to use a <stem>_states.npz sibling next to it.
            Ignored for gtcrn and rnnoise.
        atten_lim_db: Attenuation limit in dB

    Raises:
        ValueError: Unknown model name
        FileNotFoundError: Model file not found
        RuntimeError: RNNoise library unavailable
    """
    from .deepfilternet3 import DeepFilterNet3Engine
    from .gtcrn import GTCRNEngine
    from .rnnoise import RNNoiseEngine

    key = (name or DEFAULT_MODEL).strip().lower()
    if key == MODEL_DEEPFILTERNET3:
        if onnx_path == DEFAULT_DF3_ONNX:
            # Untouched default: use the vendored DF3 model files.
            return DeepFilterNet3Engine.from_path(atten_lim_db=atten_lim_db)
        return DeepFilterNet3Engine.from_path(onnx_path, atten_lim_db=atten_lim_db)
    if key == MODEL_GTCRN:
        return GTCRNEngine.from_path(atten_lim_db=atten_lim_db)
    if key == MODEL_RNNOISE:
        return RNNoiseEngine(atten_lim_db=atten_lim_db)
    raise ValueError(f"Unknown model '{name}'. Choose from: {', '.join(ALL_MODELS)}")


__all__ = [
    "DenoiseEngine",
    "DeepFilterNet3Engine",
    "GTCRNEngine",
    "RNNoiseEngine",
    "create_engine",
    "available_models",
    "model_unavailable_reason",
    "DEFAULT_DF3_ONNX",
]
