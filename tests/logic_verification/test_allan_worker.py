import unittest
from unittest.mock import MagicMock
import numpy as np
from PyQt6.QtWidgets import QApplication
import sys

from src.gui.widgets.frequency_counter import AllanWorker

# Ensure QApp exists
app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)

class TestAllanWorker(unittest.TestCase):
    def test_worker_logic_basic(self):
        # Setup data: Simple linear drift => constant diffs => constant deviation? 
        # No, linear drift y = at + b => diffs are constant 'a' => variance of constant is 0 => sigma 0?
        # Let's use white noise, sigma should decrease with tau.

        np.random.seed(42)
        noise = np.random.normal(1000, 1.0, 1000)
        history = list(noise)

        worker = AllanWorker(history, update_interval_ms=100, display_mode='frequency')

        # Mock signal slot
        mock_slot = MagicMock()
        worker.signals.result.connect(mock_slot)

        # Run synchronous
        worker.run()

        # Verify result was emitted
        mock_slot.assert_called_once()
        args = mock_slot.call_args[0]
        taus, devs = args

        self.assertGreater(len(taus), 5)
        self.assertGreater(len(devs), 5)
        self.assertEqual(len(taus), len(devs))

        # Check values are reasonable (not all zero, positive)
        self.assertTrue(all(t > 0 for t in taus))
        self.assertTrue(all(d > 0 for d in devs))

    def test_worker_empty_history(self):
        worker = AllanWorker([], 100, 'frequency')
        mock_slot = MagicMock()
        worker.signals.result.connect(mock_slot)
        worker.run()

        mock_slot.assert_called_once_with([], [])

    def test_worker_period_mode(self):
        # If input is frequency, period mode should invert it
        freqs = [100.0] * 100 # Constant freq => constant period => 0 dev
        worker = AllanWorker(freqs, 100, 'period')

        mock_slot = MagicMock()
        worker.signals.result.connect(mock_slot)
        worker.run()

        args = mock_slot.call_args[0]
        taus, devs = args

        # Constant signal => deviation should be 0.0 (or very close to floating point error)
        # But we filter 0s in the plot widget, here it returns raw.
        # However, std(constant) is 0.
        self.assertEqual(devs[0], 0.0)

if __name__ == '__main__':
    unittest.main()
