import sys
import os
import unittest
import logging
from unittest.mock import MagicMock, patch

# Add root directory to sys.path to import main_gui
sys.path.append(os.getcwd())

# Mock dependencies before importing main_gui
sys.modules["src.core.fft_manager"] = MagicMock()
sys.modules["src.core.audio_engine"] = MagicMock()
sys.modules["numpy"] = MagicMock()
sys.modules["scipy"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()
sys.modules["PyQt6"] = MagicMock()
sys.modules["PyQt6.QtCore"] = MagicMock()
sys.modules["PyQt6.QtGui"] = MagicMock()
sys.modules["PyQt6.QtWidgets"] = MagicMock()

# Mock internal modules
sys.modules["src.gui.main_window"] = MagicMock()
sys.modules["src.gui.startup"] = MagicMock()

# Setup mocks for ConfigManager and Localization
config_manager_module_mock = MagicMock()
config_manager_cls_mock = MagicMock()
config_manager_module_mock.ConfigManager = config_manager_cls_mock
sys.modules["src.core.config_manager"] = config_manager_module_mock

localization_module_mock = MagicMock()
localization_mock = MagicMock()
localization_module_mock.get_manager = MagicMock(return_value=localization_mock)
localization_module_mock.tr = MagicMock(side_effect=lambda x: x)
sys.modules["src.core.localization"] = localization_module_mock

utils_module_mock = MagicMock()
utils_module_mock.resource_path = MagicMock(side_effect=lambda x: x)
sys.modules["src.core.utils"] = utils_module_mock


# Now import main_gui
import main_gui

class TestMainGuiExceptionLogging(unittest.TestCase):
    def test_config_load_exception_is_logged(self):
        # Arrange
        # ConfigManager() raises Exception
        config_manager_cls_mock.side_effect = Exception("Config load failed test")

        # Configure logging to ensure capture works (though assertLogs handles it)
        # We need to patch main_gui.logging if we add it, but currently it's not there.
        # If main_gui uses logging.error, assertLogs will capture it on the root logger.

        with patch("sys.exit") as mock_exit, \
             patch("PyQt6.QtWidgets.QApplication") as mock_app, \
             patch("signal.signal"):

            mock_app_instance = MagicMock()
            mock_app.return_value = mock_app_instance

            # We expect an ERROR log
            try:
                with self.assertLogs(level='ERROR') as cm:
                    main_gui.main()

                # Assert
                found = any("Config load failed test" in o for o in cm.output)
                self.assertTrue(found, f"Expected log not found in: {cm.output}")

            except AssertionError as e:
                # If assertLogs fails (no logs), it raises AssertionError
                print(f"Caught expected assertion error (test confirms missing logs): {e}")
                # This is expected for reproduction before fix
                raise e

if __name__ == "__main__":
    unittest.main()
