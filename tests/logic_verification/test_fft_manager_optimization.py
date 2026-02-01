import numpy as np
from src.core.fft_manager import fft_manager

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
