import sys
from unittest.mock import MagicMock, patch

# 1. Setup Mocks for heavy dependencies
mock_np = MagicMock()
mock_scipy = MagicMock()
mock_scipy_signal = MagicMock()
mock_scipy_optimize = MagicMock()
mock_fft_manager = MagicMock()

# Configure mocks
mock_scipy.signal = mock_scipy_signal
mock_scipy.optimize = mock_scipy_optimize

# Mock methods needed for import
mock_scipy_signal.butter = MagicMock()
mock_scipy_signal.get_window = MagicMock()
mock_scipy_signal.sosfiltfilt = MagicMock()

# Mock numpy basics
mock_np.ndarray = MagicMock
mock_np.float64 = float
mock_np.arange = MagicMock(return_value=MagicMock())
mock_np.sqrt = MagicMock()

# Setup sys.modules patches
module_patches = {
    'numpy': mock_np,
    'scipy': mock_scipy,
    'scipy.signal': mock_scipy_signal,
    'scipy.optimize': mock_scipy_optimize,
    'src.core.fft_manager': mock_fft_manager,
}

# Apply patches
patcher = patch.dict(sys.modules, module_patches)
patcher.start()

# Import module under test
try:
    from src.core.analysis import _get_butter_sos
except ImportError:
    # Fallback if something else is missing, but unexpected given patches
    patcher.stop()
    raise

def teardown_module():
    patcher.stop()

def test_butter_sos_basic_shape():
    """Test basic functionality and output shape of _get_butter_sos."""
    # Setup mock return
    expected_shape = (2, 6)
    mock_sos = MagicMock()
    mock_sos.shape = expected_shape
    # Make it look like an ndarray
    mock_sos.__class__ = mock_np.ndarray

    mock_scipy_signal.butter.return_value = mock_sos

    # Call function
    sos = _get_butter_sos(4, 0.1, 'lowpass')

    # Verify return
    assert sos is mock_sos
    assert sos.shape == expected_shape
    assert isinstance(sos, mock_np.ndarray)

def test_butter_sos_caching():
    """Test caching behavior of _get_butter_sos using lru_cache."""
    _get_butter_sos.cache_clear()
    mock_scipy_signal.butter.reset_mock()

    # First call
    _get_butter_sos(4, 0.1, 'lowpass')
    assert mock_scipy_signal.butter.call_count == 1

    # Second call (same args)
    _get_butter_sos(4, 0.1, 'lowpass')
    assert mock_scipy_signal.butter.call_count == 1

    # Third call (diff args)
    _get_butter_sos(4, 0.2, 'lowpass')
    assert mock_scipy_signal.butter.call_count == 2

    # Cache info
    info = _get_butter_sos.cache_info()
    assert info.hits >= 1
    assert info.misses >= 2

def test_butter_sos_arguments():
    """Test argument passing to scipy.signal.butter."""
    _get_butter_sos.cache_clear()
    mock_scipy_signal.butter.reset_mock()

    _get_butter_sos(8, (0.1, 0.2), 'bandpass', fs=48000)

    mock_scipy_signal.butter.assert_called_with(8, (0.1, 0.2), btype='bandpass', fs=48000, output='sos')

def test_butter_sos_odd_order():
    """Test odd order calls butter correctly."""
    _get_butter_sos.cache_clear()
    mock_scipy_signal.butter.reset_mock()

    _get_butter_sos(3, 0.1, 'lowpass')

    mock_scipy_signal.butter.assert_called_with(3, 0.1, btype='lowpass', fs=None, output='sos')
