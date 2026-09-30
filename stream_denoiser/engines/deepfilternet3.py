"""
DeepFilterNet3 Engine

Runs the vendored DeepFilterNet3 streaming ONNX model
(`denoiser_model_df3.onnx` + `denoiser_model_df3_states.npz`) through
ONNX Runtime. Owns the model's recurrent/convolutional streaming state
(12 tensors: norm states, STFT overlap buffers, GRU hidden states)
between frames.

512-sample frames at 48 kHz (10.67 ms), explicit state inputs/outputs,
155-node graph — ~2x faster per frame on CPU than the previous model.
"""
import os
import sys
from typing import Dict, Optional

import numpy as np

from .base import DenoiseEngine
from ..constants import (
    MODEL_DEEPFILTERNET3,
    ONNX_INTRA_OP_THREADS,
    ONNX_INTER_OP_THREADS,
)
from ..logging_config import get_logger

_logger = get_logger(__name__)

DEFAULT_DF3_ONNX = 'denoiser_model_df3.onnx'
DEFAULT_DF3_STATES = 'denoiser_model_df3_states.npz'


def _search_model_files(onnx_name: str, states_name: Optional[str] = None):
    """
    Locate the DF3 ONNX file (and its states .npz) in the usual locations:
    next to the package, the repo root, the main script dir, or the cwd.

    Returns (onnx_path, states_path); states_path is resolved as the
    `<onnx_stem>_states.npz` sibling unless states_name is given.
    Raises FileNotFoundError listing every searched location.
    """
    search_paths = []

    script_dir = os.path.dirname(os.path.abspath(__file__))
    search_paths.append(os.path.join(script_dir, onnx_name))
    search_paths.append(os.path.join(script_dir, '..', onnx_name))
    # Grandparent: repo root in dev checkouts, payload root in Nuitka
    # onefile bundles (data files land next to stream_denoiser/, not in it)
    search_paths.append(os.path.join(script_dir, '..', '..', onnx_name))

    # Nuitka onefile payload root: the running binary lives next to the
    # bundled data files (verified: /proc/self/exe -> poise.bin in the
    # payload dir). Harmless in dev runs (points at the python binary's
    # dir, which never contains the model).
    if sys.platform.startswith("linux"):
        try:
            exe_dir = os.path.dirname(os.path.realpath("/proc/self/exe"))
            search_paths.append(os.path.join(exe_dir, onnx_name))
        except OSError:
            pass

    if hasattr(sys, 'argv') and sys.argv[0]:
        main_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        search_paths.append(os.path.join(main_dir, onnx_name))

    search_paths.append(os.path.join(os.getcwd(), onnx_name))

    if hasattr(sys, '_MEIPASS'):
        search_paths.append(os.path.join(sys._MEIPASS, onnx_name))

    onnx_path = next((p for p in search_paths if os.path.exists(p)), None)
    if onnx_path is None:
        raise FileNotFoundError(
            f"DeepFilterNet3 model not found: {onnx_name}\n"
            f"Searched in:\n" + "\n".join(f"  - {p}" for p in search_paths)
        )

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


def _to_df3_atten_lim_db(atten_lim_db: Optional[float]) -> Optional[float]:
    """
    Convert the repo attenuation-limit convention to the DF3 dry-mix form.

    Repo convention (shared with the v1 engine and RNNoise): negative dB,
    e.g. -60.0 means "suppress up to 60 dB" (a tiny fraction of dry signal
    is mixed back in: y = f*dry + (1-f)*wet, f = 10**(atten/20)).
    Positive inputs are passed through unchanged (assumed DF3 convention);
    None disables the dry mix entirely (full suppression).
    """
    if atten_lim_db is None:
        return None
    if atten_lim_db <= 0.0:
        return -atten_lim_db
    return atten_lim_db


class DeepFilterNet3Engine(DenoiseEngine):
    """DeepFilterNet3 ONNX model with streaming state."""

    name = MODEL_DEEPFILTERNET3

    def __init__(self, onnx_session,
                 initial_states: Dict[str, np.ndarray],
                 atten_lim_db: float = -60.0):
        """
        Args:
            onnx_session: ONNX Runtime inference session for the DF3 model
            initial_states: {state_input_name: float32 array} start states
            atten_lim_db: Attenuation limit in dB (repo convention, negative,
                e.g. -60.0). A fraction of the dry input is mixed back in.
        """
        self.onnx_session = onnx_session
        self.input_names = [i.name for i in onnx_session.get_inputs()]
        self.output_names = [o.name for o in onnx_session.get_outputs()]
        self.atten_lim_db = atten_lim_db

        self.required_frame_size = int(onnx_session.get_inputs()[0].shape[0])

        self._init_states = {
            k: np.ascontiguousarray(v, dtype=np.float32)
            for k, v in initial_states.items()
        }
        self._states = {k: v.copy() for k, v in self._init_states.items()}

        self._dry_db = _to_df3_atten_lim_db(atten_lim_db)
        self._dry_lin = (
            float(10.0 ** (-self._dry_db / 20.0))
            if self._dry_db is not None else None
        )
        self._dry_buf = (
            np.zeros(self.required_frame_size, dtype=np.float32)
            if self._dry_lin is not None else None
        )

    @classmethod
    def from_path(cls, onnx_path: str = DEFAULT_DF3_ONNX,
                  states_path: Optional[str] = None,
                  atten_lim_db: float = -60.0) -> "DeepFilterNet3Engine":
        """Load the vendored DF3 model (searching the usual locations)."""
        model_path, states_file = _search_model_files(onnx_path, states_path)
        session = _load_df3_session(model_path)
        with np.load(states_file) as z:
            initial = {k: z[k].astype(np.float32) for k in z.files}
        return cls(session, initial, atten_lim_db=atten_lim_db)

    @classmethod
    def is_available(cls) -> bool:
        """True if the vendored DF3 model files can be found."""
        try:
            _search_model_files(DEFAULT_DF3_ONNX)
            return True
        except FileNotFoundError:
            return False

    def process_frame(self, frame: np.ndarray) -> np.ndarray:
        feeds = {'input_frame': np.ascontiguousarray(frame, dtype=np.float32)}
        feeds.update(self._states)
        res = self.onnx_session.run(self.output_names, feeds)
        enhanced = np.ascontiguousarray(res[0], dtype=np.float32).reshape(-1)
        # outputs[0] is audio; outputs[1:] are the new states in input order
        # ("new_<input_name>"). Assign directly: ORT returns fresh arrays.
        for out_name, val in zip(self.output_names[1:], res[1:]):
            in_name = out_name[4:] if out_name.startswith('new_') else out_name
            self._states[in_name] = val

        if self._dry_lin is not None and self._dry_lin > 0.0:
            # One-frame-delayed dry mix (matches the reference DF3 streamer).
            dry = self._dry_buf
            self._dry_buf = np.ascontiguousarray(frame, dtype=np.float32).copy()
            lin = self._dry_lin
            enhanced = lin * dry + (1.0 - lin) * enhanced
        return enhanced.astype(np.float32, copy=False)

    def reset(self) -> None:
        self._states = {k: v.copy() for k, v in self._init_states.items()}
        if self._dry_lin is not None:
            self._dry_buf = np.zeros(self.required_frame_size, dtype=np.float32)


def _load_df3_session(model_path: str):
    """Create the ONNX Runtime session with the repo's standard tuning."""
    import onnxruntime

    _logger.info(f"Loading DeepFilterNet3 model: {model_path}")

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
    _logger.info("DeepFilterNet3 model loaded with optimizations")
    return session
