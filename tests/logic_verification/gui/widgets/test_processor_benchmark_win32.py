from unittest.mock import MagicMock, patch

# Mock dependencies to isolate get_cpu_name
mock_dict = {
    "numpy": MagicMock(),
    "pyqtgraph": MagicMock(),
    "PyQt6.QtCore": MagicMock(),
    "PyQt6.QtWidgets": MagicMock(),
    "src.core.analysis": MagicMock(),
    "src.core.audio_engine": MagicMock(),
    "src.core.fft_manager": MagicMock(),
    "src.core.localization": MagicMock(),
    "src.measurement_modules.base": MagicMock()
}

with patch.dict("sys.modules", mock_dict):
    from src.gui.widgets.processor_benchmark import get_cpu_name

def test_get_cpu_name_win32_exception():
    """Test that get_cpu_name correctly handles exceptions when winreg fails on win32."""
    mock_winreg = MagicMock()
    mock_winreg.OpenKey.side_effect = OSError("Mocked Exception")

    with patch("sys.platform", "win32"), \
         patch.dict("sys.modules", {"winreg": mock_winreg}):

        result = get_cpu_name()

        assert result is None
