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


def test_get_cpu_name_linux_exception():
    """Test that get_cpu_name correctly handles exceptions when reading /proc/cpuinfo fails on linux."""
    with patch("sys.platform", "linux"), patch("builtins.open", side_effect=OSError("Mocked Exception")):
        result = get_cpu_name()

        assert result is None
