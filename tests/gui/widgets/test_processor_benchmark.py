from unittest.mock import patch, MagicMock
import sys

# Mock dependencies to prevent ModuleNotFoundError
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
    'src.measurement_modules.base': MagicMock()
}

with patch.dict('sys.modules', mock_dict):
    from src.gui.widgets.processor_benchmark import get_cpu_name

def test_get_cpu_name_darwin_error_handling():
    with patch.object(sys, 'platform', 'darwin'):
        with patch('subprocess.check_output', side_effect=Exception("Command failed")):
            assert get_cpu_name() is None
