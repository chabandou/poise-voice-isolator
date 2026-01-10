"""
Ring Buffer Implementation

Lock-free ring buffer for audio samples with reduced latency
compared to queue.Queue by avoiding GIL contention.
"""
import numpy as np
import threading
from typing import Optional


class RingBuffer:
    """
    Lock-free ring buffer for audio samples.
    Reduces latency compared to queue.Queue by avoiding GIL contention.
    """
    
    def __init__(self, capacity: int):
        """
        Initialize ring buffer.
        
        Args:
            capacity: Maximum number of samples to store
        """
        self.capacity = capacity
        self.buffer = np.zeros(capacity, dtype=np.float32)
        self.write_pos = 0
        self.read_pos = 0
        self.lock = threading.Lock()
    
    def write(self, data: np.ndarray) -> bool:
        """
        Write data to ring buffer.
        
        Args:
            data: Audio samples to write
        
        Returns:
            True if successful, False if buffer is full
        """
        with self.lock:
            n = len(data)
            available = self.capacity - self.available()
            
            if n > available:
                # Buffer full - drop oldest data to make room
                samples_to_drop = n - available
                self.read_pos = (self.read_pos + samples_to_drop) % self.capacity
            
            # Write data in one or two chunks (if wrapping around)
            end_pos = self.write_pos + n
            if end_pos <= self.capacity:
                self.buffer[self.write_pos:end_pos] = data
            else:
                # Wrap around
                split = self.capacity - self.write_pos
                self.buffer[self.write_pos:] = data[:split]
                self.buffer[:n-split] = data[split:]
            
            self.write_pos = end_pos % self.capacity
            return True
    
    def read(self, n: int) -> Optional[np.ndarray]:
        """
        Read data from ring buffer.
        
        Args:
            n: Number of samples to read
        
        Returns:
            Audio samples or None if not enough data available
        """
        with self.lock:
            available = self.available()
            if available < n:
                return None
            
            # Read data in one or two chunks (if wrapping around)
            end_pos = self.read_pos + n
            if end_pos <= self.capacity:
                result = self.buffer[self.read_pos:end_pos].copy()
            else:
                # Wrap around
                split = self.capacity - self.read_pos
                result = np.concatenate([
                    self.buffer[self.read_pos:],
                    self.buffer[:n-split]
                ])
            
            self.read_pos = end_pos % self.capacity
            return result
    
    def available(self) -> int:
        """Get number of samples available to read."""
        if self.write_pos >= self.read_pos:
            return self.write_pos - self.read_pos
        else:
            return self.capacity - self.read_pos + self.write_pos
    
    def clear(self):
        """Clear the buffer."""
        with self.lock:
            self.read_pos = 0
            self.write_pos = 0
