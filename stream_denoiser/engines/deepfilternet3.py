"""
DeepFilterNet3 Engine

Runs the vendored DeepFilterNet3 streaming ONNX model
(`denoiser_model_df3.onnx` + `denoiser_model_df3_states.npz`) through
ONNX Runtime. Owns the model's recurrent/convolutional streaming state
(12 tensors: norm states, STFT overlap buffers, GRU hidden states)
between frames.

512-sample frames at 48 kHz (10.67 ms), explicit state inputs/outputs,
155-node graph — ~2x faster per frame on CPU than the previous model.
The vendored file is that export rewritten by tools/optimize_df3.py (its
inverse FFT done as small MatMuls instead of a 4.2 MB matrix): same inputs,
outputs and states, same output to within float rounding.
"""
import os
from typing import Dict, Optional

import numpy as np

from .base import DelayLine, DenoiseEngine, mix_dry
from .onnx_model import find_model_file, load_session
from ..constants import MODEL_DEEPFILTERNET3

DEFAULT_DF3_ONNX = 'denoiser_model_df3.onnx'
DEFAULT_DF3_STATES = 'denoiser_model_df3_states.npz'


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


def _dry_lin_for(atten_lim_db: Optional[float]) -> float:
    """Linear dry-mix fraction for an attenuation limit (0.0 = no dry mix)."""
    dry_db = _to_df3_atten_lim_db(atten_lim_db)
    return 0.0 if dry_db is None else float(10.0 ** (-dry_db / 20.0))


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
        # Measured on speech by cross-correlation: 1536 samples at 512.
        self.latency_samples = 3 * self.required_frame_size

        self._init_states = {
            k: np.ascontiguousarray(v, dtype=np.float32)
            for k, v in initial_states.items()
        }
        self._states = {k: v.copy() for k, v in self._init_states.items()}

        # Applied mix and the one set_atten_lim_db() asks for; the next
        # frame ramps from the first to the second. The dry signal is
        # delayed to line up with the model output (else the mix combs),
        # and kept even with no dry mix so turning it on later stays
        # aligned.
        self._dry_lin = self._dry_lin_target = _dry_lin_for(atten_lim_db)
        self._dry_delay = DelayLine(self.latency_samples)

    @classmethod
    def from_path(cls, onnx_path: str = DEFAULT_DF3_ONNX,
                  states_path: Optional[str] = None,
                  atten_lim_db: float = -60.0) -> "DeepFilterNet3Engine":
        """Load the vendored DF3 model (searching the usual locations)."""
        model_path, states_file = _search_model_files(onnx_path, states_path)
        session = load_session(model_path, "DeepFilterNet3")
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

        dry = self._dry_delay.process(frame)
        start, end = self._dry_lin, self._dry_lin_target
        if start > 0.0 or end > 0.0:
            enhanced = mix_dry(enhanced, dry, start, end)
        self._dry_lin = end
        return enhanced.astype(np.float32, copy=False)

    def set_atten_lim_db(self, atten_lim_db: Optional[float]) -> None:
        self.atten_lim_db = atten_lim_db
        self._dry_lin_target = _dry_lin_for(atten_lim_db)

    def reset(self) -> None:
        self._states = {k: v.copy() for k, v in self._init_states.items()}
        self._dry_delay.reset()
