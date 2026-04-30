import sys
import unittest
import numpy as np
from unittest.mock import MagicMock, patch

# Mock PyQt6 and pyqtgraph before importing the widget
mock_qt_widgets = MagicMock()
mock_qt_core = MagicMock()
mock_pyqtgraph = MagicMock()

class DummyQWidget:
    def __init__(self, *args, **kwargs):
        pass

mock_qt_widgets.QWidget = DummyQWidget
mock_qt_core.Qt = MagicMock()

with patch.dict(
    sys.modules,
    {
        "PyQt6.QtWidgets": mock_qt_widgets,
        "PyQt6.QtCore": mock_qt_core,
        "pyqtgraph": mock_pyqtgraph,
    },
):
    from src.gui.widgets.lock_in_frequency_counter import LockInFrequencyCounterWidget, LockInFrequencyCounter

class TestLockInDecimals(unittest.TestCase):
    def setUp(self):
        self.mock_audio_engine = MagicMock()
        self.module = LockInFrequencyCounter(self.mock_audio_engine)
        self.widget = LockInFrequencyCounterWidget(self.module)

    def test_get_decimal_places_limit(self):
        """Test that get_decimal_places respects the new limit of 12."""
        # High uncertainty -> few decimals
        self.assertEqual(self.widget.get_decimal_places(0.1), 1)
        self.assertEqual(self.widget.get_decimal_places(0.01), 2)
        
        # Low uncertainty -> many decimals
        self.assertEqual(self.widget.get_decimal_places(1e-8), 8)
        self.assertEqual(self.widget.get_decimal_places(1e-10), 10)
        self.assertEqual(self.widget.get_decimal_places(1e-12), 12)
        
        # Extremely low uncertainty -> capped at 12
        self.assertEqual(self.widget.get_decimal_places(1e-15), 12)
        self.assertEqual(self.widget.get_decimal_places(0), 5) # Default

if __name__ == "__main__":
    unittest.main()
