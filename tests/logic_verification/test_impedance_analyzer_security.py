import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Ensure src is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

class TestImpedanceAnalyzerSecurity(unittest.TestCase):
    def setUp(self):
        # Mock modules before import
        self.modules_patcher = patch.dict(sys.modules, {
            'sounddevice': MagicMock(),
            'PyQt6': MagicMock(),
            'PyQt6.QtCore': MagicMock(),
            'PyQt6.QtGui': MagicMock(),
            'PyQt6.QtWidgets': MagicMock(),
            'pyqtgraph': MagicMock()
        })
        self.modules_patcher.start()

        # Local import to avoid top-level dependency issues and satisfy linter
        from src.gui.widgets.impedance_analyzer import ImpedanceAnalyzer
        self.ImpedanceAnalyzer = ImpedanceAnalyzer

        self.mock_audio_engine = MagicMock()
        self.mock_audio_engine.sample_rate = 48000
        self.analyzer = self.ImpedanceAnalyzer(self.mock_audio_engine)

    def tearDown(self):
        self.modules_patcher.stop()

    def test_exception_logging_in_frequency_setter(self):
        """
        Verify that exceptions in _apply_dynamic_buffering are logged.
        """
        # Mock _apply_dynamic_buffering to raise an exception
        with patch.object(self.analyzer, '_apply_dynamic_buffering', side_effect=ValueError("Simulated Critical Failure")):
            # We expect an error log. Since it is currently swallowed, this should fail.
            with self.assertLogs('src.gui.widgets.impedance_analyzer', level='ERROR') as cm:
                self.analyzer.gen_frequency = 1000.0

            # Check if the log message contains the exception details
            self.assertTrue(any("Simulated Critical Failure" in o for o in cm.output))

if __name__ == '__main__':
    unittest.main()
