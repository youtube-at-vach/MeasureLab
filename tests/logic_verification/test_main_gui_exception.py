import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Ensure we can import main_gui
# We go up two levels from 'tests/logic_verification/' to reach the project root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

class TestMainGuiException(unittest.TestCase):
    def setUp(self):
        # Clean up sys.modules to avoid pollution
        self.patched_modules = {}
        for mod in ["PyQt6", "PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtWidgets",
                    "src.gui.main_window", "src.gui.startup",
                    "src.core.config_manager", "src.core.localization",
                    "src.core.utils", "src.core.fft_manager"]:
            self.patched_modules[mod] = sys.modules.get(mod)
            sys.modules[mod] = MagicMock()

            # Ensure mocked classes have appropriate attributes
            if mod == "src.core.config_manager":
                sys.modules[mod].ConfigManager = MagicMock()
            if mod == "src.gui.startup":
                 sys.modules[mod].TopLevelWindowLogger = MagicMock()
                 sys.modules[mod].WrappingSplashScreen = MagicMock()

    def tearDown(self):
        # Restore sys.modules
        for mod, original in self.patched_modules.items():
            if original is None:
                if mod in sys.modules:
                    del sys.modules[mod]
            else:
                sys.modules[mod] = original

    def test_startup_exception_logging(self):
        """
        Verify that exceptions during ConfigManager initialization are logged.
        """
        # We need to reload main_gui to pick up the mocks if it was already imported
        if "main_gui" in sys.modules:
            del sys.modules["main_gui"]

        try:
            import main_gui
        except ImportError:
            # If main_gui cannot be imported (e.g. invalid path), skip
            self.skipTest("Could not import main_gui")
            return

        # Patch ConfigManager in main_gui module
        with patch("main_gui.ConfigManager") as MockConfigManager:
            # Simulate exception during init
            MockConfigManager.side_effect = Exception("Simulated Config Load Failure")

            # Patch sys.exit to avoid exiting
            with patch("sys.exit"):
                # Use assertLogs to capture logs
                with self.assertLogs(level="ERROR") as cm:
                    main_gui.main()

                # Check if our simulated exception message is in the logs
                self.assertTrue(any("Simulated Config Load Failure" in o for o in cm.output))

if __name__ == "__main__":
    unittest.main()
