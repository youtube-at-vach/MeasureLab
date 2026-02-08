
import unittest
import sys
from unittest.mock import MagicMock, patch

class TestAnalysisResampleLogic(unittest.TestCase):
    """
    Logic verification for AudioCalc.resample.
    """

    def setUp(self):
        # Create mocks
        self.mock_numpy = MagicMock()
        self.mock_scipy = MagicMock()
        self.mock_scipy_signal = MagicMock()
        self.mock_scipy_optimize = MagicMock()
        self.mock_fft_manager = MagicMock()

        # Setup specific mocks needed for import
        self.mock_numpy.float64 = float
        self.mock_numpy.pi = 3.14159
        self.mock_scipy.signal = self.mock_scipy_signal
        self.mock_scipy.optimize = self.mock_scipy_optimize

        # Patch sys.modules
        self.module_patcher = patch.dict(sys.modules, {
            'numpy': self.mock_numpy,
            'scipy': self.mock_scipy,
            'scipy.signal': self.mock_scipy_signal,
            'scipy.optimize': self.mock_scipy_optimize,
            'src.core.fft_manager': self.mock_fft_manager
        })
        self.module_patcher.start()

        # Ensure we load a fresh version of the module using the mocks
        # We must remove it if it exists to force re-import with patched dependencies
        if 'src.core.analysis' in sys.modules:
            del sys.modules['src.core.analysis']

        import src.core.analysis
        self.AudioCalc = src.core.analysis.AudioCalc

    def tearDown(self):
        self.module_patcher.stop()

        # Clean up so subsequent tests load the real module (or fail if dependencies missing)
        # This prevents the mocked module from polluting other tests
        if 'src.core.analysis' in sys.modules:
            del sys.modules['src.core.analysis']

    def test_resample_invalid_sample_rates(self):
        """
        Verify resample returns original data if sample rates are invalid (<= 0).
        """
        data = MagicMock()

        # Test source_sr <= 0
        result = self.AudioCalc.resample(data, 0, 48000)
        self.assertIs(result, data)

        result = self.AudioCalc.resample(data, -100, 48000)
        self.assertIs(result, data)

        # Test target_sr <= 0
        result = self.AudioCalc.resample(data, 44100, 0)
        self.assertIs(result, data)

        result = self.AudioCalc.resample(data, 44100, -50)
        self.assertIs(result, data)

    def test_resample_same_sample_rate(self):
        """
        Verify resample returns original data immediately if source_sr == target_sr.
        """
        data = MagicMock()
        result = self.AudioCalc.resample(data, 48000, 48000)
        self.assertIs(result, data)

    def test_resample_calculation_gcd(self):
        """
        Verify resample calculates correct up/down factors based on GCD.
        """
        data = MagicMock()

        # Case 1: 44100 -> 48000
        # GCD(44100, 48000) = 300
        # up = 48000 // 300 = 160
        # down = 44100 // 300 = 147
        self.AudioCalc.resample(data, 44100, 48000)
        self.mock_scipy_signal.resample_poly.assert_called_with(data, 160, 147)

        # Reset mock for next assertion
        self.mock_scipy_signal.resample_poly.reset_mock()

        # Case 2: 48000 -> 96000 (Simple 2x upsample)
        # GCD(48000, 96000) = 48000
        # up = 96000 // 48000 = 2
        # down = 48000 // 48000 = 1
        self.AudioCalc.resample(data, 48000, 96000)
        self.mock_scipy_signal.resample_poly.assert_called_with(data, 2, 1)

        self.mock_scipy_signal.resample_poly.reset_mock()

        # Case 3: 96000 -> 48000 (Simple 2x downsample)
        # GCD(96000, 48000) = 48000
        # up = 48000 // 48000 = 1
        # down = 96000 // 48000 = 2
        self.AudioCalc.resample(data, 96000, 48000)
        self.mock_scipy_signal.resample_poly.assert_called_with(data, 1, 2)

    def test_resample_mock_data_passing(self):
        """
        Verify data is passed correctly to resample_poly.
        """
        mock_result = MagicMock()
        self.mock_scipy_signal.resample_poly.return_value = mock_result
        input_data = MagicMock()

        result = self.AudioCalc.resample(input_data, 1000, 2000)

        self.assertIs(result, mock_result)
        self.mock_scipy_signal.resample_poly.assert_called_once()
        # Check args: data, up=2, down=1 (1000->2000)
        args, _ = self.mock_scipy_signal.resample_poly.call_args
        self.assertIs(args[0], input_data)
        self.assertEqual(args[1], 2)
        self.assertEqual(args[2], 1)

if __name__ == '__main__':
    unittest.main()
