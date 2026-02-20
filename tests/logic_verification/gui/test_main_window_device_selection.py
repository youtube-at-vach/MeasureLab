import sys
import unittest
from unittest.mock import MagicMock, patch

# -------------------------------------------------------------------------
# MOCKING DEPENDENCIES
# -------------------------------------------------------------------------
# We mock PyQt6 and other heavy dependencies to load MainWindow
# without a GUI environment. But we do this inside a patch to avoid global pollution.

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
qt_widgets.QWidget = MagicMock
qt_widgets.QHBoxLayout = MagicMock
qt_widgets.QVBoxLayout = MagicMock
qt_widgets.QListWidget = MagicMock
qt_widgets.QStackedWidget = MagicMock
qt_widgets.QStatusBar = MagicMock
qt_widgets.QLabel = MagicMock
qt_widgets.QComboBox = MagicMock

mock_audio_engine = MagicMock()
mock_config_manager = MagicMock()
mock_localization = MagicMock()
mock_theme_manager = MagicMock()
mock_detachable = MagicMock()

class TestMainWindowDeviceSelection(unittest.TestCase):
    def test_find_device_id_logic(self):
        """
        Verify the device selection logic in _find_device_id.
        """

        # Patch modules needed by MainWindow.
        # We do NOT patch numpy or scipy here, letting them be real if available.
        modules_to_patch = {
            "PyQt6": MagicMock(),
            "PyQt6.QtCore": MagicMock(),
            "PyQt6.QtWidgets": qt_widgets,
            "src.core.audio_engine": mock_audio_engine,
            "src.core.config_manager": mock_config_manager,
            "src.core.localization": mock_localization,
            "src.core.theme_manager": mock_theme_manager,
            "src.gui.widgets.detachable_wrapper": mock_detachable,
        }

        with patch.dict(sys.modules, modules_to_patch):
            # Now we import MainWindow inside the patched context
            try:
                # We might need to reload if it was already imported?
                # But typically in pytest, test files are imported sequentially.
                # If MainWindow was already imported by another test, this import will return
                # the existing module object which might have real dependencies if not cleared.
                # However, since we are patching sys.modules, the import system sees our mocks
                # for dependencies.
                # The issue is if src.gui.main_window is already in sys.modules.
                # To be safe, we can remove it first if it exists, or rely on patch.dict
                # to shadow it if we were patching IT.
                # But here we are patching its DEPENDENCIES.
                # If src.gui.main_window is already imported, it holds references to the OLD
                # (possibly real) dependencies.
                # But here, we want to import it for the first time or force reload.

                if "src.gui.main_window" in sys.modules:
                    del sys.modules["src.gui.main_window"]

                from src.gui.main_window import MainWindow
            except ImportError as e:
                self.fail(f"Failed to import MainWindow: {e}")

            devices = [
                {"name": "Built-in Mic", "hostapi_name": "Core Audio", "max_input_channels": 2, "max_output_channels": 0},
                {"name": "Built-in Output", "hostapi_name": "Core Audio", "max_input_channels": 0, "max_output_channels": 2},
                {"name": "USB Audio", "hostapi_name": "Core Audio", "max_input_channels": 2, "max_output_channels": 2},
                {"name": "USB Audio", "hostapi_name": "ASIO", "max_input_channels": 2, "max_output_channels": 2},
            ]

            # Create an instance (mocked __init__ effectively due to mocked dependencies)
            # Or use __new__ to bypass __init__ completely which is safer for logic testing.
            mw = MainWindow.__new__(MainWindow)

            # Check if method exists
            if not hasattr(mw, "_find_device_id"):
                self.fail("Method _find_device_id not found on MainWindow")

            # Test Case 1: Strict Match Input
            # Find "USB Audio" with "ASIO" (Input)
            idx = mw._find_device_id(devices, "USB Audio", "ASIO", is_input=True)
            self.assertEqual(idx, 3)

            # Test Case 2: Strict Match Output
            # Find "Built-in Output" with "Core Audio" (Output)
            idx = mw._find_device_id(devices, "Built-in Output", "Core Audio", is_input=False)
            self.assertEqual(idx, 1)

            # Test Case 3: Loose Match Input (HostAPI mismatch)
            # Find "USB Audio" with "Unknown HostAPI". Should fall back to name match.
            # It should find the first "USB Audio" that has input channels.
            idx = mw._find_device_id(devices, "USB Audio", "Unknown HostAPI", is_input=True)
            self.assertEqual(idx, 2) # Index 2 is Core Audio USB Audio (first match)

            # Test Case 4: Wrong Capability
            # Find "Built-in Mic" as Output. Should be None.
            idx = mw._find_device_id(devices, "Built-in Mic", "Core Audio", is_input=False)
            self.assertIsNone(idx)

            # Test Case 5: Name mismatch
            idx = mw._find_device_id(devices, "Nonexistent", None, is_input=True)
            self.assertIsNone(idx)

            # Test Case 6: No HostAPI provided (Strict match on name only)
            # Find "USB Audio", any host api.
            idx = mw._find_device_id(devices, "USB Audio", None, is_input=True)
            self.assertEqual(idx, 2)

if __name__ == "__main__":
    unittest.main()
