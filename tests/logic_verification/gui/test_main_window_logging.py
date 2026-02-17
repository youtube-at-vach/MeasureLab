import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))
import sys
import unittest
from unittest.mock import MagicMock, patch

# -------------------------------------------------------------------------
# MOCKING DEPENDENCIES
# -------------------------------------------------------------------------

class MockQMainWindow:
    def __init__(self, *args, **kwargs):
        pass
    def setWindowTitle(self, t): pass
    def resize(self, w, h): pass
    def setCentralWidget(self, w): pass
    def setStatusBar(self, b): pass
    def layout(self): return MagicMock()

qt_widgets = MagicMock()
qt_widgets.QMainWindow = MockQMainWindow
qt_widgets.QApplication.instance.return_value = MagicMock()

class MockQWidget(MagicMock):
    def __init__(self, *args, **kwargs):
        super().__init__()

    def _get_child_mock(self, **kwargs):
        return MagicMock(**kwargs)

class MockLayout(MagicMock):
    def __init__(self, *args, **kwargs):
        super().__init__()
    def addWidget(self, *args): pass
    def setContentsMargins(self, *args): pass
    def count(self): return 0

qt_widgets.QWidget = MockQWidget
qt_widgets.QHBoxLayout = MockLayout
qt_widgets.QVBoxLayout = MockLayout
qt_widgets.QListWidget = MagicMock
qt_widgets.QStackedWidget = MagicMock
qt_widgets.QStatusBar = MagicMock

class MockQLabel(MagicMock):
    def __init__(self, *args, **kwargs):
        super().__init__()

qt_widgets.QLabel = MockQLabel
qt_widgets.QComboBox = MagicMock

mock_audio_engine = MagicMock()
mock_config_manager = MagicMock()
mock_localization = MagicMock()
mock_localization.tr.side_effect = lambda x: str(x)
mock_localization.get_manager.return_value = MagicMock()

mock_theme_manager = MagicMock()
mock_detachable = MagicMock()

class TestMainWindowLogging(unittest.TestCase):
    def test_logging_on_missing_device(self):
        """
        Verify that logger.warning is called when a saved device is not found.
        """
        # Reset mocks
        mock_audio_engine.reset_mock()
        mock_config_manager.reset_mock()

        # Setup mock behavior
        # Config has saved devices
        # mock_config_manager is the module, so we target the class ConfigManager inside it
        mock_config_manager.ConfigManager.return_value.get_audio_config.return_value = {
            "input_device": "Saved Mic",
            "input_hostapi": "Core Audio",
            "output_device": "Saved Speaker",
            "output_hostapi": "Core Audio"
        }

        # Audio Engine lists devices, but NOT the saved ones
        # mock_audio_engine is the module, target AudioEngine class
        mock_audio_engine.AudioEngine.return_value.list_devices.return_value = [
            {"name": "Other Mic", "hostapi_name": "Core Audio", "max_input_channels": 2, "max_output_channels": 0},
            {"name": "Other Speaker", "hostapi_name": "Core Audio", "max_input_channels": 0, "max_output_channels": 2},
        ]

        # Patch modules
        modules_to_patch = {
            "PyQt6": MagicMock(),
            "PyQt6.QtCore": MagicMock(),
            "PyQt6.QtWidgets": qt_widgets,
            "PyQt6.QtGui": MagicMock(),
            "src.core.audio_engine": mock_audio_engine,
            "src.core.config_manager": mock_config_manager,
            "src.core.localization": mock_localization,
            "src.core.theme_manager": mock_theme_manager,
            "src.gui.widgets.detachable_wrapper": mock_detachable,
        }

        with patch.dict(sys.modules, modules_to_patch):
            # Ensure fresh import
            if "src.gui.main_window" in sys.modules:
                del sys.modules["src.gui.main_window"]

            # Patch logging.getLogger to return our spy logger
            # Note: logging is imported in MainWindow, so we should patch it where it is used or imported.
            # But since we are reloading MainWindow, patching 'logging.getLogger' globally should work
            # because 'import logging' in MainWindow will use the already loaded logging module,
            # and we are patching getLogger on it.
            with patch("logging.getLogger") as mock_get_logger:
                spy_logger = MagicMock()
                mock_get_logger.return_value = spy_logger

                from src.gui.main_window import MainWindow

                # Instantiate MainWindow
                MainWindow()

                # Verify logger.warning was called for input and output
                # We expect 2 calls: one for input, one for output

                # Check for input warning
                spy_logger.warning.assert_any_call("Saved input device 'Saved Mic' not found, using default.")

                # Check for output warning
                spy_logger.warning.assert_any_call("Saved output device 'Saved Speaker' not found, using default.")

if __name__ == "__main__":
    unittest.main()
