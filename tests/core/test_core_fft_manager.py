import numpy as np
import pytest
from src.core.fft_manager import FFTManager

def test_fft_manager_rfft_irfft():
    # Setup
    manager = FFTManager()

    # Create test data
    t = np.linspace(0, 1, 1024, endpoint=False)
    # 10 Hz sine wave
    data = np.sin(2 * np.pi * 10 * t)

    # Test rfft
    fft_result = manager.rfft(data)
    assert fft_result.shape == (513,)
    assert fft_result.dtype == np.complex128

    # Check frequency peak
    freqs = manager.rfftfreq(1024, 1/1024)
    peak_idx = np.argmax(np.abs(fft_result))
    assert freqs[peak_idx] == 10.0

    # Test irfft
    reconstructed = manager.irfft(fft_result, n=1024)
    assert reconstructed.shape == (1024,)
    assert reconstructed.dtype == np.float64

    # Compare with original data
    np.testing.assert_allclose(data, reconstructed, atol=1e-10)

def test_fft_manager_out_parameter():
    manager = FFTManager()
    data = np.random.randn(512).astype(np.float64)

    # Pre-allocate output buffer
    out_fft = np.empty(257, dtype=np.complex128)

    # Test rfft with out
    result1 = manager.rfft(data, out=out_fft)
    assert result1 is out_fft
    assert np.allclose(result1, np.fft.rfft(data))

    # Pre-allocate output buffer for irfft
    out_ifft = np.empty(512, dtype=np.float64)

    # Test irfft with out
    result2 = manager.irfft(out_fft, n=512, out=out_ifft)
    assert result2 is out_ifft
    np.testing.assert_allclose(data, result2, atol=1e-10)

def test_fft_manager_dtypes():
    manager = FFTManager()

    # Test float32
    data32 = np.random.randn(256).astype(np.float32)
    fft32 = manager.rfft(data32)
    assert fft32.dtype == np.complex64

    ifft32 = manager.irfft(fft32, n=256)
    assert ifft32.dtype == np.float32
    np.testing.assert_allclose(data32, ifft32, atol=1e-5)

    # Test float64
    data64 = np.random.randn(256).astype(np.float64)
    fft64 = manager.rfft(data64)
    assert fft64.dtype == np.complex128

    ifft64 = manager.irfft(fft64, n=256)
    assert ifft64.dtype == np.float64
    np.testing.assert_allclose(data64, ifft64, atol=1e-10)

def test_fft_manager_windows():
    manager = FFTManager()
    windows = manager.get_available_windows()
    assert "hann" in windows
    assert "blackmanharris" in windows
    assert isinstance(windows, list)

def test_get_dpss_windows():
    from src.core.fft_manager import get_dpss_windows

    # Test getting DPSS windows
    windows = get_dpss_windows(N=1024, NW=3)

    # Kmax defaults to 2*NW - 1 = 5
    assert windows.shape == (5, 1024)
    assert windows.dtype == np.float64

    # Test caching - should return the exact same object
    windows_cached = get_dpss_windows(N=1024, NW=3)
    assert windows is windows_cached

def test_warmup(mocker):
    manager = FFTManager()

    # Use small sizes for fast test
    mocker.patch("src.core.fft_manager.WARMUP_SIZES", [256, 512])
    mocker.patch("src.core.fft_manager.MEDIUM_SIZES", [1024])
    mocker.patch("src.core.fft_manager.HUGE_SIZES", [2048])

    callback_calls = []
    def callback(msg):
        callback_calls.append(msg)

    manager.warmup(callback=callback, force=True, exhaustive=True, include_huge=True)

    assert len(callback_calls) > 0

    # Should have plans for float32 and float64
    # Size 256
    assert (256, "float32", "FFTW_FORWARD") in manager._plans
    assert (256, "float64", "FFTW_FORWARD") in manager._plans
    # Size 512
    assert (512, "float32", "FFTW_FORWARD") in manager._plans
    assert (512, "float64", "FFTW_FORWARD") in manager._plans

def test_save_load_wisdom(tmp_path):
    manager = FFTManager()

    # Overwrite wisdom_path for testing
    manager.wisdom_path = tmp_path / "wisdom.json"

    # Empty manager should have no wisdom
    assert not manager.wisdom_path.exists()

    # Force a plan creation with MEASURE to generate wisdom
    manager.get_plan(256, "float32", flags=("FFTW_MEASURE",))
    manager.save_wisdom()

    assert manager.wisdom_path.exists()

    # Create new manager with same path and load
    new_manager = FFTManager()
    new_manager.wisdom_path = tmp_path / "wisdom.json"
    new_manager.load_wisdom()

def test_fallback_numpy_fft(mocker):
    mocker.patch("src.core.fft_manager.HAS_PYFFTW", False)

    manager = FFTManager()

    t = np.linspace(0, 1, 1024, endpoint=False)
    data = np.sin(2 * np.pi * 10 * t)

    # Since HAS_PYFFTW is False, it should use np.fft
    fft_result = manager.rfft(data)
    assert fft_result.shape == (513,)

    # Test with out buffer
    out_buf = np.empty(513, dtype=np.complex128)
    manager.rfft(data, out=out_buf)

    # Test irfft
    reconstructed = manager.irfft(fft_result, n=1024)
    assert reconstructed.shape == (1024,)
    np.testing.assert_allclose(data, reconstructed, atol=1e-10)

    # Test irfft with out buffer
    out_buf2 = np.empty(1024, dtype=np.float64)
    manager.irfft(fft_result, n=1024, out=out_buf2)

    # Test get_plan and warmup should gracefully return/do nothing
    assert manager.get_plan(256) is None
    manager.warmup() # should not raise exception

def test_dtype_str_conversion():
    manager = FFTManager()

    assert manager._get_dtype_str(np.dtype('float32')) == 'float32'
    assert manager._get_dtype_str(np.dtype('float64')) == 'float64'
    assert manager._get_dtype_str(np.dtype('int32')) == 'float64' # fallback

def test_rfft_irfft_copy_parameter():
    manager = FFTManager()
    data = np.random.randn(256).astype(np.float64)

    # rfft copy=False
    fft_result_no_copy = manager.rfft(data, copy=False)
    assert fft_result_no_copy.shape == (129,)

    # irfft copy=False
    ifft_result_no_copy = manager.irfft(fft_result_no_copy, n=256, copy=False)
    assert ifft_result_no_copy.shape == (256,)

def test_rfft_irfft_invalid_length():
    manager = FFTManager()
    data = np.random.randn(256).astype(np.float64)
    fft_data = manager.rfft(data)

    # Try irfft with invalid length data (e.g. padding/truncating)
    # This should trigger the fallback to np.fft.irfft internally
    truncated_fft = fft_data[:-1]
    result = manager.irfft(truncated_fft, n=256)
    assert result.shape == (256,)

def test_upgrade_plan(mocker):
    manager = FFTManager()
    # Mock to ensure we can track calls
    spy = mocker.spy(manager, "_create_plan")

    # First get ESTIMATE plan
    manager.get_plan(256, "float32", flags=("FFTW_ESTIMATE",))
    assert spy.call_count == 1

    # Then get MEASURE plan, which should trigger upgrade
    manager.get_plan(256, "float32", flags=("FFTW_MEASURE",))
    assert spy.call_count == 2
