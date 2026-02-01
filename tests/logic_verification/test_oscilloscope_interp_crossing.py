
import unittest
import numpy as np
from src.gui.widgets.oscilloscope import Oscilloscope

class TestInterpCrossingTime(unittest.TestCase):
    def test_rising_crossing(self):
        t = np.array([0.0, 1.0])
        y = np.array([-1.0, 1.0])
        # Crossing at t=0.5
        res = Oscilloscope._interp_crossing_time(t, y, 0.0, "rising")
        self.assertAlmostEqual(res, 0.5)

    def test_falling_crossing(self):
        t = np.array([0.0, 1.0])
        y = np.array([1.0, -1.0])
        # Crossing at t=0.5
        res = Oscilloscope._interp_crossing_time(t, y, 0.0, "falling")
        self.assertAlmostEqual(res, 0.5)

    def test_no_crossing(self):
        t = np.array([0.0, 1.0])
        y = np.array([0.5, 1.0])
        res = Oscilloscope._interp_crossing_time(t, y, 0.0, "rising")
        self.assertIsNone(res)

    def test_multiple_crossings_first_is_picked(self):
        t = np.array([0.0, 1.0, 2.0, 3.0])
        # rising at 0.5, rising at 2.5
        y = np.array([-1.0, 1.0, -1.0, 1.0])
        res = Oscilloscope._interp_crossing_time(t, y, 0.0, "rising")
        self.assertAlmostEqual(res, 0.5)

    def test_empty_or_small(self):
        self.assertIsNone(Oscilloscope._interp_crossing_time(np.array([]), np.array([]), 0, "rising"))
        self.assertIsNone(Oscilloscope._interp_crossing_time(np.array([1]), np.array([1]), 0, "rising"))

    def test_mask_all_false_optimization_check(self):
        # This specifically targets the "if not mask[idx]: return None" logic
        # by providing data where no crossing exists.
        t = np.linspace(0, 10, 100)
        y = np.ones_like(t) # All 1.0, level 0.0 -> no crossing
        res = Oscilloscope._interp_crossing_time(t, y, 0.0, "rising")
        self.assertIsNone(res)

if __name__ == '__main__':
    unittest.main()
