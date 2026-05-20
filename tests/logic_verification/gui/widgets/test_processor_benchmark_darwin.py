from unittest.mock import MagicMock, patch
import subprocess

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

def test_get_cpu_name_darwin_exception():
    """Test that get_cpu_name correctly handles exceptions when sysctl fails on darwin."""
    with patch("sys.platform", "darwin"), \
         patch("subprocess.check_output", side_effect=subprocess.CalledProcessError(1, "sysctl")):

        result = get_cpu_name()

        assert result is None
