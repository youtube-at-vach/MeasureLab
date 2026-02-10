import unittest
from unittest.mock import MagicMock, patch
import argparse
import sys

# Mock PyQt6 and pyqtgraph to avoid GUI dependency issues during logic tests
# This is crucial for environments without a display or Qt libraries
# We need to do this BEFORE importing modules that depend on them
with patch.dict(sys.modules, {
    'PyQt6': MagicMock(),
    'PyQt6.QtCore': MagicMock(),
    'PyQt6.QtWidgets': MagicMock(),
    'PyQt6.QtGui': MagicMock(),
    'pyqtgraph': MagicMock(),
}):
    # Now we can safely import modules that use Qt
    from src.measurement_modules.base import MeasurementModule
    # We delay importing RawTimeSeries to inside the test method or after mocks are active globally if needed
    # But since we are inside a context manager that only lasts for this block, imports must happen here?
    # No, sys.modules patching persists if we modify sys.modules directly, but patch.dict context manager reverts it.
    # So if we import inside the block, the module is cached in sys.modules.
    # However, if we import inside the test method, we need the patch active then.
    pass

class ConcreteModuleNoRun(MeasurementModule):
    @property
    def name(self) -> str:
        return "Test Module"

    @property
    def description(self) -> str:
        return "Test Description"

class ConcreteModuleWithRun(MeasurementModule):
    @property
    def name(self) -> str:
        return "Test Module With Run"

    @property
    def description(self) -> str:
        return "Test Description With Run"

    def run(self, args: argparse.Namespace):
        print("Run override executed")

class TestMeasurementModuleRun(unittest.TestCase):
    def test_instantiate_without_run(self):
        """
        Verify that a subclass can be instantiated without implementing run(),
        once MeasurementModule.run is no longer abstract.
        """
        try:
            instance = ConcreteModuleNoRun()
            args = argparse.Namespace()
            with self.assertLogs(level='DEBUG'):
                instance.run(args)
        except TypeError as e:
            self.fail(f"Instantiation failed, likely due to abstract method: {e}")

    def test_instantiate_with_run(self):
        """
        Verify that a subclass implementing run() still works as expected.
        """
        instance = ConcreteModuleWithRun()
        args = argparse.Namespace()
        from io import StringIO
        captured_output = StringIO()
        sys.stdout = captured_output
        try:
            instance.run(args)
            self.assertIn("Run override executed", captured_output.getvalue())
        finally:
            sys.stdout = sys.__stdout__

    def test_instantiate_raw_time_series(self):
        """
        Verify that RawTimeSeries can be instantiated (without run).
        """
        # Mock dependencies again to be safe
        with patch.dict(sys.modules, {
            'PyQt6': MagicMock(),
            'PyQt6.QtCore': MagicMock(),
            'PyQt6.QtWidgets': MagicMock(),
            'PyQt6.QtGui': MagicMock(),
            'pyqtgraph': MagicMock(),
            'sounddevice': MagicMock(), # Mock sounddevice
        }):

            # Since I already imported dependencies like numpy, I need to make sure AudioEngine sees the mocked sounddevice.
            # If src.core.audio_engine was already imported (it wasn't in this test file yet), I'd need to reload it.
            # But just to be safe, I'll allow it to be imported fresh (since it wasn't imported at top level).

            from src.core.audio_engine import AudioEngine
            # Mock AudioEngine to avoid any real logic
            mock_audio_engine = MagicMock(spec=AudioEngine)
            mock_audio_engine.sample_rate = 48000

            # Import inside try/except to catch import errors if mocking fails
            try:
                from src.gui.widgets.raw_time_series import RawTimeSeries
            except ImportError as e:
                self.fail(f"Failed to import RawTimeSeries: {e}")

            try:
                instance = RawTimeSeries(mock_audio_engine)
                # Re-import MeasurementModule to get the one loaded in this context
                from src.measurement_modules.base import MeasurementModule as MM
                self.assertIsInstance(instance, MM)

                # Verify run works (default implementation)
                args = argparse.Namespace()
                with self.assertLogs(level='DEBUG'):
                    instance.run(args)
            except TypeError as e:
                self.fail(f"Failed to instantiate RawTimeSeries: {e}")

if __name__ == '__main__':
    unittest.main()
