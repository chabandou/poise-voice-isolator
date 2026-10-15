"""
GTCRN Engine

Runs GTCRN (Rong et al., ICASSP 2024), an ultra-lightweight speech
enhancement model, through ONNX Runtime: the official streaming export
(`gtcrn.onnx` from github.com/Xiaobin-Rong/gtcrn, MIT licensed; the
model Poise for Android ships), rewritten by tools/optimize_gtcrn.py
into an equivalent graph with the same inputs and outputs that runs
about 2.4x faster (same output to within float rounding).

GTCRN works at 16 kHz on one STFT frame at a time (512-point FFT,
256-sample hop, sqrt-Hann window) and carries its streaming state in
three cache tensors. The rest of Poise runs at 48 kHz, so each
768-sample frame (16 ms, one hop) is low-passed and decimated by 3,
enhanced, and interpolated back up with the same linear-phase FIR.
The output is band-limited to ~7.6 kHz: the model only sees, and
returns, the 16 kHz band.
"""
from typing import Optional

import numpy as np

from .base import DelayLine, DenoiseEngine, dry_mix_fraction, mix_dry
from .onnx_model import find_model_file, load_session
from ..constants import DEFAULT_SAMPLE_RATE, MODEL_GTCRN

GTCRN_ONNX = 'gtcrn.onnx'

#: The model's sample rate and STFT (as in the upstream stream export).
MODEL_SAMPLE_RATE = 16000
N_FFT = 512
HOP = 256

#: 48 kHz -> 16 kHz.
DECIMATION = DEFAULT_SAMPLE_RATE // MODEL_SAMPLE_RATE
#: Engine frame at 48 kHz: one STFT hop.
FRAME = HOP * DECIMATION

# Resampling low-pass (Kaiser-windowed sinc at 48 kHz): -0.4 dB at 7 kHz,
# below -58 dB from 8.5 kHz, so little aliases into the band the model
# hears and the interpolation images stay out of the output. Odd length:
# a whole-sample delay of (taps - 1) / 2 on each side.
FIR_TAPS = 97
FIR_CUTOFF_HZ = 7600.0
FIR_STOPBAND_DB = 60.0


def lowpass_fir(taps: int = FIR_TAPS, cutoff_hz: float = FIR_CUTOFF_HZ,
                sample_rate: int = DEFAULT_SAMPLE_RATE,
                stopband_db: float = FIR_STOPBAND_DB) -> np.ndarray:
    """Linear-phase low-pass FIR (Kaiser window), unity gain at DC."""
    if stopband_db > 50.0:
        beta = 0.1102 * (stopband_db - 8.7)
    elif stopband_db >= 21.0:
        beta = (0.5842 * (stopband_db - 21.0) ** 0.4
                + 0.07886 * (stopband_db - 21.0))
    else:
        beta = 0.0
    fc = cutoff_hz / sample_rate
    n = np.arange(taps) - (taps - 1) / 2.0
    h = 2.0 * fc * np.sinc(2.0 * fc * n) * np.kaiser(taps, beta)
    return (h / h.sum()).astype(np.float32)


class _FirResampler:
    """
    Streaming integer-factor FIR resampler (one direction).

    Down: low-pass, then keep every `factor`-th sample (the last of each
    group, so a frame needs no input beyond itself). Up: place each
    sample at the same position of its group (zeros between, times
    `factor` for unity gain), then low-pass. With both sides on the same
    phase the round trip delays by exactly taps - 1 samples (48 kHz).
    """

    def __init__(self, h: np.ndarray, factor: int, up: bool):
        self._h = h
        self._factor = factor
        self._up = up
        self._hist = np.zeros(len(h) - 1, dtype=np.float32)

    def process(self, x: np.ndarray) -> np.ndarray:
        f = self._factor
        if self._up:
            stuffed = np.zeros(len(x) * f, dtype=np.float32)
            stuffed[f - 1::f] = x * f
            x = stuffed
        buf = np.concatenate((self._hist, x))
        self._hist = buf[len(buf) - len(self._hist):]
        y = np.convolve(buf, self._h, mode='valid')
        return y if self._up else y[f - 1::f]

    def reset(self) -> None:
        self._hist[:] = 0.0


def _sqrt_hann(n: int) -> np.ndarray:
    """sqrt of the periodic Hann window (torch.hann_window(n).sqrt())."""
    return np.sqrt(0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(n) / n)
                   ).astype(np.float32)


class GTCRNEngine(DenoiseEngine):
    """GTCRN streaming ONNX model, run at 16 kHz inside 48 kHz frames."""

    name = MODEL_GTCRN
    required_frame_size = FRAME
    # STFT overlap-add (one hop) + the two resampling filters. Measured
    # on speech by cross-correlation: 864 samples (18 ms).
    latency_samples = FRAME + (FIR_TAPS - 1)

    def __init__(self, onnx_session, atten_lim_db: float = -60.0):
        """
        Args:
            onnx_session: ONNX Runtime inference session for gtcrn.onnx
            atten_lim_db: Attenuation limit in dB (repo convention,
                negative, e.g. -60.0): a fraction of the dry input is
                mixed back in, as for RNNoise.
        """
        self.onnx_session = onnx_session
        inputs = onnx_session.get_inputs()
        self._mix_name = inputs[0].name
        self.output_names = [o.name for o in onnx_session.get_outputs()]
        # Cache inputs in model order; outputs[1:] are their new values
        # ("<input_name>_out"), in the same order.
        self._cache_names = [i.name for i in inputs[1:]]
        self._cache_shapes = [tuple(int(d) for d in i.shape)
                              for i in inputs[1:]]
        self.atten_lim_db = atten_lim_db

        h = lowpass_fir()
        self._down = _FirResampler(h, DECIMATION, up=False)
        self._up = _FirResampler(h, DECIMATION, up=True)
        self._window = _sqrt_hann(N_FFT)
        self._mix = np.zeros((1, N_FFT // 2 + 1, 1, 2), dtype=np.float32)
        self._analysis = np.zeros(N_FFT, dtype=np.float32)
        self._overlap = np.zeros(N_FFT, dtype=np.float32)
        self._caches = {}
        self._reset_caches()

        # Applied mix and the one set_atten_lim_db() asks for; the next
        # frame ramps from the first to the second. The dry signal is
        # delayed to line up with the model output (else the mix combs).
        self._dry_mix = self._dry_mix_target = dry_mix_fraction(atten_lim_db)
        self._dry_delay = DelayLine(self.latency_samples)

    @classmethod
    def from_path(cls, onnx_path: str = GTCRN_ONNX,
                  atten_lim_db: float = -60.0) -> "GTCRNEngine":
        """Load the vendored GTCRN model (searching the usual locations)."""
        session = load_session(find_model_file(onnx_path, "GTCRN"), "GTCRN")
        return cls(session, atten_lim_db=atten_lim_db)

    @classmethod
    def is_available(cls) -> bool:
        """True if the vendored GTCRN model file can be found."""
        try:
            find_model_file(GTCRN_ONNX, "GTCRN")
            return True
        except FileNotFoundError:
            return False

    def _reset_caches(self) -> None:
        self._caches = {name: np.zeros(shape, dtype=np.float32)
                        for name, shape in zip(self._cache_names,
                                               self._cache_shapes)}

    def _enhance_hop(self, x16: np.ndarray) -> np.ndarray:
        """One 16 kHz hop through STFT -> GTCRN -> iSTFT (overlap-add)."""
        a = self._analysis
        a[:HOP] = a[HOP:]
        a[HOP:] = x16
        spec = np.fft.rfft(a * self._window)
        self._mix[0, :, 0, 0] = spec.real
        self._mix[0, :, 0, 1] = spec.imag

        feeds = {self._mix_name: self._mix}
        feeds.update(self._caches)
        res = self.onnx_session.run(self.output_names, feeds)
        # Assign directly: ORT returns fresh arrays.
        for name, val in zip(self._cache_names, res[1:]):
            self._caches[name] = val

        enh = res[0]
        frame = np.fft.irfft(enh[0, :, 0, 0] + 1j * enh[0, :, 0, 1], N_FFT)
        o = self._overlap
        o += frame.astype(np.float32) * self._window
        out = o[:HOP].copy()
        o[:HOP] = o[HOP:]
        o[HOP:] = 0.0
        return out

    def process_frame(self, frame: np.ndarray) -> np.ndarray:
        if frame.shape[0] != FRAME:
            raise ValueError(
                f"GTCRN requires {FRAME}-sample frames, got {frame.shape[0]}")
        frame = np.asarray(frame, dtype=np.float32)
        wet = self._up.process(self._enhance_hop(self._down.process(frame)))

        dry = self._dry_delay.process(frame)
        start, end = self._dry_mix, self._dry_mix_target
        if start > 0.0 or end > 0.0:
            wet = mix_dry(wet, dry, start, end)
        self._dry_mix = end
        return wet.astype(np.float32, copy=False)

    def set_atten_lim_db(self, atten_lim_db: Optional[float]) -> None:
        self.atten_lim_db = atten_lim_db
        self._dry_mix_target = dry_mix_fraction(atten_lim_db)

    def reset(self) -> None:
        self._reset_caches()
        self._down.reset()
        self._up.reset()
        self._analysis[:] = 0.0
        self._overlap[:] = 0.0
        self._dry_delay.reset()
