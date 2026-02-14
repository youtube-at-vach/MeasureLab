import unittest
from unittest.mock import MagicMock, patch
import numpy as np
import sys
import os

# Ensure repo root is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.gui.widgets.noise_profiler import NoiseProfiler, NoiseAnalysisWorker

class MockEngine:
    def __init__(self):
        self.sample_rate = 48000
        self.calibration = MagicMock()
        self.calibration.get_input_offset_db.return_value = 0.0

    def register_callback(self, cb):
        return 1

    def unregister_callback(self, id):
        pass

class TestNoiseProfilerAverage(unittest.TestCase):
    def setUp(self):
        self.engine = MockEngine()
        self.profiler = NoiseProfiler(self.engine)
        # Manually set attributes that will be added
        self.profiler.average_mode = True
        self.profiler.target_averages = 10
        self.profiler.current_avg_count = 0
        self.profiler.accumulated_magnitude = None
        self.profiler._avg_magnitude = None
        self.profiler.buffer_size = 1024
        self.profiler.input_data = np.zeros((1024, 2))

    def test_averaging_logic(self):
        # Simulate 3 updates

        # Test Data
        mag1 = np.ones(513) * 1.0
        mag2 = np.ones(513) * 2.0
        mag3 = np.ones(513) * 3.0

        # Step 1
        self.profiler.update_average(mag1)
        self.assertEqual(self.profiler.current_avg_count, 1)
        np.testing.assert_array_almost_equal(self.profiler._avg_magnitude, mag1)

        # Step 2
        self.profiler.update_average(mag2)
        self.assertEqual(self.profiler.current_avg_count, 2)
        # Avg of 1 and 2 is 1.5
        np.testing.assert_array_almost_equal(self.profiler._avg_magnitude, np.ones(513) * 1.5)

        # Step 3
        self.profiler.update_average(mag3)
        self.assertEqual(self.profiler.current_avg_count, 3)
        # Avg of 1, 2, 3 is 2.0
        np.testing.assert_array_almost_equal(self.profiler._avg_magnitude, np.ones(513) * 2.0)

class TestNoiseProfilerProcess(unittest.TestCase):
    def setUp(self):
        self.engine = MagicMock()
        self.engine.sample_rate = 48000
        self.engine.calibration.get_input_offset_db.return_value = 0.0

        self.profiler = NoiseProfiler(self.engine)
        self.profiler.buffer_size = 1024
        # Fill input data
        self.profiler.input_data = np.random.rand(1024, 2)

    def test_process_data_smoke(self):
        # Basic smoke test
        output = self.profiler.process_data(channel_idx=0, unit_mode="dBV", apply_gain_correction=False)

        self.assertIsNotNone(output)
        freqs, mag, results, raw_avg = output

        self.assertIsNotNone(freqs)
        self.assertIsNotNone(mag)
        self.assertIsNotNone(results)
        self.assertEqual(len(freqs), 513) # 1024/2 + 1
        self.assertEqual(len(mag), 513)
        self.assertIn("white_density", results)

    def test_process_data_insufficient_data(self):
        self.profiler.input_data = np.zeros((100, 2)) # Less than buffer_size
        output = self.profiler.process_data(0, "dBV", False)
        self.assertIsNone(output)

class TestNoiseProfilerLogging(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ensure QApplication exists for signal emission
        try:
            from PyQt6.QtWidgets import QApplication
            if not QApplication.instance():
                cls.app = QApplication([])
            else:
                cls.app = QApplication.instance()
        except ImportError:
            pass

    def test_worker_exception_logging(self):
        """
        Verify that exceptions in NoiseAnalysisWorker.run are logged using logger.error with exc_info=True,
        and that the error signal is emitted.
        """
        # Mock AudioEngine
        mock_engine = MagicMock()

        # Initialize Module
        module = NoiseProfiler(mock_engine)

        # Mock process_data to raise an exception
        test_exception = ValueError("Simulated Crash")
        module.process_data = MagicMock(side_effect=test_exception)

        # Create Worker
        # We don't need real channel_idx etc for this test as process_data is mocked
        worker = NoiseAnalysisWorker(module, channel_idx=0, unit_mode="dBV", apply_gain=False)

        # Connect signals
        error_slot = MagicMock()
        worker.signals.error.connect(error_slot)

        # Mock the logger in the module
        with patch('src.gui.widgets.noise_profiler.logger', create=True) as mock_logger:
            # Run worker directly
            worker.run()

            # Check that process_data was actually called
            module.process_data.assert_called()

            # Check if error signal was emitted
            error_slot.assert_called_once_with("Simulated Crash")

            # Check if logger.error was called
            assert mock_logger.error.called, "logger.error should be called"

            # Verify arguments
            args, kwargs = mock_logger.error.call_args
            assert "Error in NoiseAnalysisWorker" in args[0]
            assert "Simulated Crash" in args[0]
            assert kwargs.get('exc_info') is True, "exc_info=True is required for full traceback"

if __name__ == '__main__':
    unittest.main()
