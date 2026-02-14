import sys
import unittest
from unittest.mock import MagicMock, patch
from collections import deque

# Mock PyQt6 before importing the module under test to allow logic testing without GUI
# We assign MagicMock instances to modules.
mock_qt = MagicMock()
sys.modules["PyQt6"] = mock_qt
sys.modules["PyQt6.QtCore"] = MagicMock()
sys.modules["PyQt6.QtGui"] = MagicMock()
sys.modules["PyQt6.QtWidgets"] = MagicMock()

# Mock numpy if not present
try:
    import numpy as np
except ImportError:
    np = MagicMock()
    sys.modules["numpy"] = np

# Mock src.core.localization
mock_loc = MagicMock()
mock_loc.tr = lambda x: x
sys.modules["src.core.localization"] = mock_loc

# Now import the module
from src.gui.widgets.timecode_monitor import TimecodeMonitor

class TestTimecodeCalibration(unittest.TestCase):
    def test_calibration_poll_optimization(self):
        # Mock AudioEngine
        audio_engine = MagicMock()
        audio_engine.sample_rate = 48000

        monitor = TimecodeMonitor(audio_engine)

        # Setup calibration state manually
        monitor._cal_active = True
        monitor._cal_key = "L"
        monitor._cal_need = 30
        monitor._cal_started_at = 1000.0

        # Fill samples with known values
        # Format: (ref_t, diff, in_lat, out_lat)
        samples = []
        for i in range(100):
            samples.append((float(i), int(i), float(i), float(i)))

        monitor._cal_samples = deque(samples)

        # Mock time.time to return a time shortly after start (no timeout)
        with patch('time.time', return_value=1001.0):
            result = monitor.calibration_poll()

        self.assertIsNotNone(result)
        self.assertTrue(result['ok'])
        self.assertEqual(result['samples'], 30)

        # Verify result calculation
        # We expect diffs to be the last 30 items: 70..99
        # list(range(70, 100))
        # Median calculation in code:
        # diffs.sort()
        # mid = len(diffs) // 2
        # len=30, mid=15.
        # diffs[15] is 70+15 = 85.
        # diffs[14] is 70+14 = 84.
        # (84+85)/2.0 = 84.5. round(84.5) -> 84.
        expected_delay = 84

        self.assertEqual(result['total_delay_frames'], expected_delay)

        # Case 2: Not enough samples
        monitor._cal_active = True # reset active (it was set False by success)
        monitor._cal_samples = deque(samples[:10]) # 10 items

        with patch('time.time', return_value=1001.0):
            result = monitor.calibration_poll()

        self.assertIsNone(result)

        # Case 3: Timeout
        monitor._cal_active = True
        monitor._cal_result = None # Reset result

        with patch('time.time', return_value=1010.0): # > 8.0s after 1000.0
            result = monitor.calibration_poll()

        self.assertIsNotNone(result)
        self.assertFalse(result['ok'])
        self.assertEqual(result['reason'], "timeout")

if __name__ == '__main__':
    unittest.main()
