import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))
import sys
import unittest
from unittest.mock import MagicMock, patch

# Create mock objects
mock_scipy = MagicMock()
mock_signal = MagicMock()
mock_windows = MagicMock()
mock_dpss = MagicMock()

# Configure scipy mocks
mock_windows.dpss = mock_dpss
mock_signal.windows = mock_windows
mock_scipy.signal = mock_signal

# Configure numpy mock
mock_numpy = MagicMock()
mock_numpy.float32 = 'float32'
mock_numpy.float64 = 'float64'
mock_numpy.complex64 = 'complex64'
mock_numpy.complex128 = 'complex128'

class TestFFTManagerWindows(unittest.TestCase):
    def setUp(self):
        # Patch sys.modules to simulate scipy and numpy presence
        self.modules_patcher = patch.dict(sys.modules, {
            'scipy': mock_scipy,
            'scipy.signal': mock_signal,
            'scipy.signal.windows': mock_windows,
            'numpy': mock_numpy
        })
        self.modules_patcher.start()

        # Reset mock_dpss for each test
        mock_dpss.reset_mock()

        # Import the function under test
        # Ensure clean import by removing from sys.modules if present
        if 'src.core.fft_manager' in sys.modules:
            del sys.modules['src.core.fft_manager']

        from src.core.fft_manager import get_dpss_windows
        self.get_dpss_windows = get_dpss_windows

        # Clear cache to ensure clean state
        self.get_dpss_windows.cache_clear()

    def tearDown(self):
        self.modules_patcher.stop()

    def test_get_dpss_windows_defaults(self):
        """Test basic call with defaults."""
        N = 1024
        mock_dpss.return_value = "windows_1024"

        result = self.get_dpss_windows(N)

        # Verify defaults: NW=3, Kmax=None -> Kmax=2*3-1=5
        mock_dpss.assert_called_once_with(N, 3, 5)
        self.assertEqual(result, "windows_1024")

    def test_get_dpss_windows_explicit(self):
        """Test call with explicit parameters."""
        N = 512
        NW = 4
        Kmax = 7
        mock_dpss.return_value = "windows_512_explicit"

        result = self.get_dpss_windows(N, NW, Kmax)

        mock_dpss.assert_called_once_with(N, NW, Kmax)
        self.assertEqual(result, "windows_512_explicit")

    def test_get_dpss_windows_caching(self):
        """Test that repeated calls use the cache."""
        N = 2048
        mock_dpss.return_value = "windows_2048"

        # First call
        res1 = self.get_dpss_windows(N)
        mock_dpss.assert_called_once_with(N, 3, 5)

        # Second call
        res2 = self.get_dpss_windows(N)
        # Should NOT call dpss again
        mock_dpss.assert_called_once()
        self.assertIs(res1, res2)

    def test_get_dpss_windows_kmax_logic(self):
        """Verify Kmax calculation logic."""
        N = 100
        NW = 2.5
        # Kmax = 2 * 2.5 - 1 = 4.0 -> int(4.0) = 4

        self.get_dpss_windows(N, NW)

        mock_dpss.assert_called_with(N, NW, 4)

if __name__ == '__main__':
    unittest.main()
