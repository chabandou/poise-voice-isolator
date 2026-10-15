"""
ONNX model helpers shared by the ONNX Runtime engines (DeepFilterNet3,
GTCRN): finding a vendored model file, and the tuned inference session.

onnxruntime is imported inside load_session(), never at import time.
"""
import os
import sys
from typing import List

from ..constants import ONNX_INTRA_OP_THREADS, ONNX_INTER_OP_THREADS
from ..logging_config import get_logger

_logger = get_logger(__name__)


def model_search_paths(file_name: str) -> List[str]:
    """
    Where a vendored model file may live, in search order: the package's
    models/ dir (in source checkouts, wheels and frozen builds alike),
    then next to the package, the repo root, the main script dir, or the
    cwd.
    """
    search_paths = []

    engines_dir = os.path.dirname(os.path.abspath(__file__))
    package_dir = os.path.dirname(engines_dir)
    search_paths.append(os.path.join(package_dir, 'models', file_name))
    search_paths.append(os.path.join(engines_dir, file_name))
    search_paths.append(os.path.join(engines_dir, '..', file_name))
    # Grandparent: repo root in dev checkouts, payload root in Nuitka
    # onefile bundles (data files land next to stream_denoiser/, not in it)
    search_paths.append(os.path.join(engines_dir, '..', '..', file_name))

    # Nuitka onefile payload root: the running binary lives next to the
    # bundled data files (verified: /proc/self/exe -> poise.bin in the
    # payload dir). Harmless in dev runs (points at the python binary's
    # dir, which never contains the model).
    if sys.platform.startswith("linux"):
        try:
            exe_dir = os.path.dirname(os.path.realpath("/proc/self/exe"))
            search_paths.append(os.path.join(exe_dir, file_name))
        except OSError:
            pass

    if hasattr(sys, 'argv') and sys.argv[0]:
        main_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        search_paths.append(os.path.join(main_dir, file_name))

    search_paths.append(os.path.join(os.getcwd(), file_name))

    if hasattr(sys, '_MEIPASS'):
        search_paths.append(os.path.join(sys._MEIPASS, file_name))

    return search_paths


def find_model_file(file_name: str, label: str) -> str:
    """
    First existing model_search_paths() entry for `file_name`.

    Raises FileNotFoundError listing every searched location; `label`
    names the model in that message (e.g. "DeepFilterNet3").
    """
    search_paths = model_search_paths(file_name)
    path = next((p for p in search_paths if os.path.exists(p)), None)
    if path is None:
        raise FileNotFoundError(
            f"{label} model not found: {file_name}\n"
            f"Searched in:\n" + "\n".join(f"  - {p}" for p in search_paths)
        )
    return path


def load_session(model_path: str, label: str):
    """Create the ONNX Runtime session with the repo's standard tuning."""
    import onnxruntime

    _logger.info(f"Loading {label} model: {model_path}")

    session_options = onnxruntime.SessionOptions()
    session_options.graph_optimization_level = (
        onnxruntime.GraphOptimizationLevel.ORT_ENABLE_ALL
    )
    session_options.intra_op_num_threads = ONNX_INTRA_OP_THREADS
    session_options.inter_op_num_threads = ONNX_INTER_OP_THREADS
    session_options.enable_mem_pattern = True
    session_options.enable_cpu_mem_arena = True

    providers = [
        ('CPUExecutionProvider', {
            'arena_extend_strategy': 'kSameAsRequested',
        })
    ]

    session = onnxruntime.InferenceSession(
        model_path,
        sess_options=session_options,
        providers=providers
    )
    _logger.info(f"{label} model loaded with optimizations")
    return session
