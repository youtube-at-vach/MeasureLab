import sys
import os
import unittest
import numpy as np
from unittest.mock import MagicMock, patch

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))

# Import for optimization tests (will be used by TestFFTOptimization)
try:
    from src.core.fft_manager import fft_manager, HAS_PYFFTW
except ImportError:
    # If imports fail (e.g. dependencies missing), these might be None
    fft_manager = None
    HAS_PYFFTW = False

class TestFFTWarmup(unittest.TestCase):
    def setUp(self):
        self.mock_numpy = MagicMock()
        self.mock_numpy.float32 = 'float32'
        self.mock_numpy.float64 = 'float64'
        self.mock_numpy.complex64 = 'complex64'
        self.mock_numpy.complex128 = 'complex128'
        self.mock_pyfftw = MagicMock()

        # Patch sys.modules manually
        self.original_modules = sys.modules.copy()
        sys.modules['numpy'] = self.mock_numpy
        sys.modules['pyfftw'] = self.mock_pyfftw

        # Make sure src.core.fft_manager is not in sys.modules so we can re-import it with mocks
        if 'src.core.fft_manager' in sys.modules:
            del sys.modules['src.core.fft_manager']

    def tearDown(self):
        # Restore sys.modules state for cleanliness
        to_restore = ['numpy', 'pyfftw', 'src.core.fft_manager']

        for mod in to_restore:
            # Remove our mock/module if it wasn't there originally
            if mod in sys.modules and mod not in self.original_modules:
                del sys.modules[mod]

            # Restore original if it was there (e.g. if we patched an existing module)
            if mod in self.original_modules:
                sys.modules[mod] = self.original_modules[mod]

    def test_warmup_includes_float32(self):
        # Import inside the test method, after setUp has mocked modules
        import src.core.fft_manager
        from src.core.fft_manager import FFTManager, WARMUP_SIZES

        # Verify HAS_PYFFTW is True (mocked)
        self.assertTrue(src.core.fft_manager.HAS_PYFFTW, "HAS_PYFFTW should be True with mock")

        # Mock load_wisdom/save_wisdom on the class itself before instantiation
        with patch.object(FFTManager, 'load_wisdom'), \
             patch.object(FFTManager, 'save_wisdom'):

            manager = FFTManager()

            # Mock get_plan to track calls.
            manager.get_plan = MagicMock()

            # Call warmup
            manager.warmup(callback=MagicMock())

            # Verify calls
            missing_calls = []
            for size in WARMUP_SIZES:
                # Check for float64
                try:
                    manager.get_plan.assert_any_call(size, "float64", flags=("FFTW_MEASURE",))
                except AssertionError:
                    missing_calls.append(f"Missing float64 warmup for size {size}")

                # Check for float32
                try:
                    manager.get_plan.assert_any_call(size, "float32", flags=("FFTW_MEASURE",))
                except AssertionError:
                    missing_calls.append(f"Missing float32 warmup for size {size}")

            if missing_calls:
                print("\n".join(missing_calls))
                self.fail("Missing warmup calls")

class TestFFTManagerWindows(unittest.TestCase):
    def setUp(self):
        self.mock_scipy = MagicMock()
        self.mock_signal = MagicMock()
        self.mock_windows = MagicMock()
        self.mock_dpss = MagicMock()

        # Configure scipy mocks
        self.mock_windows.dpss = self.mock_dpss
        self.mock_signal.windows = self.mock_windows
        self.mock_scipy.signal = self.mock_signal

        self.mock_numpy = MagicMock()
        self.mock_numpy.float32 = 'float32'
        self.mock_numpy.float64 = 'float64'
        self.mock_numpy.complex64 = 'complex64'
        self.mock_numpy.complex128 = 'complex128'

        # Patch sys.modules to simulate scipy and numpy presence
        self.modules_patcher = patch.dict(sys.modules, {
            'scipy': self.mock_scipy,
            'scipy.signal': self.mock_signal,
            'scipy.signal.windows': self.mock_windows,
            'numpy': self.mock_numpy
        })
        self.modules_patcher.start()

        # Reset mock_dpss for each test
        self.mock_dpss.reset_mock()

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
        self.mock_dpss.return_value = "windows_1024"

        result = self.get_dpss_windows(N)

        # Verify defaults: NW=3, Kmax=None -> Kmax=2*3-1=5
        self.mock_dpss.assert_called_once_with(N, 3, 5)
        self.assertEqual(result, "windows_1024")

    def test_get_dpss_windows_explicit(self):
        """Test call with explicit parameters."""
        N = 512
        NW = 4
        Kmax = 7
        self.mock_dpss.return_value = "windows_512_explicit"

        result = self.get_dpss_windows(N, NW, Kmax)

        self.mock_dpss.assert_called_once_with(N, NW, Kmax)
        self.assertEqual(result, "windows_512_explicit")

    def test_get_dpss_windows_caching(self):
        """Test that repeated calls use the cache."""
        N = 2048
        self.mock_dpss.return_value = "windows_2048"

        # First call
        res1 = self.get_dpss_windows(N)
        self.mock_dpss.assert_called_once_with(N, 3, 5)

        # Second call
        res2 = self.get_dpss_windows(N)
        # Should NOT call dpss again
        self.mock_dpss.assert_called_once()
        self.assertIs(res1, res2)

    def test_get_dpss_windows_kmax_logic(self):
        """Verify Kmax calculation logic."""
        N = 100
        NW = 2.5
        # Kmax = 2 * 2.5 - 1 = 4.0 -> int(4.0) = 4

        self.get_dpss_windows(N, NW)

        self.mock_dpss.assert_called_with(N, NW, 4)

class TestFFTOptimization(unittest.TestCase):
    def test_rfft_out_param(self):
        if fft_manager is None:
            self.skipTest("FFTManager not available")
        N = 1024
        data = np.random.random(N).astype(np.float64)

        # Baseline
        res_base = fft_manager.rfft(data)

        # With out
        out_buf = np.zeros_like(res_base)
        res_opt = fft_manager.rfft(data, out=out_buf)

        self.assertIs(res_opt, out_buf)
        np.testing.assert_allclose(res_opt, res_base, rtol=1e-10)

    def test_irfft_out_param(self):
        if fft_manager is None:
            self.skipTest("FFTManager not available")
        N = 1024
        data = np.random.random(N).astype(np.float64)

        # Get FFT first
        fft_data = fft_manager.rfft(data)

        # Baseline irfft
        res_base = fft_manager.irfft(fft_data, n=N)

        # With out
        out_buf = np.zeros_like(res_base)
        res_opt = fft_manager.irfft(fft_data, n=N, out=out_buf)

        self.assertIs(res_opt, out_buf)
        np.testing.assert_allclose(res_opt, res_base, rtol=1e-10)

    def test_rfft_out_param_float32(self):
        if fft_manager is None:
            self.skipTest("FFTManager not available")
        N = 1024
        data = np.random.random(N).astype(np.float32)

        # Baseline
        res_base = fft_manager.rfft(data)

        # With out
        # Output of rfft for float32 input is complex64
        out_buf = np.zeros(len(res_base), dtype=np.complex64)
        res_opt = fft_manager.rfft(data, out=out_buf)

        self.assertIs(res_opt, out_buf)
        np.testing.assert_allclose(res_opt, res_base, rtol=1e-5)

    def test_rfft_no_copy(self):
        if fft_manager is None:
            self.skipTest("FFTManager not available")
        N = 2048
        data = np.random.random(N).astype(np.float64)

        # 1. Normal copy
        res_copy_1 = fft_manager.rfft(data)
        res_copy_2 = fft_manager.rfft(data)
        self.assertIsNot(res_copy_1, res_copy_2)

        # 2. No copy
        res_no_copy_1 = fft_manager.rfft(data, copy=False)
        res_no_copy_2 = fft_manager.rfft(data, copy=False)

        if HAS_PYFFTW:
            # Check that they are the same object (internal buffer)
            self.assertIs(res_no_copy_1, res_no_copy_2)

            # Verify that modifying one modifies the other (proof of shared memory)
            original_val = res_no_copy_1[0]
            res_no_copy_1[0] += 1
            self.assertEqual(res_no_copy_2[0], original_val + 1)
        else:
            # Fallback to numpy always returns copy
            pass

    def test_irfft_no_copy(self):
        if fft_manager is None:
            self.skipTest("FFTManager not available")
        N = 2048
        data = np.random.random(N).astype(np.float64)
        fft_data = fft_manager.rfft(data)

        # 1. Normal copy
        res_copy_1 = fft_manager.irfft(fft_data, n=N)
        res_copy_2 = fft_manager.irfft(fft_data, n=N)
        self.assertIsNot(res_copy_1, res_copy_2)

        # 2. No copy
        res_no_copy_1 = fft_manager.irfft(fft_data, n=N, copy=False)
        res_no_copy_2 = fft_manager.irfft(fft_data, n=N, copy=False)

        if HAS_PYFFTW:
            self.assertIs(res_no_copy_1, res_no_copy_2)

            # Verify values are correct (normalization happened)
            np.testing.assert_allclose(res_no_copy_1, data, rtol=1e-10, atol=1e-10)
        else:
            # Fallback to numpy always returns copy
            pass

    def test_irfft_correctness(self):
        if fft_manager is None:
            self.skipTest("FFTManager not available")
        N = 1024
        data = np.random.random(N).astype(np.float64)
        fft_data = fft_manager.rfft(data)
        recon = fft_manager.irfft(fft_data, n=N)
        np.testing.assert_allclose(recon, data, rtol=1e-5)

    def test_fallback_correctness(self):
        if fft_manager is None:
            self.skipTest("FFTManager not available")

        # We need to simulate HAS_PYFFTW = False
        with patch('src.core.fft_manager.HAS_PYFFTW', False):
            N = 1024
            data = np.random.random(N).astype(np.float64)

            # Should use numpy fallback
            res_base = fft_manager.rfft(data)
            recon = fft_manager.irfft(res_base, n=N)

            np.testing.assert_allclose(recon, data, rtol=1e-5)

            # Test copy=False (should still be a copy in fallback)
            res_nc = fft_manager.rfft(data, copy=False)
            res_nc_2 = fft_manager.rfft(data, copy=False)
            self.assertIsNot(res_nc, res_nc_2)

if __name__ == '__main__':
    unittest.main()
