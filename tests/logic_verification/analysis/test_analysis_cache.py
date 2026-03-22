import numpy as np

from src.core.analysis import get_cached_window, _get_butter_sos


def test_get_cached_window_basic_functionality():
    """Verify that get_cached_window returns the correct window shape and type."""
    # Test hann window
    nx = 128
    window = get_cached_window("hann", nx)
    assert isinstance(window, np.ndarray)
    assert window.shape == (nx,)
    assert window.dtype == np.float64

    # Check simple values (Hann window should be 0 at edges and 1 in middle)
    # The default fftbins=True means the window is asymmetric, so the exact center
    # may not be exactly 1.0, but it should be close.
    # Alternatively, test fftbins=False which is symmetric
    sym_window = get_cached_window("hann", nx, fftbins=False)
    assert sym_window.shape == (nx,)
    assert sym_window[0] == 0.0
    assert sym_window[-1] == 0.0

    # Test different dtype
    window_f32 = get_cached_window("hann", nx, dtype=np.float32)
    assert window_f32.dtype == np.float32


def test_get_cached_window_caching_behavior():
    """Verify that get_cached_window actually caches the results."""
    # Clear cache before testing to ensure clean state
    get_cached_window.cache_clear()

    # First call
    win1 = get_cached_window("hamming", 256)
    info1 = get_cached_window.cache_info()
    assert info1.misses >= 1

    # Second call with same parameters
    win2 = get_cached_window("hamming", 256)
    info2 = get_cached_window.cache_info()

    # Should be a cache hit
    assert info2.hits > info1.hits

    # Crucially, the returned objects should be identical in memory
    assert win1 is win2

    # Third call with different parameters
    win3 = get_cached_window("hamming", 256, fftbins=False)
    info3 = get_cached_window.cache_info()

    # Should be a cache miss because fftbins changed
    assert info3.misses > info2.misses
    assert win1 is not win3


def test_get_butter_sos_basic_functionality():
    """Verify that _get_butter_sos returns valid SOS coefficients."""
    # 4th order lowpass at 1kHz for 48kHz sample rate
    fs = 48000
    fc = 1000
    nyq = 0.5 * fs
    wn = fc / nyq

    sos = _get_butter_sos(4, wn, "lowpass", fs=None)  # scipy butter takes normalized Wn if fs=None

    # SOS array should be shape (N_sections, 6)
    # For a 4th order filter, we expect 2 sections of biquads
    assert isinstance(sos, np.ndarray)
    assert sos.shape == (2, 6)

    # Test with fs parameter
    sos_fs = _get_butter_sos(4, fc, "lowpass", fs=fs)
    assert sos_fs.shape == (2, 6)
    # They should be mathematically equivalent
    assert np.allclose(sos, sos_fs)


def test_get_butter_sos_caching_behavior():
    """Verify that _get_butter_sos caches the returned coefficients."""
    # Clear cache
    _get_butter_sos.cache_clear()

    # First call
    sos1 = _get_butter_sos(2, 0.1, "highpass")
    info1 = _get_butter_sos.cache_info()
    assert info1.misses >= 1

    # Second call with same params
    sos2 = _get_butter_sos(2, 0.1, "highpass")
    info2 = _get_butter_sos.cache_info()

    # Cache hit
    assert info2.hits > info1.hits

    # Same object in memory
    assert sos1 is sos2

    # Call with different parameter
    sos3 = _get_butter_sos(2, 0.2, "highpass")
    info3 = _get_butter_sos.cache_info()

    # Cache miss
    assert info3.misses > info2.misses
    assert sos1 is not sos3

    # Call with different type (but same Wn conceptually, though type differs)
    # e.g., lowpass vs highpass
    sos4 = _get_butter_sos(2, 0.1, "lowpass")
    assert sos1 is not sos4
