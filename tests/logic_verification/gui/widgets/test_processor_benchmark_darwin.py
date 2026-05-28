from unittest.mock import MagicMock, patch

mock_dict = {
    "numpy": MagicMock(),
    "pyqtgraph": MagicMock(),
    "PyQt6.QtCore": MagicMock(),
    "PyQt6.QtWidgets": MagicMock(),
    "src.core.analysis": MagicMock(),
    "src.core.audio_engine": MagicMock(),
    "src.core.fft_manager": MagicMock(),
    "src.core.localization": MagicMock(),
    "src.measurement_modules.base": MagicMock(),
}

with patch.dict("sys.modules", mock_dict):
    from src.gui.widgets.processor_benchmark import get_cpu_name


def test_get_cpu_name_darwin_exception():
    """Test that get_cpu_name correctly handles exceptions when sysctlbyname fails on darwin."""
    with patch("sys.platform", "darwin"):
        with patch("ctypes.util.find_library", return_value="c"), patch("ctypes.cdll.LoadLibrary") as mock_load:
            # Simulate failure to get size
            mock_load.return_value.sysctlbyname.return_value = -1
            result = get_cpu_name()
            assert result is None


def test_get_cpu_name_darwin_success():
    """Test that get_cpu_name returns the correct name when sysctlbyname succeeds."""
    with patch("sys.platform", "darwin"):
        with (
            patch("ctypes.util.find_library", return_value="c"),
            patch("ctypes.cdll.LoadLibrary") as mock_load,
            patch("ctypes.create_string_buffer") as mock_buffer,
        ):
            # Simulate successful sysctlbyname calls
            mock_load.return_value.sysctlbyname.return_value = 0

            # Setup the mocked buffer to return our test string
            mock_buf_instance = MagicMock()
            mock_buf_instance.value = b"Apple M1 Pro"
            mock_buffer.return_value = mock_buf_instance

            result = get_cpu_name()
            assert result == "Apple M1 Pro"
