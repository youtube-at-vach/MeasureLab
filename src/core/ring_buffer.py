import threading
from typing import Optional
import numpy as np


class RingBuffer:
    """
    A thread-safe circular buffer for audio data transfer.

    Supports writing data from one thread (e.g., audio callback) and reading
    from another (e.g., UI thread) with automatic overflow handling.
    """

    def __init__(self, capacity: int, channels: int, dtype=np.float32):
        if capacity <= 0:
            raise ValueError("Capacity must be positive")
        if channels <= 0:
            raise ValueError("Channels must be positive")

        self._capacity = capacity
        self._channels = channels
        self._dtype = dtype

        self._buffer = np.zeros((capacity, channels), dtype=dtype)
        self._write_index = 0
        self._read_index = 0
        self._lock = threading.Lock()

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def channels(self) -> int:
        return self._channels

    @property
    def dtype(self):
        return self._dtype

    def reset(self):
        """Resets the buffer state, clearing all data and indices."""
        with self._lock:
            self._write_index = 0
            self._read_index = 0
            self._buffer.fill(0)

    def write(self, data: np.ndarray):
        """
        Writes data to the buffer.

        Args:
            data: NumPy array of shape (frames, channels) or (frames,).
                  If data is mono (frames, 1) or (frames,) and buffer is stereo,
                  it will be broadcasted to all channels.
                  If data has more channels than the buffer, extra channels are ignored.
        """
        data = np.asarray(data)
        # Ensure 2D for consistent broadcasting
        if data.ndim == 1:
            data = data[:, np.newaxis]

        n_frames, n_channels = data.shape
        if n_frames == 0:
            return

        # Handle channel mismatch (e.g. input 4ch -> buffer 2ch)
        if n_channels > self._channels:
            data = data[:, :self._channels]
        elif 1 < n_channels < self._channels:
            # Handle input with fewer channels (but > 1) -> Pad with zeros
            # Note: input 1ch (mono) is handled by broadcasting in assignment
            padded = np.zeros((n_frames, self._channels), dtype=self._dtype)
            padded[:, :n_channels] = data
            data = padded

        # Handle overflow if writing more than capacity (only keep latest)
        if n_frames > self._capacity:
            data = data[-self._capacity:]
            n_frames = self._capacity

        with self._lock:
            idx = self._write_index % self._capacity
            remaining = self._capacity - idx

            chunk1 = min(n_frames, remaining)
            chunk2 = n_frames - chunk1

            # Write first chunk
            # Numpy broadcasting handles (N, 1) -> (N, C) assignment
            self._buffer[idx : idx + chunk1] = data[:chunk1]

            # Write second chunk (wrap around)
            if chunk2 > 0:
                self._buffer[:chunk2] = data[chunk1:]

            self._write_index += n_frames

    def read(self, num_samples: Optional[int] = None) -> np.ndarray:
        """
        Reads data from the buffer.

        Args:
            num_samples: Number of samples to read. If None, reads all available.

        Returns:
            NumPy array containing the read data.
        """
        with self._lock:
            written = self._write_index
            read = self._read_index

            available = written - read

            if available <= 0:
                return np.empty((0, self._channels), dtype=self._dtype)

            # Handle Overflow: Writer lapped reader
            if available > self._capacity:
                # Skip old data, jump to start of valid window
                read = written - self._capacity
                available = self._capacity

            if num_samples is not None:
                to_read = min(available, num_samples)
            else:
                to_read = available

            if to_read <= 0:
                 return np.empty((0, self._channels), dtype=self._dtype)

            start_idx = read % self._capacity
            chunk1 = min(to_read, self._capacity - start_idx)
            chunk2 = to_read - chunk1

            if chunk2 == 0:
                # Copy is essential to avoid race conditions if we returned a view
                # and writer continued writing.
                data = self._buffer[start_idx : start_idx + chunk1].copy()
            else:
                data = np.concatenate(
                    (self._buffer[start_idx:], self._buffer[:chunk2])
                )

            self._read_index = read + to_read
            return data

    def available(self) -> int:
        """Returns the number of samples available to read."""
        with self._lock:
            count = self._write_index - self._read_index
            return min(count, self._capacity) if count > 0 else 0
