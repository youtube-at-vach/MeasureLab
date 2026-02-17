import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))
import numpy as np
from src.core.fft_manager import fft_manager, HAS_PYFFTW

def test_rfft_out_param():
    N = 1024
    data = np.random.random(N).astype(np.float64)

    # Baseline
    res_base = fft_manager.rfft(data)

    # With out
    out_buf = np.zeros_like(res_base)
    res_opt = fft_manager.rfft(data, out=out_buf)

    assert res_opt is out_buf
    np.testing.assert_allclose(res_opt, res_base, rtol=1e-10)

def test_irfft_out_param():
    N = 1024
    data = np.random.random(N).astype(np.float64)

    # Get FFT first
    fft_data = fft_manager.rfft(data)

    # Baseline irfft
    res_base = fft_manager.irfft(fft_data, n=N)

    # With out
    out_buf = np.zeros_like(res_base)
    res_opt = fft_manager.irfft(fft_data, n=N, out=out_buf)

    assert res_opt is out_buf
    np.testing.assert_allclose(res_opt, res_base, rtol=1e-10)

def test_rfft_out_param_float32():
    N = 1024
    data = np.random.random(N).astype(np.float32)

    # Baseline
    res_base = fft_manager.rfft(data)

    # With out
    # Output of rfft for float32 input is complex64
    out_buf = np.zeros(len(res_base), dtype=np.complex64)
    res_opt = fft_manager.rfft(data, out=out_buf)

    assert res_opt is out_buf
    np.testing.assert_allclose(res_opt, res_base, rtol=1e-5)

def test_rfft_no_copy():
    N = 2048
    data = np.random.random(N).astype(np.float64)

    # 1. Normal copy
    res_copy_1 = fft_manager.rfft(data)
    res_copy_2 = fft_manager.rfft(data)
    assert res_copy_1 is not res_copy_2

    # 2. No copy
    res_no_copy_1 = fft_manager.rfft(data, copy=False)
    res_no_copy_2 = fft_manager.rfft(data, copy=False)

    if HAS_PYFFTW:
        # Check that they are the same object (internal buffer)
        assert res_no_copy_1 is res_no_copy_2

        # Verify that modifying one modifies the other (proof of shared memory)
        original_val = res_no_copy_1[0]
        res_no_copy_1[0] += 1
        assert res_no_copy_2[0] == original_val + 1
    else:
        # Fallback to numpy always returns copy
        pass

def test_irfft_no_copy():
    N = 2048
    data = np.random.random(N).astype(np.float64)
    fft_data = fft_manager.rfft(data)

    # 1. Normal copy
    res_copy_1 = fft_manager.irfft(fft_data, n=N)
    res_copy_2 = fft_manager.irfft(fft_data, n=N)
    assert res_copy_1 is not res_copy_2

    # 2. No copy
    res_no_copy_1 = fft_manager.irfft(fft_data, n=N, copy=False)
    res_no_copy_2 = fft_manager.irfft(fft_data, n=N, copy=False)

    if HAS_PYFFTW:
        assert res_no_copy_1 is res_no_copy_2

        # Verify values are correct (normalization happened)
        np.testing.assert_allclose(res_no_copy_1, data, rtol=1e-10, atol=1e-10)
    else:
        # Fallback to numpy always returns copy
        pass

def test_irfft_correctness():
    N = 1024
    data = np.random.random(N).astype(np.float64)
    fft_data = fft_manager.rfft(data)
    recon = fft_manager.irfft(fft_data, n=N)
    np.testing.assert_allclose(recon, data, rtol=1e-5)

def test_fallback_correctness(monkeypatch):
    import src.core.fft_manager
    monkeypatch.setattr(src.core.fft_manager, "HAS_PYFFTW", False)

    N = 1024
    data = np.random.random(N).astype(np.float64)

    # Should use numpy fallback
    res_base = fft_manager.rfft(data)
    recon = fft_manager.irfft(res_base, n=N)

    np.testing.assert_allclose(recon, data, rtol=1e-5)

    # Test copy=False (should still be a copy in fallback)
    res_nc = fft_manager.rfft(data, copy=False)
    res_nc_2 = fft_manager.rfft(data, copy=False)
    assert res_nc is not res_nc_2
