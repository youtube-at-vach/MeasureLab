from unittest.mock import patch, MagicMock

mock_dict = {
    "numpy": MagicMock(),
    "pyqtgraph": MagicMock(),
    "PyQt6": MagicMock(),
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
    with patch("sys.platform", "win32"):
        mock_winreg = MagicMock()
        mock_winreg.OpenKey.side_effect = Exception("Test Exception")
        with patch.dict("sys.modules", {"winreg": mock_winreg}):
            assert get_cpu_name() is None
