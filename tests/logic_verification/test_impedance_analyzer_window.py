import unittest
from unittest.mock import MagicMock, patch
import numpy as np
import sys
import os
from scipy.signal import get_window

# Ensure src is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

# Mock sounddevice
sys.modules['sounddevice'] = MagicMock()

try:
    from src.gui.widgets.impedance_analyzer import ImpedanceAnalyzer
    from src.core.analysis import get_cached_window
except ImportError:
    # If imports fail (e.g. due to missing deps in environment), skip tests
    ImpedanceAnalyzer = None

class TestImpedanceAnalyzerWindow(unittest.TestCase):
    def setUp(self):
        if ImpedanceAnalyzer is None:
            self.skipTest("ImpedanceAnalyzer could not be imported")

        self.mock_audio_engine = MagicMock()
        self.mock_audio_engine.sample_rate = 48000
        self.analyzer = ImpedanceAnalyzer(self.mock_audio_engine)
        self.buffer_size = 1024
        self.analyzer.buffer_size = self.buffer_size

        # Populate input data
        with self.analyzer._buffer_lock:
            self.analyzer.input_data = np.ones((self.buffer_size, 2)) # Constant DC

    @patch('src.gui.widgets.impedance_analyzer.get_cached_window')
    def test_process_data_uses_cached_window(self, mock_get_window):
        # Setup mock return value to be a real window so math works
        # Use periodic hann window as expected by get_cached_window
        real_window = get_window("hann", self.buffer_size)
        mock_get_window.return_value = real_window

        self.analyzer.process_data()

        # Verify get_cached_window was called with correct args
        mock_get_window.assert_called_with("hann", self.buffer_size)

    def test_window_consistency(self):
        # Verify that get_cached_window returns the periodic Hann window
        # which is appropriate for spectral analysis.
        w = get_cached_window("hann", self.buffer_size)

        # We expect get_cached_window to return the same as scipy.signal.get_window('hann', ...)
        # which defaults to periodic (fftbins=True)
        expected = get_window("hann", self.buffer_size)

        np.testing.assert_allclose(w, expected, atol=1e-10)

if __name__ == '__main__':
    unittest.main()
