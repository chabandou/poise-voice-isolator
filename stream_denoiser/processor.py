"""
Denoiser Audio Processor

Core audio processing pipeline: a pluggable denoising engine (DeepFilterNet3
via ONNX Runtime, or RNNoise) plus AAD, resampling, and streaming state
management.
"""
import time
import numpy as np
from typing import Optional, Tuple

from .constants import (
    DEFAULT_SAMPLE_RATE,
    DEFAULT_FRAME_SIZE,
    DEFAULT_AAD_THRESHOLD_DB,
    DEFAULT_AAD_HANG_TIME_MS,
    SOFT_LIMITER_THRESHOLD,
    AUDIO_CLIP_MIN,
    AUDIO_CLIP_MAX,
    OUTPUT_GAIN_DB,
)
from .engines import DenoiseEngine
from .aad import AudioActivityDetector
from .resampler import StreamingResampler
from .logging_config import get_logger

_logger = get_logger(__name__)


class DenoiserAudioProcessor:
    """
    Audio processor for denoiser models.
    Handles direct time-domain processing, engine inference, resampling, and AAD.
    """
    
    def __init__(self, engine,
                 target_sr: int = DEFAULT_SAMPLE_RATE, 
                 frame_size: int = DEFAULT_FRAME_SIZE, 
                 enable_aad: bool = True, 
                 aad_threshold_db: float = DEFAULT_AAD_THRESHOLD_DB, 
                 atten_lim_db: float = -60.0):
        """
        Initialize audio processor.
        
        Args:
            engine: A DenoiseEngine (created via create_engine())
            target_sr: Target sample rate for model (default: 48000)
            frame_size: Frame size in samples (default: 480; engines with a
                fixed frame size, e.g. deepfilternet3=512, override this)
            enable_aad: Enable Audio Activity detection (default: True)
            aad_threshold_db: AAD threshold in dB (default: -40.0)
            atten_lim_db: Attenuation limit in dB. informational only —
                engines created via create_engine() carry their own.
        """
        if not isinstance(engine, DenoiseEngine):
            raise TypeError(
                f"engine must be a DenoiseEngine (got {type(engine).__name__}); "
                "create one via stream_denoiser.engines.create_engine()"
            )
        
        required = engine.required_frame_size
        if required is not None and required != frame_size:
            raise ValueError(
                f"Engine '{engine.name}' requires {required}-sample frames, "
                f"but frame_size={frame_size}"
            )
        
        self.engine = engine
        self.target_sr = target_sr
        self.frame_size = frame_size
        self.enable_aad = enable_aad
        self.atten_lim_db = atten_lim_db
        # Fixed makeup gain (linear) applied to every output frame before
        # the soft limiter. Not user-configurable by design.
        self.output_gain_db = OUTPUT_GAIN_DB
        self.output_gain = float(10.0 ** (OUTPUT_GAIN_DB / 20.0))
        
        # Resampler (created on demand)
        self.resampler: Optional[StreamingResampler] = None
        self.output_resampler: Optional[StreamingResampler] = None
        self.output_resample_size: int = frame_size
        # Exact (fractional) output take size, e.g. 470.4 for a 512-sample
        # frame at a 44100Hz output device. next_output_block_size()
        # dithers around output_resample_size so takes average exact;
        # a fixed take would let the output backlog grow ~0.4 samples/frame
        # until the safety cap starts dropping (periodic output gaps).
        self._output_block_exact: float = float(frame_size)
        self._output_block_err: float = 0.0
        # Number of input-device samples to read per loop iteration so that,
        # after input resampling, each read yields ~one engine frame on
        # average. Reading a fixed `frame_size` regardless of the input rate
        # over/under-feeds the resampler and its backlog grows unbounded
        # (minutes-long A/V desync). Equals frame_size when no resampling.
        self.input_sr: int = target_sr
        self.input_block_size: int = frame_size
        # Exact (fractional) rate-scaled read size, e.g. 470.4 for a
        # 512-sample frame at 44100Hz. next_input_block_size() dithers
        # around input_block_size so the long-term average is exact.
        self._input_block_exact: float = float(frame_size)
        self._input_block_err: float = 0.0
        self.output_sr: int = target_sr
        
        # AAD
        self.aad = AudioActivityDetector(
            aad_threshold_db, 
            hang_time_ms=DEFAULT_AAD_HANG_TIME_MS, 
            sample_rate=target_sr,
            frame_size=frame_size
        ) if enable_aad else None
        
        # Statistics
        self.frame_count = 0
        self.total_processing_time = 0.0

        # Reusable scratch buffer for post-processing (avoids per-frame allocs)
        self._abs_scratch = np.zeros(frame_size, dtype=np.float32)
        
        _logger.info(f"Denoise engine: {engine.name}")
        if enable_aad:
            _logger.info(f"AAD enabled with threshold: {aad_threshold_db} dB")
    
    def setup_resampler(self, input_sr: int) -> None:
        """
        Setup resampler if input sample rate differs from target.
        
        Args:
            input_sr: Input sample rate
        """
        self.input_sr = int(input_sr)
        if input_sr != self.target_sr:
            self.resampler = StreamingResampler(input_sr, self.target_sr, channels=1)
            # Scale the read size so each input block resamples to ~one
            # engine frame; otherwise the resampler backlog grows linearly.
            self._input_block_exact = self.frame_size * input_sr / self.target_sr
            self.input_block_size = max(
                1, int(round(self._input_block_exact)))
            self._input_block_err = 0.0
        else:
            self.resampler = None
            self.input_block_size = self.frame_size
            self._input_block_exact = float(self.frame_size)
            self._input_block_err = 0.0

    def next_input_block_size(self) -> int:
        """
        Per-iteration input read size (in input-device samples).

        Dithers around `input_block_size` so the long-term average equals
        the exact fractional rate-scaled size. A fixed rounded size would
        systematically over/under-feed the resampler by the rounding error
        (e.g. 470 vs 470.4 starves one frame every ~100 reads -> a periodic
        ~10ms output gap), which again shows up as A/V sync wobble.
        """
        if self.resampler is None:
            return self.frame_size
        self._input_block_err += self._input_block_exact - self.input_block_size
        n = self.input_block_size
        if self._input_block_err >= 1.0:
            n += 1
            self._input_block_err -= 1.0
        elif self._input_block_err <= -1.0:
            n -= 1
            self._input_block_err += 1.0
        return max(1, n)

    def setup_output_resampler(self, output_sr: int) -> None:
        """
        Setup output resampler if output sample rate differs from target.
        
        Args:
            output_sr: Output sample rate
        """
        self.output_sr = int(output_sr)
        if output_sr != self.target_sr:
            self.output_resampler = StreamingResampler(self.target_sr, output_sr, channels=1)
            self._output_block_exact = self.frame_size * output_sr / self.target_sr
            self.output_resample_size = max(
                1, int(round(self._output_block_exact)))
            self._output_block_err = 0.0
            _logger.info(f"Output resampling enabled: {self.target_sr}Hz -> {output_sr}Hz (frame size: {self.output_resample_size})")
        else:
            self.output_resampler = None
            self.output_resample_size = self.frame_size
            self._output_block_exact = float(self.frame_size)
            self._output_block_err = 0.0

    def next_output_block_size(self) -> int:
        """
        Per-iteration output take size (in output-device samples).

        Dithers around `output_resample_size` so the long-term average
        equals the exact fractional size (mirror of next_input_block_size).
        """
        if self.output_resampler is None:
            return self.frame_size
        self._output_block_err += self._output_block_exact - self.output_resample_size
        n = self.output_resample_size
        if self._output_block_err >= 1.0:
            n += 1
            self._output_block_err -= 1.0
        elif self._output_block_err <= -1.0:
            n -= 1
            self._output_block_err += 1.0
        return max(1, n)
    
    def _resample_audio(self, audio_chunk: np.ndarray) -> Optional[np.ndarray]:
        """
        Resample audio if resampler is configured.
        
        Args:
            audio_chunk: Input audio samples
            
        Returns:
            Resampled audio or None if not enough data accumulated
        """
        if self.resampler is not None:
            audio_chunk = self.resampler.process(audio_chunk, self.frame_size)
            if audio_chunk is None:
                return None  # Not enough samples yet
        return audio_chunk
    
    def _normalize_frame_size(self, audio_chunk: np.ndarray) -> np.ndarray:
        """
        Ensure audio chunk matches expected frame size (pad or truncate).

        Zero-copy fast path: chunks that already match are returned as-is
        (only a dtype conversion copies).

        Args:
            audio_chunk: Input audio samples

        Returns:
            Audio chunk with correct frame size
        """
        if audio_chunk.dtype != np.float32:
            audio_chunk = audio_chunk.astype(np.float32)
        if len(audio_chunk) != self.frame_size:
            if len(audio_chunk) < self.frame_size:
                audio_chunk = np.pad(audio_chunk, (0, self.frame_size - len(audio_chunk)), mode='constant')
            else:
                audio_chunk = audio_chunk[:self.frame_size]
        return audio_chunk
    
    def _run_engine(self, audio_chunk: np.ndarray) -> Tuple[np.ndarray, float]:
        """
        Run the denoising engine on an audio chunk.
        
        Args:
            audio_chunk: Input audio samples (already normalized)
            
        Returns:
            Tuple of (enhanced_audio_frame, processing_time_ms)
        """
        start_time = time.perf_counter()
        enhanced_audio_frame = self.engine.process_frame(audio_chunk)
        processing_time = (time.perf_counter() - start_time) * 1000
        return enhanced_audio_frame, processing_time
    
    def _normalize_output_shape(self, enhanced_audio_frame: np.ndarray, 
                                fallback_audio: np.ndarray) -> np.ndarray:
        """
        Normalize engine output to expected frame size.

        Zero-copy fast path: engines already return float32 frames of the
        correct shape, which are passed through untouched.

        Args:
            enhanced_audio_frame: Raw engine output
            fallback_audio: Audio to use if output is invalid
            
        Returns:
            Normalized audio output
        """
        # Fast path: already the right shape and dtype (both bundled engines)
        if (enhanced_audio_frame.dtype == np.float32
                and enhanced_audio_frame.shape == (self.frame_size,)):
            return enhanced_audio_frame
        # Handle dynamic output shape - ensure we have valid audio
        if len(enhanced_audio_frame.shape) == 0 or enhanced_audio_frame.size == 0:
            # Empty output, return fallback
            return fallback_audio.copy()
        
        # Flatten to 1D if needed (copies only when necessary)
        if enhanced_audio_frame.dtype != np.float32:
            audio_output = enhanced_audio_frame.flatten().astype(np.float32)
        elif enhanced_audio_frame.ndim != 1:
            audio_output = enhanced_audio_frame.flatten().copy()
        else:
            audio_output = enhanced_audio_frame
        
        # If output is shorter than expected, pad with zeros
        if len(audio_output) < self.frame_size:
            audio_output = np.pad(audio_output, (0, self.frame_size - len(audio_output)), mode='constant')
        # If output is longer, truncate (view, no copy)
        elif len(audio_output) > self.frame_size:
            audio_output = audio_output[:self.frame_size]
        
        return audio_output
    
    def process_chunk(self, audio_chunk: np.ndarray) -> Optional[np.ndarray]:
        """
        Process a single audio chunk through the pipeline.
        
        Args:
            audio_chunk: Input audio samples
        
        Returns:
            Enhanced audio samples or None if not enough data accumulated
        """
        # Resample if needed
        audio_chunk = self._resample_audio(audio_chunk)
        if audio_chunk is None:
            return None  # Not enough samples yet
        
        # Ensure correct size
        audio_chunk = self._normalize_frame_size(audio_chunk)
        
        # AAD check - bypass processing if silence detected
        if self.aad and not self.aad.is_audio(audio_chunk):
            # Bypassed frames get the same makeup gain + limiter chain as
            # processed frames so loudness stays consistent and the boosted
            # signal still can't clip. Still runs through the output
            # resampler so bypassed frames keep the same length/timing as
            # processed frames.
            return self._resample_output(self._postprocess_audio(audio_chunk))
        
        # Run the denoising engine
        enhanced_audio_frame, processing_time = self._run_engine(audio_chunk)
        
        # Statistics
        self.frame_count += 1
        self.total_processing_time += processing_time
        
        # Normalize output shape
        audio_output = self._normalize_output_shape(enhanced_audio_frame, audio_chunk)
        
        # Post-processing: normalize and clip
        audio_output = self._postprocess_audio(audio_output)
        
        # Output resampling
        return self._resample_output(audio_output)

    def _resample_output(self, audio: np.ndarray) -> Optional[np.ndarray]:
        """Resample engine-rate audio to the output device rate, if needed."""
        if self.output_resampler is not None:
            return self.output_resampler.process(audio, self.next_output_block_size())
        return audio
    
    def _postprocess_audio(self, audio: np.ndarray) -> np.ndarray:
        """Post-process audio: makeup gain, soft-limit, clip, remove DC offset."""
        if len(audio) == 0:
            return audio

        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        # Makeup gain first (new array, never mutates engine buffers);
        # the soft limiter + clip below guarantee no clipping.
        if self.output_gain != 1.0:
            audio = audio * self.output_gain

        # Soft limiter into a reusable scratch buffer (no per-frame alloc).
        # Falls back to a one-off abs() if a resampled size differs.
        if len(self._abs_scratch) == len(audio):
            np.abs(audio, out=self._abs_scratch)
            max_val = float(self._abs_scratch.max())
        else:
            max_val = float(np.max(np.abs(audio)))
        if max_val > SOFT_LIMITER_THRESHOLD:
            audio *= (SOFT_LIMITER_THRESHOLD / max_val)

        # Remove DC offset first, in place: recentering after the clip
        # could push peaks back outside [-1, 1].
        audio -= float(np.mean(audio))

        # Final clip to valid range, in place — output never exceeds [-1, 1].
        np.clip(audio, AUDIO_CLIP_MIN, AUDIO_CLIP_MAX, out=audio)

        return audio
    
    def get_stats(self) -> dict:
        """Get processing statistics."""
        stats = {
            'model': self.engine.name,
            'frame_size': self.frame_size,
            'target_sr': self.target_sr,
            'frame_count': self.frame_count,
            'avg_time_ms': 0.0,
            'rtf': 0.0
        }
        
        if self.engine.speech_prob is not None:
            stats['speech_prob'] = self.engine.speech_prob
        
        if self.frame_count > 0:
            avg_time = self.total_processing_time / self.frame_count
            # RTF: processing time / frame duration
            frame_duration_ms = (self.frame_size / self.target_sr) * 1000
            rtf = avg_time / frame_duration_ms
            stats['avg_time_ms'] = avg_time
            stats['rtf'] = rtf
        
        # Add AAD stats
        if self.aad:
            aad_stats = self.aad.get_stats()
            stats.update({
                'aad_total': aad_stats['total'],
                'aad_active': aad_stats['active'],
                'aad_bypassed': aad_stats['bypassed'],
                'aad_bypass_ratio': aad_stats['bypass_ratio'],
                'aad_bypass_active': self.aad.bypass_active,
            })

        return stats

    def get_diagnostics(self) -> dict:
        """
        Extra counters for file-log diagnosis (does not affect UI numbers).

        Distinguishes "RTF=0 because AAD bypassed everything (silence)"
        from "RTF=0 because no frames reached the engine (resampler
        starvation / empty reads)".
        """
        diag = self.get_stats()
        diag['resampler_active'] = self.resampler is not None
        diag['output_resampler_active'] = self.output_resampler is not None
        diag['input_sr'] = self.input_sr
        diag['input_block_size'] = self.input_block_size
        diag['output_sr'] = self.output_sr
        diag['output_resample_size'] = self.output_resample_size
        diag['resampler_backlog'] = (
            self.resampler.buffered_samples() if self.resampler else 0
        )
        diag['resampler_dropped'] = (
            self.resampler.dropped_samples if self.resampler else 0
        )
        diag['output_resampler_backlog'] = (
            self.output_resampler.buffered_samples() if self.output_resampler else 0
        )
        diag['output_resampler_dropped'] = (
            self.output_resampler.dropped_samples if self.output_resampler else 0
        )
        diag['aad_threshold_db'] = self.aad.threshold_db if self.aad else None
        return diag
    
    def reset(self):
        """Reset processor state."""
        self.engine.reset()
        if self.resampler:
            self.resampler.reset()
        if self.output_resampler:
            self.output_resampler.reset()
        if self.aad:
            self.aad.reset()
        self.frame_count = 0
        self.total_processing_time = 0.0
        self._input_block_err = 0.0
        self._output_block_err = 0.0
    
    def close(self):
        """Release engine resources."""
        self.engine.close()
