import sys
import time
from unittest.mock import MagicMock

sys.modules['sounddevice'] = MagicMock()

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

def benchmark_oscilloscope_start_analysis():
    audio_engine = MockAudioEngine()
    osc = Oscilloscope(audio_engine)

    n_iterations = 100000

    start_time = time.time()
    for _ in range(n_iterations):
        osc.start_analysis()
        osc.stop_analysis()

    end_time = time.time()
    duration = end_time - start_time

    print(f"Executed start_analysis/stop_analysis {n_iterations} times in {duration:.4f} seconds.")
    print(f"Rate: {n_iterations / duration:.2f} iterations/sec")

if __name__ == "__main__":
    benchmark_oscilloscope_start_analysis()
