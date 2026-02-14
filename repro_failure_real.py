
import unittest
from unittest.mock import MagicMock, patch
import sys

# Mock sounddevice before importing module under test
sys.modules['sounddevice'] = MagicMock()
sys.modules['src.core.audio_engine'] = MagicMock()

# Now import
from src.gui.widgets.noise_profiler import NoiseProfiler, NoiseAnalysisWorker

class TestNoiseProfilerLogging(unittest.TestCase):
    def test_worker_exception_logging(self):
        # Mock AudioEngine
        mock_engine = MagicMock()

        # Initialize Module
        module = NoiseProfiler(mock_engine)

        # Mock process_data to raise an exception
        test_exception = ValueError("Simulated Crash")
        module.process_data = MagicMock(side_effect=test_exception)

        # Create Worker
        worker = NoiseAnalysisWorker(module, channel_idx=0, unit_mode="dBV", apply_gain=False)

        # Connect signals
        error_slot = MagicMock()
        worker.signals.error.connect(error_slot)

        # Mock the logger in the module
        with patch('src.gui.widgets.noise_profiler.logger', create=True) as mock_logger:
            # Run worker directly
            worker.run()

            # Check if error signal was emitted
            error_slot.assert_called_once_with("Simulated Crash")

            # Check if logger.error was called
            assert mock_logger.error.called

if __name__ == "__main__":
    unittest.main()
