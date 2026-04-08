from unittest.mock import patch, mock_open, MagicMock

# In offline environments where pipx inject is impossible and core dependencies (e.g., numpy, PyQt6) are missing, logic-only functions can be unit-tested by wrapping imports within a patch.dict("sys.modules", mock_dict) context manager at the top of the test file to isolate the function under test and bypass ImportError during test discovery.
mock_dict = {
    'numpy': MagicMock(),
    'pyqtgraph': MagicMock(),
    'PyQt6': MagicMock(),
    'PyQt6.QtCore': MagicMock(),
    'PyQt6.QtWidgets': MagicMock(),
    'src.core.analysis': MagicMock(),
    'src.core.audio_engine': MagicMock(),
    'src.core.fft_manager': MagicMock(),
    'src.core.localization': MagicMock(),
    'src.measurement_modules.base': MagicMock(),
    'winreg': MagicMock(),
}

with patch.dict('sys.modules', mock_dict):
    from src.gui.widgets.processor_benchmark import get_cpu_name
    import winreg

@patch.dict('sys.modules', {'winreg': winreg})
@patch('sys.platform', 'win32')
def test_get_cpu_name_win32():
    with patch.object(winreg, 'OpenKey'):
        with patch.object(winreg, 'QueryValueEx') as mock_query:
            mock_query.return_value = ('Intel(R) Core(TM) i9-9900K CPU @ 3.60GHz   ', None)
            assert get_cpu_name() == 'Intel(R) Core(TM) i9-9900K CPU @ 3.60GHz'

@patch.dict('sys.modules', {'winreg': winreg})
@patch('sys.platform', 'win32')
def test_get_cpu_name_win32_exception():
    with patch.object(winreg, 'OpenKey', side_effect=Exception('Error')):
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
