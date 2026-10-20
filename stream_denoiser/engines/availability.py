"""
Which models can run here

Whether each engine's model files (or library) are present, without
loading the engines themselves: the UI lists and explains the models
from these, and stays free of numpy and ONNX Runtime.
"""
import os
import sys
from typing import List, Optional

from .onnx_model import find_model_file
from .rnnoise_lib import _load_library
from ..constants import (
    DEFAULT_DF3_ONNX,
    GTCRN_ONNX,
    MODEL_DEEPFILTERNET3,
    MODEL_GTCRN,
    MODEL_RNNOISE,
)


def _search_model_files(onnx_name: str, states_name: Optional[str] = None):
    """
    Locate the DF3 ONNX file (and its states .npz) in the usual locations
    (see onnx_model.model_search_paths).

    Returns (onnx_path, states_path); states_path is resolved as the
    `<onnx_stem>_states.npz` sibling unless states_name is given.
    Raises FileNotFoundError listing every searched location.
    """
    onnx_path = find_model_file(onnx_name, "DeepFilterNet3")

    if states_name is None:
        stem, _ = os.path.splitext(os.path.basename(onnx_path))
        states_name = stem + '_states.npz'
    states_path = os.path.join(os.path.dirname(onnx_path), states_name)
    if not os.path.exists(states_path):
        raise FileNotFoundError(
            f"DeepFilterNet3 states not found: {states_path}\n"
            f"(expected next to {onnx_path})"
        )
    return onnx_path, states_path


def df3_available() -> bool:
    """True if the vendored DF3 model files can be found."""
    try:
        _search_model_files(DEFAULT_DF3_ONNX)
        return True
    except FileNotFoundError:
        return False


def gtcrn_available() -> bool:
    """True if the vendored GTCRN model file can be found."""
    try:
        find_model_file(GTCRN_ONNX, "GTCRN")
        return True
    except FileNotFoundError:
        return False


def rnnoise_available() -> bool:
    """True if librnnoise can be loaded on this machine."""
    try:
        _load_library()
        return True
    except RuntimeError:
        return False


def available_models() -> List[str]:
    """Model names usable on this machine (needs model files / native lib)."""
    models = []
    if df3_available():
        models.append(MODEL_DEEPFILTERNET3)
    if gtcrn_available():
        models.append(MODEL_GTCRN)
    if rnnoise_available():
        models.append(MODEL_RNNOISE)
    return models


def model_unavailable_reason(name: str) -> Optional[str]:
    """
    Why a model cannot be used on this machine, or None if available.

    Used by the UI to explain unavailable entries (with install hints).
    """
    key = (name or "").strip().lower()
    if key == MODEL_DEEPFILTERNET3 and not df3_available():
        return ("model files not found "
                "(denoiser_model_df3.onnx + denoiser_model_df3_states.npz)")
    if key == MODEL_GTCRN and not gtcrn_available():
        return f"model file not found ({GTCRN_ONNX})"
    if key == MODEL_RNNOISE and not rnnoise_available():
        if sys.platform == "win32":
            return "rnnoise.dll not found next to the app (reinstall Poise)"
        return "librnnoise not installed (e.g. 'sudo pacman -S rnnoise' on Arch)"
    return None
