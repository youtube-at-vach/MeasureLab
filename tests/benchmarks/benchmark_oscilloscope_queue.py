import sys
import time
from unittest.mock import MagicMock

# Mock sounddevice before importing anything that uses it
sys.modules["sounddevice"] = MagicMock()

import numpy as np  # noqa: E402
from src.gui.widgets.oscilloscope import Oscilloscope  # noqa: E402


class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000
        self.calibration = MagicMock()
        self.calibration.input_sensitivity = 1.0

    def register_callback(self, callback):
        self.callback = callback
        return 1

    def unregister_callback(self, callback_id):
        self.callback = None


def benchmark_oscilloscope_queue():
    audio_engine = MockAudioEngine()

    # We need to patch AudioEngine class in the module if it's used for type hinting or inheritance
    # But Oscilloscope takes audio_engine as an argument.

    osc = Oscilloscope(audio_engine)
    osc.start_analysis()

    # Simulate Audio Callback
    block_size = 1024
    n_blocks = 50000  # Total frames: ~50M

    # Pre-allocate input data to feed into callback
    input_data = np.random.rand(block_size, 2).astype(np.float32)
    output_data = np.zeros((block_size, 2), dtype=np.float32)

    start_time = time.time()

    for _ in range(n_blocks):
        # 1. Callback
        osc.audio_engine.callback(input_data, output_data, block_size, 0, 0)

        # 2. Process Queue
        osc.process_queue()

    end_time = time.time()
    duration = end_time - start_time

    print(f"Processed {n_blocks} blocks in {duration:.4f} seconds.")
    print(f"Rate: {n_blocks / duration:.2f} blocks/sec")

    osc.stop_analysis()


if __name__ == "__main__":
    benchmark_oscilloscope_queue()
