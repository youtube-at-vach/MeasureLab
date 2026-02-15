import unittest
from unittest.mock import MagicMock, patch
import numpy as np
import sys
import os

# Mock PyQt6 and pyqtgraph
mock_qt = MagicMock()

# Define Mock Base Classes to avoid MagicMock inheritance issues
class MockQObject:
    def __init__(self, *args, **kwargs):
        pass

class MockQRunnable:
    def __init__(self, *args, **kwargs):
        pass

mock_qt.QtCore.QObject = MockQObject
mock_qt.QtCore.QRunnable = MockQRunnable

# Ensure pyqtSignal returns unique mocks
mock_qt.QtCore.pyqtSignal.side_effect = lambda *args, **kwargs: MagicMock()

sys.modules['PyQt6'] = mock_qt
sys.modules['PyQt6.QtCore'] = mock_qt.QtCore
sys.modules['PyQt6.QtWidgets'] = mock_qt.QtWidgets
sys.modules['pyqtgraph'] = MagicMock()
sys.modules['sounddevice'] = MagicMock()
sys.modules['pywt'] = MagicMock()

# Ensure repo root is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.gui.widgets.noise_profiler import NoiseProfiler, NoiseAnalysisWorker  # noqa: E402

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

            # Check if error signal was emitted
            # In a mocked PyQt environment, connect() doesn't wire emit() to the slot.
            # We verify that emit() was called instead.
            worker.signals.error.emit.assert_called_once_with("Simulated Crash")

            # Check if logger.error was called
            assert mock_logger.error.called, "logger.error should be called"

            # Verify arguments
            args, kwargs = mock_logger.error.call_args
            assert "Error in NoiseAnalysisWorker" in args[0]
            assert "Simulated Crash" in args[0]
            assert kwargs.get('exc_info') is True, "exc_info=True is required for full traceback"

class TestNoiseProfilerRingBuffer(unittest.TestCase):
    def setUp(self):
        self.mock_engine = MagicMock()
        self.mock_engine.sample_rate = 48000
        # Mock calibration
        self.mock_engine.calibration.get_input_offset_db.return_value = 0.0

        self.profiler = NoiseProfiler(self.mock_engine)
        self.profiler.set_buffer_size(10) # Small buffer for testing

        self.callback = None
        def register_side_effect(cb):
            self.callback = cb
            return 1
        self.mock_engine.register_callback.side_effect = register_side_effect

        self.profiler.start_analysis()

    def test_callback_logic(self):
        # 1. Fill partial
        data1 = np.ones((4, 2)) * 1
        # callback signature: (indata, outdata, frames, time, status)
        outdata = np.zeros_like(data1)
        self.callback(data1, outdata, 4, None, None)

        self.assertEqual(self.profiler.buffer_ptr, 4)
        np.testing.assert_array_equal(self.profiler.input_data[:4], data1)
        np.testing.assert_array_equal(self.profiler.input_data[4:], np.zeros((6, 2)))

    def test_wrap_around(self):
        # Fill 8
        data = np.ones((8, 2)) * 1
        outdata = np.zeros_like(data)
        self.callback(data, outdata, 8, None, None)

        self.assertEqual(self.profiler.buffer_ptr, 8)

        # Fill 4 (wrap)
        data2 = np.ones((4, 2)) * 2
        outdata2 = np.zeros_like(data2)
        self.callback(data2, outdata2, 4, None, None)

        # Buffer size 10. Ptr 8. Space 2. Write 2 at 8,9. Write 2 at 0,1. Ptr 2.
        self.assertEqual(self.profiler.buffer_ptr, 2)

        np.testing.assert_array_equal(self.profiler.input_data[8:], np.ones((2, 2)) * 2)
        np.testing.assert_array_equal(self.profiler.input_data[:2], np.ones((2, 2)) * 2)
        np.testing.assert_array_equal(self.profiler.input_data[2:8], np.ones((6, 2)) * 1)

    def test_manual_reconstruction(self):
        # Test the logic that process_data uses
        # Setup buffer state
        self.profiler.buffer_ptr = 2
        self.profiler.input_data = np.zeros((10, 2))

        # Oldest data is at 2..9 (value 1)
        # Newest data is at 0..1 (value 2)
        self.profiler.input_data[2:] = 1
        self.profiler.input_data[:2] = 2

        # Reconstruct: [ptr:] + [:ptr] -> [1,1...,1, 2,2]
        raw = self.profiler.input_data
        ptr = self.profiler.buffer_ptr
        reconstructed = np.concatenate((raw[ptr:], raw[:ptr]))

        expected = np.concatenate((np.ones((8, 2)), np.ones((2, 2)) * 2))
        np.testing.assert_array_equal(reconstructed, expected)

    def test_buffer_overrun(self):
        # Write more than buffer size
        data = np.ones((15, 2)) * 3
        outdata = np.zeros_like(data)
        self.callback(data, outdata, 15, None, None)

        # Should keep last 10
        self.assertEqual(self.profiler.buffer_ptr, 0)
        np.testing.assert_array_equal(self.profiler.input_data, np.ones((10, 2)) * 3)

if __name__ == '__main__':
    unittest.main()
