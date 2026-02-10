import time
import sys
import os
import numpy as np
from unittest.mock import MagicMock

# Ensure src is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

# Mock sounddevice before importing anything that uses it
sys.modules['sounddevice'] = MagicMock()

# Mock QApplication to avoid "QApplication was not created in the main() thread" issues if any widget is touched
# But ImpedanceAnalyzer logic class shouldn't need it.
# However, importing the module might trigger some Qt things.

try:
    from src.gui.widgets.impedance_analyzer import ImpedanceAnalyzer
except ImportError as e:
    print(f"Import failed: {e}")
    sys.exit(1)

def benchmark():
    print("Benchmarking ImpedanceAnalyzer.process_data window creation...")

    # Mock AudioEngine
    mock_audio_engine = MagicMock()
    mock_audio_engine.sample_rate = 48000
    mock_audio_engine.register_callback = MagicMock()

    # Instantiate
    try:
        analyzer = ImpedanceAnalyzer(mock_audio_engine)
    except Exception as e:
        print(f"Failed to instantiate ImpedanceAnalyzer: {e}")
        # If it fails due to missing QApplication (though unlikely for this class), we might need to mock more.
        return

    # Setup parameters
    buffer_size = 8192 # Use a reasonably large buffer to make window creation significant
    analyzer.buffer_size = buffer_size
    analyzer.set_base_buffer_size(buffer_size)

    # Mock input data
    # ImpedanceAnalyzer uses self.input_data
    # We need to populate it.
    # process_data copies it: data = np.array(self.input_data, copy=True)
    with analyzer._buffer_lock:
        analyzer.input_data = np.random.rand(buffer_size, 2).astype(np.float64)

    # Set other params
    analyzer.gen_frequency = 1000.0
    analyzer.voltage_channel = 0
    analyzer.current_channel = 1
    analyzer.averaging_count = 1

    # Warmup
    print("Warming up...")
    for _ in range(10):
        analyzer.process_data()

    iterations = 2000
    start_time = time.time()

    print(f"Running {iterations} iterations with buffer size {buffer_size}...")
    for _ in range(iterations):
        analyzer.process_data()

    end_time = time.time()
    total_time = end_time - start_time
    avg_time = total_time / iterations

    print(f"Total time: {total_time:.4f} s")
    print(f"Average time per iteration: {avg_time:.6f} s")
    print(f"Throughput: {1/avg_time:.2f} calls/s")

if __name__ == "__main__":
    benchmark()
