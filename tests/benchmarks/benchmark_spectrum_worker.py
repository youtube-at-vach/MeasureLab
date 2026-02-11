
import timeit
import numpy as np
import sys
import os
from unittest.mock import MagicMock

# Add repo root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

# Mock sounddevice before importing anything that uses it
sys.modules['sounddevice'] = MagicMock()

# Mock AudioEngine
mock_audio_engine = MagicMock()
mock_audio_engine.sample_rate = 48000
mock_audio_engine.register_callback.return_value = 1

# Mock Calibration
mock_calibration = MagicMock()
mock_calibration.get_input_offset_db.return_value = 0.0
mock_calibration.get_spl_offset_db.return_value = 0.0
mock_audio_engine.calibration = mock_calibration

# Import SpectrumAnalyzer
from src.gui.widgets.spectrum_analyzer import SpectrumAnalyzer, SpectrumAnalysisWorker  # noqa: E402

def benchmark_size(size, multitaper=False, iterations=50):
    # Setup
    module = SpectrumAnalyzer(mock_audio_engine)
    module.set_buffer_size(size)
    module.multitaper_enabled = multitaper
    module.start_analysis()

    # Initialize worker
    worker = SpectrumAnalysisWorker(module)

    # Fill queue with some data to simulate audio callback
    chunk_size = 1024

    module.input_data = np.random.rand(module.buffer_size, 2).astype(np.float32)

    mt_str = " (Multitaper)" if multitaper else ""
    print(f"Benchmarking Spectrum Analysis (FFT Size={module.buffer_size}){mt_str}")

    def workload():
        module.audio_queue.put(np.random.rand(chunk_size, 2).astype(np.float32))
        # Call process_cycle directly instead of run()
        worker.process_cycle()

    t = timeit.timeit(workload, number=iterations)

    print(f"  Total Time ({iterations} runs): {t:.4f} seconds")
    print(f"  Avg Time per run: {t/iterations*1000:.2f} ms")

if __name__ == "__main__":
    benchmark_size(16384, False, 100)
    benchmark_size(16384, True, 20)
    benchmark_size(131072, False, 20)
