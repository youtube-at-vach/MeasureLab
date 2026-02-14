import unittest
import numpy as np
from unittest.mock import MagicMock, patch
import sys

# Mock modules BEFORE importing the module under test
mock_modules = {
    'PyQt6.QtCore': MagicMock(),
    'PyQt6.QtWidgets': MagicMock(),
    'pyqtgraph': MagicMock(),
    'src.core.audio_engine': MagicMock(),
    'src.core.localization': MagicMock(),
    'scipy.signal': MagicMock(),
    'scipy.optimize': MagicMock(),
    'scipy': MagicMock(),
    'soundfile': MagicMock(),
}

patcher = patch.dict(sys.modules, mock_modules)
patcher.start()

# Setup common mocks
sys.modules['src.core.localization'].tr = lambda x: x

# Mock src.core.analysis specifically because NoiseProfiler imports from it
mock_analysis = MagicMock()
sys.modules['src.core.analysis'] = mock_analysis

def get_cached_window_mock(name, length):
    return np.ones(length) # Rectangular window for simplicity in test

mock_analysis.get_cached_window = get_cached_window_mock
mock_analysis.AudioCalc = MagicMock()
# Mock calculate_noise_profile to return dummy results
mock_analysis.AudioCalc.calculate_noise_profile.return_value = {
    "hum_rms": 0, "noise_rms_20k": 0, "white_density": 0,
    "flicker_slope": 0, "flicker_intercept": 0, "hum_components": []
}

# Now import the module
import src.gui.widgets.noise_profiler as np_module
from src.gui.widgets.noise_profiler import NoiseProfiler
from src.core.fft_manager import fft_manager

class TestNoiseProfilerLogic(unittest.TestCase):
    def setUp(self):
        self.mock_engine = MagicMock()
        self.mock_engine.sample_rate = 1000.0 # Simple rate
        self.mock_engine.calibration.get_input_offset_db.return_value = 0.0

        self.profiler = NoiseProfiler(self.mock_engine)
        self.profiler.buffer_size = 100 # Small buffer
        self.profiler.set_buffer_size(100) # Reset

    def tearDown(self):
        pass

    def test_buffer_logic_reconstruction(self):
        # This test verifies that data fed into the callback is correctly
        # available in process_data, preserving order.

        self.profiler.start_analysis()
        callback = self.mock_engine.register_callback.call_args[0][0]

        # Generate a ramp signal: 0, 1, 2, ...
        # This allows easy verification of order.
        data_len = 250 # More than 2x buffer size to force wrap
        ramp = np.arange(data_len, dtype=float)

        # Feed in chunks
        chunk_size = 20
        for i in range(0, data_len, chunk_size):
            chunk = ramp[i:i+chunk_size]
            indata = np.zeros((len(chunk), 2))
            indata[:, 0] = chunk
            indata[:, 1] = chunk

            # Call callback
            callback(indata, np.zeros_like(indata), len(chunk), None, None)

        # The buffer size is 100.
        # The last 100 samples of ramp should be in the buffer.
        # ramp is 0..249.
        # Expected content: 150..249.
        expected = np.arange(150, 250, dtype=float)

        # Intercept fft_manager.rfft call
        with patch.object(fft_manager, 'rfft', wraps=fft_manager.rfft) as mock_rfft:
            self.profiler.process_data(0, "dBV", False)

            # Check arguments
            if mock_rfft.call_count == 0:
                self.fail("rfft was not called, process_data might have failed early")

            args, _ = mock_rfft.call_args
            fft_input_arg = args[0]

            # fft_input_arg should be the linear data (last 100 samples)
            # It might be multiplied by window (ones).

            np.testing.assert_array_almost_equal(fft_input_arg, expected,
                err_msg="Reconstructed data passed to FFT does not match expected linear sequence")

if __name__ == '__main__':
    unittest.main()
