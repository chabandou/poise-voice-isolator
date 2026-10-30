"""
Streaming Audio Resampler

High-quality streaming resampler using the samplerate library.
"""
import numpy as np
import samplerate
from typing import Optional


class StreamingResampler:
    """
    Streaming audio resampler using samplerate library for better real-time performance.
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
        
        self.resampler = samplerate.Resampler('sinc_fastest', channels=channels)
        self.buffer = []
        print(f"Using samplerate library for {input_sr}Hz -> {output_sr}Hz resampling")
    
    def process(self, data: np.ndarray, output_size: int) -> Optional[np.ndarray]:
        """
        Process audio data through resampler.
        
        Args:
            data: Input audio samples
            output_size: Desired output size
        
        Returns:
            Resampled audio or None if not enough data accumulated
        """
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

    def _enforce_cap(self, output_size: int) -> None:
        """Drop oldest buffered samples if the backlog exceeds the cap.

        Keeps at most `max_buffered_frames * output_size` samples, where
        `output_size` is in output-rate samples. A drifting capture/playback
        clock pair therefore cannot accumulate unbounded latency (the A/V desync).
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
        self.resampler.reset()
        self.buffer = []
        self.dropped_samples = 0
