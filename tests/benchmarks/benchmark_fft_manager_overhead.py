import sys
import timeit
import unittest.mock
import numpy as np
import os

# Set path to allow imports from src
sys.path.append(os.getcwd())

# Mock pyfftw before importing fft_manager
mock_pyfftw = unittest.mock.MagicMock()
mock_pyfftw.empty_aligned.side_effect = lambda n, dtype: np.zeros(n, dtype=dtype)
mock_pyfftw.config.NUM_THREADS = 1

# Mock FFTW object to be callable and fast
class MockFFTW:
    def __init__(self, *args, **kwargs):
        pass
    def __call__(self):
        pass

mock_pyfftw.FFTW = MockFFTW

# Patch sys.modules so import pyfftw works
sys.modules['pyfftw'] = mock_pyfftw

# Now import fft_manager
from src.core import fft_manager  # noqa: E402

# Force HAS_PYFFTW to True (it should be True if import succeeded, which it did via mock)
# But strictly speaking, the module checks ImportError. Since we put it in sys.modules, it won't raise ImportError.
if not fft_manager.HAS_PYFFTW:
    print("WARNING: HAS_PYFFTW is False, forcing True")
    fft_manager.HAS_PYFFTW = True

# Re-initialize the global instance to use the mocked pyfftw
fft_manager.fft_manager = fft_manager.FFTManager()
fm = fft_manager.fft_manager

def benchmark():
    size = 1024
    data = np.random.rand(size).astype(np.float64)
    # Using a large number of iterations to measure overhead
    iterations = 100000

    # Pre-warmup to ensure plan is created
    fm.rfft(data)

    # Measure
    # We pass copy=False to minimize array copying overhead and focus on lookup overhead
    t = timeit.timeit(lambda: fm.rfft(data, copy=False), number=iterations)

    print(f"Time for {iterations} rfft calls (overhead only): {t:.4f} s")
    print(f"Time per call: {t/iterations*1e6:.2f} us")

if __name__ == "__main__":
    benchmark()
