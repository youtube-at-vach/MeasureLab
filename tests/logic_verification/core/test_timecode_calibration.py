import sys
import unittest
import importlib.util
from unittest.mock import MagicMock, patch
from collections import deque


class TestTimecodeCalibration(unittest.TestCase):
    def setUp(self):
        # Create mocks
        self.mock_qt = MagicMock()
        self.mock_loc = MagicMock()
        self.mock_loc.tr = lambda x: x

        # Prepare mocks dict
        mocks = {
            "PyQt6": self.mock_qt,
            "PyQt6.QtCore": MagicMock(),
            "PyQt6.QtGui": MagicMock(),
            "PyQt6.QtWidgets": MagicMock(),
            "src.core.localization": self.mock_loc,
        }

        # Mock numpy if not present
        if "numpy" not in sys.modules and importlib.util.find_spec("numpy") is None:
            # Create a mock numpy that behaves enough like numpy for import
            mock_np = MagicMock()
            # Essential attributes often used at import time
            mock_np.array = MagicMock()
            mock_np.float32 = float
            mock_np.int64 = int
            mocks["numpy"] = mock_np

        # Setup patcher for sys.modules
        self.modules_patcher = patch.dict(sys.modules, mocks)
        self.modules_patcher.start()

        # Ensure we reload the module under test to pick up the mocks
        if "src.gui.widgets.timecode_monitor" in sys.modules:
            del sys.modules["src.gui.widgets.timecode_monitor"]

        # Now import
        from src.gui.widgets.timecode_monitor import TimecodeMonitor

        self.TimecodeMonitor = TimecodeMonitor

    def tearDown(self):
        self.modules_patcher.stop()
        # Clean up the poisoned module so subsequent tests import the real one
        if "src.gui.widgets.timecode_monitor" in sys.modules:
            del sys.modules["src.gui.widgets.timecode_monitor"]

    def test_calibration_poll_optimization(self):
        # Mock AudioEngine
        audio_engine = MagicMock()
        audio_engine.sample_rate = 48000

        monitor = self.TimecodeMonitor(audio_engine)

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
        with patch("time.time", return_value=1001.0):
            result = monitor.calibration_poll()

        self.assertIsNotNone(result)
        self.assertTrue(result["ok"])
        self.assertEqual(result["samples"], 30)

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

        self.assertEqual(result["total_delay_frames"], expected_delay)

        # Case 2: Not enough samples
        monitor._cal_active = True  # reset active (it was set False by success)
        monitor._cal_samples = deque(samples[:10])  # 10 items

        with patch("time.time", return_value=1001.0):
            result = monitor.calibration_poll()

        self.assertIsNone(result)

        # Case 3: Timeout
        monitor._cal_active = True
        monitor._cal_result = None  # Reset result

        with patch("time.time", return_value=1010.0):  # > 8.0s after 1000.0
            result = monitor.calibration_poll()

        self.assertIsNotNone(result)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "timeout")


if __name__ == "__main__":
    unittest.main()
