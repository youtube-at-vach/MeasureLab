import sys
import unittest
from unittest.mock import MagicMock, patch

# Mock PyQt6
qt_widgets = MagicMock()
qt_core = MagicMock()

# Mock specific classes
class MockQMainWindow:
    def __init__(self, *args, **kwargs):
        pass
    def setWindowTitle(self, t): pass
    def resize(self, w, h): pass
    def setCentralWidget(self, w): pass
    def setStatusBar(self, b): pass
    def addPermanentWidget(self, w): pass
    def layout(self): return MagicMock()

qt_widgets.QMainWindow = MockQMainWindow
qt_widgets.QWidget = MagicMock
qt_widgets.QHBoxLayout = MagicMock()
qt_widgets.QVBoxLayout = MagicMock()
qt_widgets.QListWidget = MagicMock()
qt_widgets.QStackedWidget = MagicMock()
qt_widgets.QStatusBar = MagicMock()
qt_widgets.QLabel = MagicMock()
qt_widgets.QComboBox = MagicMock()
qt_widgets.QApplication = MagicMock()
qt_core.QTimer = MagicMock()

# Mock src.core dependencies
mock_audio_engine_cls = MagicMock()
mock_audio_engine = mock_audio_engine_cls.return_value
# Setup default return values for AudioEngine
mock_audio_engine.list_devices.return_value = []
mock_audio_engine.get_status.return_value = {
    "active": False,
    "input_channels": "stereo",
    "output_channels": "stereo",
    "sample_rate": 48000,
    "cpu_load": 0.0,
    "active_clients": 0,
    "offline_mode": False
}
mock_audio_engine.offline_mode = False
mock_audio_engine.loopback = False
mock_audio_engine.mute_output = False

mock_config_manager_cls = MagicMock()
mock_config_manager = mock_config_manager_cls.return_value
# Setup ConfigManager defaults
mock_config_manager.get_language.return_value = "en"
mock_config_manager.get_theme.return_value = "dark"
mock_config_manager.get_audio_config.return_value = {}
mock_config_manager.get_pipewire_jack_resident.return_value = False

mock_localization = MagicMock()
mock_localization.tr = lambda x: x # Simple pass-through for translation
mock_localization.get_manager.return_value = MagicMock()

mock_theme_manager_cls = MagicMock()
mock_theme_manager = mock_theme_manager_cls.return_value

mock_welcome_cls = MagicMock()

class TestMainWindowInitRefactor(unittest.TestCase):
    def test_main_window_initialization(self):
        modules_to_patch = {
            "PyQt6": MagicMock(),
            "PyQt6.QtCore": qt_core,
            "PyQt6.QtWidgets": qt_widgets,
            "src.core.audio_engine": MagicMock(AudioEngine=mock_audio_engine_cls),
            "src.core.config_manager": MagicMock(ConfigManager=mock_config_manager_cls),
            "src.core.localization": mock_localization,
            "src.core.theme_manager": MagicMock(ThemeManager=mock_theme_manager_cls),
            "src.gui.widgets.welcome": MagicMock(WelcomeWidget=mock_welcome_cls),
            # DetachableWrapper is imported in main_window.py
            "src.gui.widgets.detachable_wrapper": MagicMock(),
        }

        # Capture keys before
        before_keys = set(sys.modules.keys())

        with patch.dict(sys.modules, modules_to_patch):
            if "src.gui.main_window" in sys.modules:
                del sys.modules["src.gui.main_window"]

            from src.gui.main_window import MainWindow

            # Instantiate MainWindow
            _ = MainWindow()

            # Verify basic calls
            self.assertTrue(mock_config_manager_cls.called)
            self.assertTrue(mock_audio_engine_cls.called)

            # Check if UI elements were created (via our mocks)
            self.assertTrue(qt_widgets.QListWidget.called)
            self.assertTrue(qt_widgets.QStackedWidget.called)

            # Check if status timer started
            self.assertTrue(qt_core.QTimer.return_value.start.called)

            # Check if WelcomeWidget was initialized
            self.assertTrue(mock_welcome_cls.called)

        # Cleanup newly loaded modules
        after_keys = set(sys.modules.keys())
        for key in (after_keys - before_keys):
            if key.startswith("src.") or key.startswith("PyQt6"):
                del sys.modules[key]

if __name__ == "__main__":
    unittest.main()
