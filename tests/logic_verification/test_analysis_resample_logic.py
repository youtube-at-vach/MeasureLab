import sys
import unittest
from unittest.mock import MagicMock, patch

# Define the mocks
mock_numpy = MagicMock()
mock_scipy = MagicMock()
mock_scipy_signal = MagicMock()
mock_scipy_optimize = MagicMock()
# Mock submodules
mock_scipy.signal = mock_scipy_signal
mock_scipy.optimize = mock_scipy_optimize

mock_fft_manager = MagicMock()

# Setup module dictionary
# We need to mock everything that src.core.analysis imports that might not be present or valid
modules_to_patch = {
    "numpy": mock_numpy,
    "scipy": mock_scipy,
    "scipy.signal": mock_scipy_signal,
    "scipy.optimize": mock_scipy_optimize,
    "src.core.fft_manager": mock_fft_manager,
}

class TestAudioCalcResample(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # We need to apply the patch before importing src.core.analysis
        cls.patcher = patch.dict(sys.modules, modules_to_patch)
        cls.patcher.start()

        # Now we can safely import AudioCalc
        # We must force a reload or fresh import if it was already loaded
        if 'src.core.analysis' in sys.modules:
            # If it was already loaded, we remove it so it re-imports using our mocks
            del sys.modules['src.core.analysis']

        # Attempt import
        try:
            from src.core.analysis import AudioCalc
            cls.AudioCalc = AudioCalc
        except Exception as e:
            # If import fails, we should stop the patcher to clean up
            cls.patcher.stop()
            raise e

    @classmethod
    def tearDownClass(cls):
        cls.patcher.stop()
        # Ensure we don't leave a mocked module behind, forcing a clean reload for other tests
        if 'src.core.analysis' in sys.modules:
            del sys.modules['src.core.analysis']

    def setUp(self):
        # Reset mocks before each test
        mock_scipy_signal.reset_mock()
        mock_numpy.reset_mock()

    def test_resample_identity(self):
        """Test that resampling to the same rate returns original data."""
        data = MagicMock()
        source_sr = 48000
        target_sr = 48000

        result = self.AudioCalc.resample(data, source_sr, target_sr)

        # Should return data directly without calling resample_poly
        self.assertIs(result, data)
        mock_scipy_signal.resample_poly.assert_not_called()

    def test_resample_invalid_source_sr(self):
        """Test that invalid source SR returns original data."""
        data = MagicMock()
        source_sr = 0
        target_sr = 48000

        result = self.AudioCalc.resample(data, source_sr, target_sr)

        self.assertIs(result, data)
        mock_scipy_signal.resample_poly.assert_not_called()

    def test_resample_invalid_target_sr(self):
        """Test that invalid target SR returns original data."""
        data = MagicMock()
        source_sr = 48000
        target_sr = -100

        result = self.AudioCalc.resample(data, source_sr, target_sr)

        self.assertIs(result, data)
        mock_scipy_signal.resample_poly.assert_not_called()

    def test_resample_upsampling_integer(self):
        """Test upsampling with integer ratio (e.g. 48k -> 96k)."""
        data = MagicMock()
        source_sr = 48000
        target_sr = 96000

        # Expected: GCD = 48000. up = 2, down = 1

        self.AudioCalc.resample(data, source_sr, target_sr)

        mock_scipy_signal.resample_poly.assert_called_once_with(data, 2, 1)

    def test_resample_downsampling_integer(self):
        """Test downsampling with integer ratio (e.g. 48k -> 24k)."""
        data = MagicMock()
        source_sr = 48000
        target_sr = 24000

        # Expected: GCD = 24000. up = 1, down = 2

        self.AudioCalc.resample(data, source_sr, target_sr)

        mock_scipy_signal.resample_poly.assert_called_once_with(data, 1, 2)

    def test_resample_fractional(self):
        """Test resampling with fractional ratio (e.g. 44100 -> 48000)."""
        data = MagicMock()
        source_sr = 44100
        target_sr = 48000

        # GCD of 44100 and 48000 is 300.
        # up = 48000 / 300 = 160
        # down = 44100 / 300 = 147

        self.AudioCalc.resample(data, source_sr, target_sr)

        mock_scipy_signal.resample_poly.assert_called_once_with(data, 160, 147)

    def test_resample_float_inputs(self):
        """Test that float sampling rates are handled correctly."""
        data = MagicMock()
        source_sr = 44100.0
        target_sr = 48000.0

        self.AudioCalc.resample(data, source_sr, target_sr)

        # Should be converted to int internally for GCD
        mock_scipy_signal.resample_poly.assert_called_once_with(data, 160, 147)
