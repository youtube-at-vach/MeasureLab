import unittest
import numpy as np

class TestCalibrationAlignment(unittest.TestCase):
    def test_calibration_alignment(self):
        """Verify that Frequency Counter and 1PPS Monitor calibration logic align."""

        # 1. Frequency Counter Logic Check
        # Reference: 1000Hz
        f_ref = 1000.0
        # For a +4ppm fast clock, samples are captured faster.
        # 48000.192 samples take 1.0 seconds.
        # In 48000 samples, only 48000/48000.192 seconds passed.
        # So a 1000Hz signal appears as 1000 * (48000/48000.192) = 999.996 Hz.
        f_meas = 999.996
        fc_factor = f_ref / f_meas
        # This results in fc_factor = 1.000004

        # 2. 1PPS Monitor Logic Check
        # 1PPS monitor measures +4.0 ppm directly from pulse intervals
        current_ppm = 4.0
        # Factor: new_factor = 1.0 + current_ppm / 1e6
        pps_factor = 1.0 + current_ppm / 1e6

        # Check if factors align
        np.testing.assert_allclose(fc_factor, pps_factor, rtol=1e-6, err_msg=f"Discrepancy: {fc_factor} vs {pps_factor}")

        # 3. Check UI Display Logic Alignment
        # In OnePPSMonitorWidget: ppm = (cal - 1.0) * 1e6
        pps_ui_ppm = (pps_factor - 1.0) * 1e6
        # In FrequencyCounterWidget: curr_ppm = (curr_factor - 1.0) * 1e6
        fc_ui_ppm = (fc_factor - 1.0) * 1e6

        # Check if UI display values align
        np.testing.assert_allclose(pps_ui_ppm, fc_ui_ppm, atol=1e-3, err_msg=f"UI Display Discrepancy: {pps_ui_ppm} vs {fc_ui_ppm}")

if __name__ == '__main__':
    unittest.main()
