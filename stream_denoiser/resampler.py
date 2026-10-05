"""
Streaming Audio Resampler

High-quality streaming resampler using samplerate library,
with scipy fallback for compatibility.
"""
import numpy as np
from typing import Optional

try:
    import samplerate
    USE_SAMPLERATE = True
except ImportError:
    from scipy import signal
    USE_SAMPLERATE = False


class StreamingResampler:
    """
    Streaming audio resampler using samplerate library for better real-time performance.
    Falls back to scipy if samplerate is not available.
    """
    
    def __init__(self, input_sr: int, output_sr: int, channels: int = 1,
                 max_buffered_frames: int = 4):
        """
        Initialize streaming resampler.
        
        Args:
            input_sr: Input sample rate
            output_sr: Output sample rate
            channels: Number of audio channels
            max_buffered_frames: Safety cap for internally buffered output
                frames (in units of `output_size` passed to process()).
                If clock drift between capture and playback devices lets the
                buffer grow past this, the oldest samples are dropped (with
                `dropped_samples` counting them) so latency stays bounded
                instead of growing into a visible A/V desync over minutes.
        """
        if input_sr <= 0 or output_sr <= 0:
            raise ValueError(f"Invalid sample rates: input_sr={input_sr}, output_sr={output_sr}")
        
        self.input_sr = input_sr
        self.output_sr = output_sr
        self.channels = channels
        self.ratio = output_sr / input_sr
        self.max_buffered_frames = max(1, max_buffered_frames)
        self.dropped_samples = 0
        
        if USE_SAMPLERATE:
            # Use high-quality streaming resampler
            self.resampler = samplerate.Resampler('sinc_fastest', channels=channels)
            self.buffer = []
            print(f"Using samplerate library for {input_sr}Hz -> {output_sr}Hz resampling")
        else:
            # Fallback to scipy with buffering
            self.buffer = []
            print(f"Using scipy.signal.resample for {input_sr}Hz -> {output_sr}Hz resampling (slower)")
    
    def process(self, data: np.ndarray, output_size: int) -> Optional[np.ndarray]:
        """
        Process audio data through resampler.
        
        Args:
            data: Input audio samples
            output_size: Desired output size
        
        Returns:
            Resampled audio or None if not enough data accumulated
        """
        if USE_SAMPLERATE:
            # samplerate handles streaming internally
            resampled = self.resampler.process(data, self.ratio, end_of_input=False)
            
            # Accumulate in buffer
            self.buffer.extend(resampled)
            self._enforce_cap(output_size)
            
            # Return output_size samples if available
            if len(self.buffer) >= output_size:
                output = np.array(self.buffer[:output_size], dtype=np.float32)
                self.buffer = self.buffer[output_size:]
                return output
            return None
        else:
            # Scipy fallback - accumulate and resample (buffer holds
            # input-rate samples, so the cap is expressed in input samples).
            self.buffer.extend(data)
            self._enforce_cap(int(output_size * self.input_sr / self.output_sr))
            
            # Calculate how many output samples we can produce
            num_output_samples = int(len(self.buffer) * self.output_sr / self.input_sr)
            
            if num_output_samples >= output_size:
                # Resample the buffer
                resampled = signal.resample(self.buffer, num_output_samples)
                
                # Take exactly output_size samples
                output = resampled[:output_size].astype(np.float32)
                
                # Calculate how many input samples were used
                samples_used = int(output_size * self.input_sr / self.output_sr)
                
                # Keep remainder in buffer
                self.buffer = self.buffer[samples_used:]
                
                return output
            return None
    
    def _enforce_cap(self, output_size: int) -> None:
        """Drop oldest buffered samples if the backlog exceeds the cap.

        Keeps at most `max_buffered_frames * output_size` samples, where
        `output_size` is expressed in the buffer's native domain
        (output-rate samples for the samplerate path, input-rate samples
        for the scipy fallback). A drifting capture/playback clock pair
        therefore cannot accumulate unbounded latency (the A/V desync).
        Dropped samples are counted in `dropped_samples` for diagnostics.
        """
        limit = self.max_buffered_frames * max(1, int(output_size))
        if len(self.buffer) > limit:
            dropped = len(self.buffer) - limit
            self.buffer = self.buffer[dropped:]
            self.dropped_samples += dropped

    def buffered_samples(self) -> int:
        """Number of samples currently held in the internal buffer."""
        return len(self.buffer)

    def reset(self):
        """Reset the resampler state."""
        if USE_SAMPLERATE:
            self.resampler.reset()
        self.buffer = []
        self.dropped_samples = 0
