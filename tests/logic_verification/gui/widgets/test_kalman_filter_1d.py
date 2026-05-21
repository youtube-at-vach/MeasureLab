import unittest
from src.gui.widgets.lock_in_frequency_counter import KalmanFilter1D


class TestKalmanFilter1D(unittest.TestCase):
    def test_reset_behavior(self):
        kf = KalmanFilter1D(process_noise=1e-10, measurement_noise=1e-6)

        # Perform some updates to change internal state
        kf.update(100.0)
        kf.update(105.0)

        # Verify state changed
        self.assertFalse(kf._first_run)
        self.assertNotEqual(kf.p, 1.0)

        # Reset
        kf.reset()

        # Verify state reverted to initial conditions
        self.assertTrue(kf._first_run)
        self.assertEqual(kf.p, 1.0)

    def test_update_step(self):
        kf = KalmanFilter1D(process_noise=1e-10, measurement_noise=1e-6)

        res1 = kf.update(10.0)
        self.assertEqual(res1, 10.0)
        self.assertEqual(kf.x, 10.0)

        res2 = kf.update(12.0)
        self.assertNotEqual(res2, 10.0)

    def test_get_std_uncertainty(self):
        kf = KalmanFilter1D()
        kf.p = 4.0
        self.assertEqual(kf.get_std_uncertainty(), 2.0)


if __name__ == "__main__":
    unittest.main()
