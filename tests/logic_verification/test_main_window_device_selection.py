import sys
import unittest
from unittest.mock import MagicMock

# -------------------------------------------------------------------------
# MOCKING DEPENDENCIES
# -------------------------------------------------------------------------
# We need to mock PyQt6 and other heavy dependencies to load MainWindow
# without a GUI environment.

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

sys.modules["PyQt6"] = MagicMock()
sys.modules["PyQt6.QtCore"] = MagicMock()
sys.modules["PyQt6.QtWidgets"] = qt_widgets
sys.modules["numpy"] = MagicMock()
sys.modules["scipy"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

# Mock internal modules
sys.modules["src.core.audio_engine"] = MagicMock()
sys.modules["src.core.config_manager"] = MagicMock()
sys.modules["src.core.localization"] = MagicMock()
sys.modules["src.core.theme_manager"] = MagicMock()
sys.modules["src.gui.widgets.detachable_wrapper"] = MagicMock()

# -------------------------------------------------------------------------
# IMPORT
# -------------------------------------------------------------------------
try:
    from src.gui.main_window import MainWindow
except ImportError as e:
    print(f"Failed to import MainWindow: {e}")
    MainWindow = None

class TestMainWindowDeviceSelection(unittest.TestCase):
    def setUp(self):
        if MainWindow is None:
            self.skipTest("MainWindow could not be imported")

        # We don't instantiate MainWindow because __init__ does a lot.
        # We just want to test the helper method which should be pure logic.
        # But we need an instance or class to call the method if it's an instance method.
        # Since we are refactoring, we can just test the method by attaching it to a dummy
        # or calling it as unbound method if possible, or instantiating a mocked MainWindow.

        # Let's instantiate a minimal MainWindow if possible, or just mock __init__
        pass

    def test_find_device_id_logic(self):
        """
        Since we haven't implemented the method in MainWindow yet,
        we define the expected logic here to verify our test expectations,
        and then we will verify it calls the method on MainWindow once implemented.
        """

        devices = [
            {"name": "Built-in Mic", "hostapi_name": "Core Audio", "max_input_channels": 2, "max_output_channels": 0},
            {"name": "Built-in Output", "hostapi_name": "Core Audio", "max_input_channels": 0, "max_output_channels": 2},
            {"name": "USB Audio", "hostapi_name": "Core Audio", "max_input_channels": 2, "max_output_channels": 2},
            {"name": "USB Audio", "hostapi_name": "ASIO", "max_input_channels": 2, "max_output_channels": 2},
        ]

        # Create an instance with the new method (simulating it) or access it if it exists
        # For now, I'll use a local helper to verify my logic, then I'll use this test
        # to verify the ACTUAL method after I apply the edit.

        mw = MainWindow.__new__(MainWindow) # Skip __init__

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
