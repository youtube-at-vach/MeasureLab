import os
import tempfile
import unittest
from src.core.module_discovery import discover_modules

class TestModuleDiscovery(unittest.TestCase):
    def test_discover_modules_real(self):
        """Test scanning the actual source code directory."""
        # Locate src/gui/widgets relative to the project root
        widgets_dir = os.path.join("src", "gui", "widgets")

        if not os.path.exists(widgets_dir):
            self.skipTest(f"Widgets directory not found at {widgets_dir}")

        registry = discover_modules(widgets_dir, "src.gui.widgets")

        # Verify specific known modules
        self.assertIn("Signal Generator", registry)
        self.assertEqual(registry["Signal Generator"], ("src.gui.widgets.signal_generator", "SignalGenerator"))

        self.assertIn("Spectrum Analyzer", registry)
        self.assertEqual(registry["Spectrum Analyzer"], ("src.gui.widgets.spectrum_analyzer", "SpectrumAnalyzer"))

        # Verify a reasonable number of modules found
        self.assertGreater(len(registry), 5)

    def test_discover_modules_dummy(self):
        """Test scanning a dummy directory with specific structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a dummy module file
            module_content = """
from src.measurement_modules.base import MeasurementModule

class MyModule(MeasurementModule):
    @property
    def name(self) -> str:
        return "My Dummy Module"
            """
            with open(os.path.join(tmpdir, "my_module.py"), "w") as f:
                f.write(module_content)

            # Create a non-module file (no class inheriting MeasurementModule)
            with open(os.path.join(tmpdir, "utils.py"), "w") as f:
                f.write("def helper(): pass")

            registry = discover_modules(tmpdir, "dummy.widgets")

            self.assertIn("My Dummy Module", registry)
            self.assertEqual(registry["My Dummy Module"], ("dummy.widgets.my_module", "MyModule"))

            self.assertNotIn("utils", registry)

if __name__ == '__main__':
    unittest.main()
