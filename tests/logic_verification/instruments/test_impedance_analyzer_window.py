import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))
import unittest
from unittest.mock import MagicMock, patch
import numpy as np
import sys
from scipy.signal import get_window

class TestImpedanceAnalyzerWindow(unittest.TestCase):
    def setUp(self):
        # Define mocks
        self.mock_pyqt = MagicMock()
        self.mock_sd = MagicMock()
        self.mock_pg = MagicMock()
        self.mock_loc = MagicMock()
        self.mock_loc.tr = lambda x, default=None: x

        # Modules to patch
        self.modules_to_patch = {
            'PyQt6': self.mock_pyqt,
            'PyQt6.QtCore': self.mock_pyqt,
            'PyQt6.QtGui': self.mock_pyqt,
            'PyQt6.QtWidgets': self.mock_pyqt,
            'pyqtgraph': self.mock_pg,
            'sounddevice': self.mock_sd,
            'src.core.localization': self.mock_loc,
        }

        self.original_modules = {}
        for name, mock_obj in self.modules_to_patch.items():
            if name in sys.modules:
                self.original_modules[name] = sys.modules[name]
            sys.modules[name] = mock_obj

        # Force reload of the module under test to ensure it uses the mocked dependencies
        if 'src.gui.widgets.impedance_analyzer' in sys.modules:
            del sys.modules['src.gui.widgets.impedance_analyzer']

        try:
            import src.gui.widgets.impedance_analyzer
            self.ImpedanceAnalyzer = src.gui.widgets.impedance_analyzer.ImpedanceAnalyzer
        except ImportError:
            self.skipTest("ImpedanceAnalyzer could not be imported")

        self.mock_audio_engine = MagicMock()
        self.mock_audio_engine.sample_rate = 48000
        self.analyzer = self.ImpedanceAnalyzer(self.mock_audio_engine)
        self.buffer_size = 1024
        self.analyzer.buffer_size = self.buffer_size

        # Populate input data
        with self.analyzer._buffer_lock:
            self.analyzer.input_data = np.ones((self.buffer_size, 2)) # Constant DC

    def tearDown(self):
        # Restore sys.modules
        for name in self.modules_to_patch:
            if name in self.original_modules:
                sys.modules[name] = self.original_modules[name]
            else:
                del sys.modules[name]

        # Cleanup module cache
        if 'src.gui.widgets.impedance_analyzer' in sys.modules:
            del sys.modules['src.gui.widgets.impedance_analyzer']

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

        # Note: We need to import get_cached_window from the (possibly mocked) module context
        # or import it directly if it doesn't depend on GUI.
        # src.core.analysis depends on scipy/numpy, not GUI.
        from src.core.analysis import get_cached_window

        w = get_cached_window("hann", self.buffer_size)

        # We expect get_cached_window to return the same as scipy.signal.get_window('hann', ...)
        # which defaults to periodic (fftbins=True)
        expected = get_window("hann", self.buffer_size)

        np.testing.assert_allclose(w, expected, atol=1e-10)

if __name__ == '__main__':
    unittest.main()
