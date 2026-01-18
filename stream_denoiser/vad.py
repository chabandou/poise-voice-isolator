"""
Voice Activity Detection (VAD)

Simple energy-based VAD for skipping processing during silence,
providing 2-3x performance boost.
"""
import numpy as np

from .constants import DEFAULT_FRAME_SIZE


class VoiceActivityDetector:
    """
    Simple energy-based Voice Activity Detection (VAD).
    Skips processing during silence for 2-3x performance boost.
    """
    
    def __init__(self, threshold_db: float = -40.0, hang_time_ms: float = 300.0, 
                 sample_rate: int = 48000):
        """
        Initialize VAD.
        
        Args:
            threshold_db: Energy threshold in dB (lower = more sensitive)
            hang_time_ms: How long to keep processing after speech ends (smoothing)
            sample_rate: Audio sample rate
        """
        self.threshold_db = threshold_db
        self.threshold_linear = 10 ** (threshold_db / 20)
        # Calculate hang frames based on frame size
        self.hang_frames = int(hang_time_ms * sample_rate / 1000 / DEFAULT_FRAME_SIZE)
        self.frames_since_active = self.hang_frames + 1
        
        # Statistics
        self.total_frames = 0
        self.active_frames = 0
        self.bypassed_frames = 0
    
    def set_threshold(self, threshold_db: float) -> None:
        """Update the VAD threshold at runtime."""
        self.threshold_db = threshold_db
        self.threshold_linear = 10 ** (threshold_db / 20)
    
    def is_speech(self, audio: np.ndarray) -> bool:
        """
        Determine if audio contains speech.
        
        Args:
            audio: Audio samples
        
        Returns:
            True if speech detected, False if silence
        """
        self.total_frames += 1
        
        # Calculate RMS energy
        rms = np.sqrt(np.mean(audio ** 2))
        
        # Check if above threshold
        is_active = rms > self.threshold_linear
        
        if is_active:
            self.frames_since_active = 0
            self.active_frames += 1
            return True
        else:
            self.frames_since_active += 1
            # Use hang time to smooth transitions
            if self.frames_since_active < self.hang_frames:
                self.active_frames += 1
                return True
            else:
                self.bypassed_frames += 1
                return False
    
    def get_stats(self) -> dict:
        """Get VAD statistics."""
        if self.total_frames == 0:
            return {'total': 0, 'active': 0, 'bypassed': 0, 'bypass_ratio': 0.0}
        
        return {
            'total': self.total_frames,
            'active': self.active_frames,
            'bypassed': self.bypassed_frames,
            'bypass_ratio': self.bypassed_frames / self.total_frames
        }
    
    def reset(self):
        """Reset VAD state."""
        self.frames_since_active = self.hang_frames + 1
        self.total_frames = 0
        self.active_frames = 0
        self.bypassed_frames = 0
