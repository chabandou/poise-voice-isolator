"""
Denoiser Audio Processor

Core audio processing pipeline using ONNX model inference,
with support for VAD, resampling, and streaming state management.
"""
import os
import time
import numpy as np
from typing import Optional, Tuple

import onnxruntime

from .constants import (
    DEFAULT_SAMPLE_RATE,
    DEFAULT_FRAME_SIZE,
    DEFAULT_VAD_THRESHOLD_DB,
    DEFAULT_VAD_HANG_TIME_MS,
    ONNX_STATE_SIZE,
    ONNX_INTRA_OP_THREADS,
    ONNX_INTER_OP_THREADS,
    SOFT_LIMITER_THRESHOLD,
    AUDIO_CLIP_MIN,
    AUDIO_CLIP_MAX,
)
from .vad import VoiceActivityDetector
from .resampler import StreamingResampler
from .logging_config import get_logger

_logger = get_logger(__name__)


class DenoiserAudioProcessor:
    """
    Audio processor for denoiser model.
    Handles direct time-domain processing, ONNX inference, resampling, and VAD.
    """
    
    def __init__(self, onnx_session: onnxruntime.InferenceSession, 
                 target_sr: int = DEFAULT_SAMPLE_RATE, 
                 frame_size: int = DEFAULT_FRAME_SIZE, 
                 enable_vad: bool = True, 
                 vad_threshold_db: float = DEFAULT_VAD_THRESHOLD_DB, 
                 atten_lim_db: float = -60.0):
        """
        Initialize audio processor.
        
        Args:
            onnx_session: ONNX Runtime inference session
            target_sr: Target sample rate for model (default: 48000)
            frame_size: Frame size in samples (default: 480)
            enable_vad: Enable Voice Activity Detection (default: True)
            vad_threshold_db: VAD threshold in dB (default: -40.0)
            atten_lim_db: Attenuation limit in dB (default: -60.0)
        """
        self.onnx_session = onnx_session
        self.target_sr = target_sr
        self.frame_size = frame_size
        self.enable_vad = enable_vad
        self.atten_lim_db = atten_lim_db
        
        # Initialize ONNX model state
        self.states = np.zeros([ONNX_STATE_SIZE], dtype=np.float32)
        
        # Resampler (created on demand)
        self.resampler: Optional[StreamingResampler] = None
        self.output_resampler: Optional[StreamingResampler] = None
        self.output_resample_size: int = frame_size
        
        # VAD
        self.vad = VoiceActivityDetector(
            vad_threshold_db, 
            hang_time_ms=DEFAULT_VAD_HANG_TIME_MS, 
            sample_rate=target_sr
        ) if enable_vad else None
        
        # Statistics
        self.frame_count = 0
        self.total_processing_time = 0.0
        
        if enable_vad:
            _logger.info(f"VAD enabled with threshold: {vad_threshold_db} dB")
    
    def setup_resampler(self, input_sr: int) -> None:
        """
        Setup resampler if input sample rate differs from target.
        
        Args:
            input_sr: Input sample rate
        """
        if input_sr != self.target_sr:
            self.resampler = StreamingResampler(input_sr, self.target_sr, channels=1)
        else:
            self.resampler = None

    def setup_output_resampler(self, output_sr: int) -> None:
        """
        Setup output resampler if output sample rate differs from target.
        
        Args:
            output_sr: Output sample rate
        """
        if output_sr != self.target_sr:
            self.output_resampler = StreamingResampler(self.target_sr, output_sr, channels=1)
            self.output_resample_size = int(self.frame_size * output_sr / self.target_sr)
            _logger.info(f"Output resampling enabled: {self.target_sr}Hz -> {output_sr}Hz (frame size: {self.output_resample_size})")
        else:
            self.output_resampler = None
            self.output_resample_size = self.frame_size
    
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
        
        Args:
            audio_chunk: Input audio samples
            
        Returns:
            Audio chunk with correct frame size
        """
        if len(audio_chunk) != self.frame_size:
            if len(audio_chunk) < self.frame_size:
                audio_chunk = np.pad(audio_chunk, (0, self.frame_size - len(audio_chunk)), mode='constant')
            else:
                audio_chunk = audio_chunk[:self.frame_size]
        return audio_chunk
    
    def _run_onnx_inference(self, audio_chunk: np.ndarray) -> Tuple[np.ndarray, np.ndarray, float]:
        """
        Run ONNX model inference on audio chunk.
        
        Args:
            audio_chunk: Input audio samples (already normalized)
            
        Returns:
            Tuple of (enhanced_audio_frame, new_states, processing_time_ms)
        """
        # Prepare inputs for ONNX model
        input_frame = audio_chunk.astype(np.float32)
        atten_lim_db = np.array(self.atten_lim_db, dtype=np.float32)
        
        # Process through ONNX model
        start_time = time.perf_counter()
        outputs = self.onnx_session.run(
            [],
            {
                'input_frame': input_frame,
                'states': self.states,
                'atten_lim_db': atten_lim_db
            }
        )
        processing_time = (time.perf_counter() - start_time) * 1000
        
        # Extract outputs
        enhanced_audio_frame = outputs[0]  # Dynamic shape
        new_states = outputs[1]  # [ONNX_STATE_SIZE]
        # outputs[2] is lsnr (optional, for monitoring) - not used currently
        
        # Update state for next iteration
        self.states = new_states.copy()
        
        return enhanced_audio_frame, new_states, processing_time
    
    def _normalize_output_shape(self, enhanced_audio_frame: np.ndarray, 
                                fallback_audio: np.ndarray) -> np.ndarray:
        """
        Normalize ONNX output to expected frame size.
        
        Args:
            enhanced_audio_frame: Raw ONNX output
            fallback_audio: Audio to use if output is invalid
            
        Returns:
            Normalized audio output
        """
        # Handle dynamic output shape - ensure we have valid audio
        if len(enhanced_audio_frame.shape) == 0 or enhanced_audio_frame.size == 0:
            # Empty output, return fallback
            return fallback_audio.copy()
        
        # Flatten to 1D if needed
        audio_output = enhanced_audio_frame.flatten().astype(np.float32)
        
        # If output is shorter than expected, pad with zeros
        if len(audio_output) < self.frame_size:
            audio_output = np.pad(audio_output, (0, self.frame_size - len(audio_output)), mode='constant')
        # If output is longer, truncate
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
        
        # VAD check - bypass processing if silence detected
        if self.vad and not self.vad.is_speech(audio_chunk):
            # Pass through unprocessed audio during silence
            return audio_chunk.copy()
        
        # Run ONNX inference
        enhanced_audio_frame, new_states, processing_time = self._run_onnx_inference(audio_chunk)
        
        # Statistics
        self.frame_count += 1
        self.total_processing_time += processing_time
        
        # Normalize output shape
        audio_output = self._normalize_output_shape(enhanced_audio_frame, audio_chunk)
        
        # Post-processing: normalize and clip
        audio_output = self._postprocess_audio(audio_output)
        
        # Output resampling
        if self.output_resampler is not None:
            audio_output = self.output_resampler.process(audio_output, self.output_resample_size)
        
        return audio_output
    
    def _postprocess_audio(self, audio: np.ndarray) -> np.ndarray:
        """Post-process audio: normalize, clip, remove DC offset."""
        if len(audio) == 0:
            return audio
        
        # Soft limiter
        max_val = np.max(np.abs(audio))
        if max_val > SOFT_LIMITER_THRESHOLD and max_val > 0:
            audio = audio * (SOFT_LIMITER_THRESHOLD / max_val)
        
        # Clip to valid range
        audio = np.clip(audio, AUDIO_CLIP_MIN, AUDIO_CLIP_MAX)
        
        # Remove DC offset
        audio = audio - np.mean(audio)
        
        return audio
    
    def get_stats(self) -> dict:
        """Get processing statistics."""
        stats = {
            'frame_count': self.frame_count,
            'avg_time_ms': 0.0,
            'rtf': 0.0
        }
        
        if self.frame_count > 0:
            avg_time = self.total_processing_time / self.frame_count
            # RTF: processing time / frame duration
            frame_duration_ms = (self.frame_size / self.target_sr) * 1000
            rtf = avg_time / frame_duration_ms
            stats['avg_time_ms'] = avg_time
            stats['rtf'] = rtf
        
        # Add VAD stats
        if self.vad:
            vad_stats = self.vad.get_stats()
            stats.update({
                'vad_total': vad_stats['total'],
                'vad_active': vad_stats['active'],
                'vad_bypassed': vad_stats['bypassed'],
                'vad_bypass_ratio': vad_stats['bypass_ratio']
            })
        
        return stats
    
    def reset(self):
        """Reset processor state."""
        self.states = np.zeros([ONNX_STATE_SIZE], dtype=np.float32)
        if self.resampler:
            self.resampler.reset()
        if self.output_resampler:
            self.output_resampler.reset()
        if self.vad:
            self.vad.reset()
        self.frame_count = 0
        self.total_processing_time = 0.0


def load_onnx_model(onnx_path: str = 'denoiser_model.onnx') -> onnxruntime.InferenceSession:
    """
    Load ONNX model for inference with optimized settings.
    Uses CPU execution provider with intra-op parallelism for better performance.
    
    Searches for model in multiple locations:
    1. Provided path (if absolute)
    2. Same directory as the executable/script
    3. Current working directory
    """
    import sys
    
    # If absolute path provided, use it directly
    if os.path.isabs(onnx_path) and os.path.exists(onnx_path):
        model_path = onnx_path
    else:
        # Search in multiple locations
        search_paths = []
        
        # 1. Directory containing the executable (works for Nuitka onefile)
        if hasattr(sys, '_MEIPASS'):
            # PyInstaller
            search_paths.append(os.path.join(sys._MEIPASS, onnx_path))
        
        # Nuitka onefile extracts to a temp dir, __file__ points there
        script_dir = os.path.dirname(os.path.abspath(__file__))
        search_paths.append(os.path.join(script_dir, onnx_path))
        search_paths.append(os.path.join(script_dir, '..', onnx_path))
        
        # 2. Directory containing the main script
        if hasattr(sys, 'argv') and sys.argv[0]:
            main_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
            search_paths.append(os.path.join(main_dir, onnx_path))
        
        # 3. Current working directory
        search_paths.append(os.path.join(os.getcwd(), onnx_path))
        
        # Find the first existing path
        model_path = None
        for path in search_paths:
            _logger.debug(f"Searching for model at: {path}")
            if os.path.exists(path):
                model_path = path
                break
        
        if model_path is None:
            raise FileNotFoundError(
                f"ONNX model not found: {onnx_path}\n"
                f"Searched in:\n" + "\n".join(f"  - {p}" for p in search_paths)
            )
    
    _logger.info(f"Loading ONNX model: {model_path}")
    
    # Configure session options for better performance
    session_options = onnxruntime.SessionOptions()
    
    # Enable optimizations
    session_options.graph_optimization_level = onnxruntime.GraphOptimizationLevel.ORT_ENABLE_ALL
    
    # Set thread count (tune based on your CPU)
    # Use fewer threads to reduce overhead for small models
    session_options.intra_op_num_threads = ONNX_INTRA_OP_THREADS
    session_options.inter_op_num_threads = ONNX_INTER_OP_THREADS
    
    # Enable memory pattern optimization
    session_options.enable_mem_pattern = True
    session_options.enable_cpu_mem_arena = True
    
    # Configure CPU execution provider
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
    
    _logger.info("ONNX model loaded with optimizations")
    _logger.debug(f"  Graph optimization: ALL")
    _logger.debug(f"  Intra-op threads: {session_options.intra_op_num_threads}")
    _logger.debug(f"  Inter-op threads: {session_options.inter_op_num_threads}")
    
    return session
