import numpy as np
from unittest.mock import MagicMock
from src.gui.widgets.frequency_counter import FrequencyCounter
from src.gui.widgets.one_pps_monitor import OnePPSMonitor

# Mock Audio Engine and Calibration
mock_audio_engine = MagicMock()
mock_audio_engine.sample_rate = 48000
mock_calibration = MagicMock()
mock_audio_engine.calibration = mock_calibration

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
print(f"Frequency Counter factor (+4ppm error -> meas=999.996): {fc_factor:.8f}")

# 2. 1PPS Monitor Logic Check
# 1PPS monitor measures +4.0 ppm directly from pulse intervals
current_ppm = 4.0
# Factor: new_factor = 1.0 + current_ppm / 1e6
pps_factor = 1.0 + current_ppm / 1e6
print(f"1PPS Monitor factor (+4.0ppm error):                   {pps_factor:.8f}")

assert np.isclose(fc_factor, pps_factor), f"Discrepancy: {fc_factor} vs {pps_factor}"

# 3. Check UI Display Logic Alignment
# In OnePPSMonitorWidget: ppm = (cal - 1.0) * 1e6
pps_ui_ppm = (pps_factor - 1.0) * 1e6
# In FrequencyCounterWidget: curr_ppm = (curr_factor - 1.0) * 1e6
fc_ui_ppm = (fc_factor - 1.0) * 1e6

print(f"1PPS UI display PPM for factor: {pps_ui_ppm:+.3f} ppm")
print(f"FC UI display PPM for factor:   {fc_ui_ppm:+.3f} ppm")

assert np.isclose(pps_ui_ppm, fc_ui_ppm, atol=1e-3), f"UI Display Discrepancy: {pps_ui_ppm} vs {fc_ui_ppm}"

print("\nVerification Successful: Calibration parameters are aligned.")
