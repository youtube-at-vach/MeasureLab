from unittest.mock import patch, mock_open, MagicMock

# The function get_cpu_name doesn't use the classes/variables from the module that require numpy/pyqt6,
# so if we need to isolate it, we can patch the whole module to prevent ImportError, but doing so with
# patch.dict globally pollutes the test environment and breaks other tests if they run afterwards.
# Given that pytest is running in an environment where all dependencies are installed (as the full test suite passes),
# we don't strictly need to mock `numpy` and `PyQt6` here, as the module should import cleanly.
from src.gui.widgets.processor_benchmark import get_cpu_name

@patch('sys.platform', 'win32')
def test_get_cpu_name_win32():
    # Use create=True because winreg is imported locally inside get_cpu_name when platform is win32,
    # meaning it might not exist in the sys.modules before calling it or patching it correctly.
    with patch.dict('sys.modules', {'winreg': MagicMock()}) as mock_modules:
        mock_winreg = mock_modules['winreg']
        mock_winreg.OpenKey.return_value = MagicMock()
        mock_winreg.QueryValueEx.return_value = ('Intel(R) Core(TM) i9-9900K CPU @ 3.60GHz   ', None)
        assert get_cpu_name() == 'Intel(R) Core(TM) i9-9900K CPU @ 3.60GHz'

@patch('sys.platform', 'win32')
def test_get_cpu_name_win32_exception():
    with patch.dict('sys.modules', {'winreg': MagicMock()}) as mock_modules:
        mock_winreg = mock_modules['winreg']
        mock_winreg.OpenKey.side_effect = Exception('Error')
        assert get_cpu_name() is None

@patch('sys.platform', 'linux')
@patch('builtins.open', new_callable=mock_open, read_data="processor\t: 0\nmodel name\t: AMD Ryzen 9 5900X 12-Core Processor\n")
def test_get_cpu_name_linux(mock_file):
    assert get_cpu_name() == 'AMD Ryzen 9 5900X 12-Core Processor'

@patch('sys.platform', 'linux')
@patch('builtins.open', side_effect=Exception('Error'))
def test_get_cpu_name_linux_exception(mock_file):
    assert get_cpu_name() is None

@patch('sys.platform', 'darwin')
@patch('subprocess.check_output')
def test_get_cpu_name_darwin(mock_subprocess):
    mock_subprocess.return_value = b'Apple M1 Max\n'
    assert get_cpu_name() == 'Apple M1 Max'

@patch('sys.platform', 'darwin')
@patch('subprocess.check_output', side_effect=Exception('Error'))
def test_get_cpu_name_darwin_exception(mock_subprocess):
    assert get_cpu_name() is None

@patch('sys.platform', 'unknown')
def test_get_cpu_name_unknown():
    assert get_cpu_name() is None
