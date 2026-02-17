import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))

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

        # Make sure src.core.fft_manager is not in sys.modules
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

if __name__ == '__main__':
    unittest.main()
