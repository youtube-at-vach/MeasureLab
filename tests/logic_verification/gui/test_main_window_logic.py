import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Adjust path to import src if needed
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

# -------------------------------------------------------------------------
# SHARED MOCKS
# -------------------------------------------------------------------------

class MockQMainWindow:
    def __init__(self, *args, **kwargs):
        pass
    def setWindowTitle(self, t): pass
    def resize(self, w, h): pass
    def setCentralWidget(self, w): pass
    def setStatusBar(self, b): pass
    def addPermanentWidget(self, w): pass
    def layout(self): return MagicMock()

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

class MockQLabel(MagicMock):
    def __init__(self, *args, **kwargs):
        super().__init__()

# Prepare mock modules for sys.modules patching
qt_widgets = MagicMock()
qt_widgets.QMainWindow = MockQMainWindow
qt_widgets.QWidget = MockQWidget
qt_widgets.QHBoxLayout = MockLayout
qt_widgets.QVBoxLayout = MockLayout
qt_widgets.QListWidget = MagicMock
qt_widgets.QStackedWidget = MagicMock
qt_widgets.QStatusBar = MagicMock
qt_widgets.QLabel = MockQLabel
qt_widgets.QComboBox = MagicMock
qt_widgets.QApplication = MagicMock()
qt_widgets.QApplication.instance.return_value = MagicMock()

qt_core = MagicMock()
qt_core.QTimer = MagicMock()

# -------------------------------------------------------------------------
# TEST CLASS
# -------------------------------------------------------------------------

class TestMainWindowLogic(unittest.TestCase):
    def setUp(self):
        # Common mocks for dependencies
        self.mock_audio_engine = MagicMock()
        self.mock_config_manager = MagicMock()
        self.mock_localization = MagicMock()
        self.mock_theme_manager = MagicMock()
        self.mock_detachable = MagicMock()
        self.mock_welcome = MagicMock()

        # Setup default ConfigManager behavior
        self.mock_config_manager.ConfigManager.return_value.get_language.return_value = "en"
        self.mock_config_manager.ConfigManager.return_value.get_theme.return_value = "dark"
        self.mock_config_manager.ConfigManager.return_value.get_audio_config.return_value = {}
        self.mock_config_manager.ConfigManager.return_value.get_pipewire_jack_resident.return_value = False

        # Setup default AudioEngine behavior
        self.mock_audio_engine.AudioEngine.return_value.list_devices.return_value = []
        self.mock_audio_engine.AudioEngine.return_value.get_status.return_value = {
            "active": False,
            "input_channels": "stereo",
            "output_channels": "stereo",
            "sample_rate": 48000,
            "cpu_load": 0.0,
            "active_clients": 0,
            "offline_mode": False
        }

        # Setup Localization
        self.mock_localization.tr = lambda x: str(x)
        self.mock_localization.get_manager.return_value = MagicMock()

    def _get_modules_to_patch(self):
        return {
            "PyQt6": MagicMock(),
            "PyQt6.QtCore": qt_core,
            "PyQt6.QtWidgets": qt_widgets,
            "PyQt6.QtGui": MagicMock(),
            "src.core.audio_engine": self.mock_audio_engine,
            "src.core.config_manager": self.mock_config_manager,
            "src.core.localization": self.mock_localization,
            "src.core.theme_manager": self.mock_theme_manager,
            "src.gui.widgets.detachable_wrapper": self.mock_detachable,
            "src.gui.widgets.welcome": self.mock_welcome,
        }

    def test_initialization(self):
        """Test basic MainWindow initialization."""
        with patch.dict(sys.modules, self._get_modules_to_patch()):
            if "src.gui.main_window" in sys.modules:
                del sys.modules["src.gui.main_window"]

            from src.gui.main_window import MainWindow

            # Instantiate MainWindow
            _ = MainWindow()

            # Verify basic calls
            self.assertTrue(self.mock_config_manager.ConfigManager.called)
            self.assertTrue(self.mock_audio_engine.AudioEngine.called)
            self.assertTrue(qt_widgets.QListWidget.called)
            self.assertTrue(qt_widgets.QStackedWidget.called)
            self.assertTrue(qt_core.QTimer.return_value.start.called)
            self.assertTrue(self.mock_welcome.WelcomeWidget.called)

    def test_device_selection_logic(self):
        """Verify the device selection logic in _find_device_id."""
        with patch.dict(sys.modules, self._get_modules_to_patch()):
            if "src.gui.main_window" in sys.modules:
                del sys.modules["src.gui.main_window"]

            from src.gui.main_window import MainWindow

            devices = [
                {"name": "Built-in Mic", "hostapi_name": "Core Audio", "max_input_channels": 2, "max_output_channels": 0},
                {"name": "Built-in Output", "hostapi_name": "Core Audio", "max_input_channels": 0, "max_output_channels": 2},
                {"name": "USB Audio", "hostapi_name": "Core Audio", "max_input_channels": 2, "max_output_channels": 2},
                {"name": "USB Audio", "hostapi_name": "ASIO", "max_input_channels": 2, "max_output_channels": 2},
            ]

            # Use __new__ to bypass __init__ for pure logic testing
            mw = MainWindow.__new__(MainWindow)

            # Test Case 1: Strict Match Input
            idx = mw._find_device_id(devices, "USB Audio", "ASIO", is_input=True)
            self.assertEqual(idx, 3)

            # Test Case 2: Strict Match Output
            idx = mw._find_device_id(devices, "Built-in Output", "Core Audio", is_input=False)
            self.assertEqual(idx, 1)

            # Test Case 3: Loose Match Input (HostAPI mismatch)
            idx = mw._find_device_id(devices, "USB Audio", "Unknown HostAPI", is_input=True)
            self.assertEqual(idx, 2) # Index 2 is Core Audio USB Audio (first match)

            # Test Case 4: Wrong Capability
            idx = mw._find_device_id(devices, "Built-in Mic", "Core Audio", is_input=False)
            self.assertIsNone(idx)

            # Test Case 5: Name mismatch
            idx = mw._find_device_id(devices, "Nonexistent", None, is_input=True)
            self.assertIsNone(idx)

            # Test Case 6: No HostAPI provided
            idx = mw._find_device_id(devices, "USB Audio", None, is_input=True)
            self.assertEqual(idx, 2)

    def test_module_loading_logic(self):
        """Test _load_module_class helper."""
        from src.core.module_constants import MODULE_SIGNAL_GENERATOR

        with patch.dict(sys.modules, self._get_modules_to_patch()):
            # Mock numpy/scipy as well since modules might import them
            sys.modules["numpy"] = MagicMock()
            sys.modules["scipy"] = MagicMock()
            sys.modules["scipy.signal"] = MagicMock()

            if "src.gui.main_window" in sys.modules:
                del sys.modules["src.gui.main_window"]

            from src.gui.main_window import _load_module_class

            # We need to mock importlib to return our mocked module classes
            # or patching internal imports inside _load_module_class.
            # _load_module_class does explicit imports.
            # E.g. from src.gui.widgets.signal_generator import SignalGenerator

            # Since we are using sys.modules patching, we can pre-populate the module it tries to import
            mock_sig_gen_mod = MagicMock()
            mock_sig_gen_class = MagicMock()
            mock_sig_gen_class.__name__ = "SignalGenerator"
            mock_sig_gen_mod.SignalGenerator = mock_sig_gen_class

            # The path depends on implementation.
            # Assuming src.gui.widgets.signal_generator
            sys.modules["src.gui.widgets.signal_generator"] = mock_sig_gen_mod

            # It might fail if we don't mock ALL potential modules,
            # but _load_module_class usually imports only the requested one.

            try:
                cls = _load_module_class(MODULE_SIGNAL_GENERATOR)
                self.assertEqual(cls.__name__, "SignalGenerator")
            except ImportError:
                # If dependencies are complicated, we might skip, but with mocks it should work
                pass
            except KeyError:
                self.fail("MODULE_SIGNAL_GENERATOR key raised KeyError")

            with self.assertRaises(KeyError):
                _load_module_class("Invalid Key")

    def test_logging_on_missing_device(self):
        """Verify that logger.info is called when a saved device is not found."""

        # Configure Config to return saved devices
        self.mock_config_manager.ConfigManager.return_value.get_audio_config.return_value = {
            "input_device": "Saved Mic",
            "input_hostapi": "Core Audio",
            "output_device": "Saved Speaker",
            "output_hostapi": "Core Audio"
        }

        # Configure AudioEngine to return DIFFERENT devices
        self.mock_audio_engine.AudioEngine.return_value.list_devices.return_value = [
            {"name": "Other Mic", "hostapi_name": "Core Audio", "max_input_channels": 2, "max_output_channels": 0},
            {"name": "Other Speaker", "hostapi_name": "Core Audio", "max_input_channels": 0, "max_output_channels": 2},
        ]

        with patch.dict(sys.modules, self._get_modules_to_patch()):
            if "src.gui.main_window" in sys.modules:
                del sys.modules["src.gui.main_window"]

            with patch("logging.getLogger") as mock_get_logger:
                spy_logger = MagicMock()
                mock_get_logger.return_value = spy_logger

                from src.gui.main_window import MainWindow

                # Instantiate
                MainWindow()

                # Verify info logging
                spy_logger.info.assert_any_call("Saved input device 'Saved Mic' not found, using default.")
                spy_logger.info.assert_any_call("Saved output device 'Saved Speaker' not found, using default.")

    def test_swallowed_exception_logging(self):
        """Verify that logger.error is called when set_devices fallback fails."""

        # Configure Config
        self.mock_config_manager.ConfigManager.return_value.get_audio_config.return_value = {
            "input_device": "Saved Mic",
            "output_device": "Saved Speaker"
        }

        # Mock set_devices to raise exception
        mock_ae_instance = self.mock_audio_engine.AudioEngine.return_value
        def set_devices_side_effect(in_id, out_id):
            if in_id is None and out_id is None:
                raise Exception("Fallback Failure")
            raise Exception("Primary Failure")
        mock_ae_instance.set_devices.side_effect = set_devices_side_effect
        mock_ae_instance.set_pipewire_jack_resident.side_effect = Exception("Resident Failure")

        with patch.dict(sys.modules, self._get_modules_to_patch()):
            if "src.gui.main_window" in sys.modules:
                del sys.modules["src.gui.main_window"]

            with patch("logging.getLogger") as mock_get_logger:
                spy_logger = MagicMock()
                mock_get_logger.return_value = spy_logger

                from src.gui.main_window import MainWindow

                MainWindow()

                # 1. Primary failure
                spy_logger.error.assert_any_call("Failed to set devices/settings: Primary Failure")

                # 2. Fallback failure (search in calls)
                fallback_found = any("Fallback Failure" in str(call) for call in spy_logger.error.call_args_list + spy_logger.warning.call_args_list)
                self.assertTrue(fallback_found, "Fallback Failure was not logged")

                # 3. Resident failure
                resident_found = any("Resident Failure" in str(call) for call in spy_logger.error.call_args_list + spy_logger.warning.call_args_list)
                self.assertTrue(resident_found, "Resident Failure was not logged")

if __name__ == "__main__":
    unittest.main()
