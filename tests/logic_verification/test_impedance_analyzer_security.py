import unittest
from unittest.mock import MagicMock, patch
import sys
import os
import logging

# Ensure src is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

# Mock sounddevice and PyQt6 modules before importing the widget
# We need to mock them in sys.modules so that imports in the target module don't fail
sys.modules['sounddevice'] = MagicMock()

# Mock PyQt6 modules
mock_qt = MagicMock()
sys.modules['PyQt6'] = mock_qt
sys.modules['PyQt6.QtCore'] = mock_qt
sys.modules['PyQt6.QtGui'] = mock_qt
sys.modules['PyQt6.QtWidgets'] = mock_qt
sys.modules['pyqtgraph'] = MagicMock()

from src.gui.widgets.impedance_analyzer import ImpedanceAnalyzer

class TestImpedanceAnalyzerSecurity(unittest.TestCase):
    def setUp(self):
        self.mock_audio_engine = MagicMock()
        self.mock_audio_engine.sample_rate = 48000
        self.analyzer = ImpedanceAnalyzer(self.mock_audio_engine)

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
