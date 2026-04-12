import sys
import os
import time
from unittest.mock import MagicMock
import numpy as np

# Mock sounddevice before importing anything else that might import it
sys.modules["sounddevice"] = MagicMock()

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.gui.widgets.spectrogram import Spectrogram  # noqa: E402


class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 44100

    def register_callback(self, cb):
        return 1

    def unregister_callback(self, id):
        pass


def benchmark_get_latest_samples():
    engine = MockAudioEngine()
    spec = Spectrogram(engine)

    # Setup
    fft_size = 8192  # Use a reasonably large size to make memory alloc noticeable
    spec.set_fft_size(fft_size)

    # Verify buffer size
    # reset_buffers sets audio_buffer to (fft_size * 2, 2)
    # audio_buffer len is 16384

    # We want to force wrap-around.
    # get_latest_samples(n) does start_pos = pos - n
    # if start_pos < 0 -> wrap around.
    # So if we set pos = 100, and request 8192, start_pos = 100 - 8192 = -8092 -> Wrap.

    spec.audio_buffer_pos = 100
    n_samples = fft_size

    # Fill buffer with some data so we aren't just copying zeros (though performance is same)
    spec.audio_buffer[:] = np.random.rand(*spec.audio_buffer.shape)

    iterations = 100000

    # Warmup
    for _ in range(100):
        _ = spec.get_latest_samples(n_samples)

    start_time = time.perf_counter()
    for _ in range(iterations):
        _ = spec.get_latest_samples(n_samples)
    end_time = time.perf_counter()

    total_time = end_time - start_time
    avg_time = total_time / iterations * 1e6  # microseconds

    print(f"Time per call: {avg_time:.2f} us")
    print(f"Total time for {iterations} calls: {total_time:.4f} s")


if __name__ == "__main__":
    benchmark_get_latest_samples()
