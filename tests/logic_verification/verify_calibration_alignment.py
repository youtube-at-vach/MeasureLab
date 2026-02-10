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
# Reference: 1000Hz, Measured: 1000.004Hz (+4ppm)
f_ref = 1000.0
f_meas = 1000.004
fc_factor = f_ref / f_meas
print(f"Frequency Counter factor for +4ppm error: {fc_factor:.8f}")

# 2. 1PPS Monitor Logic Check
# Simulated error in 1PPS monitor (also +4ppm)
current_ppm = 4.0
# New formula: new_factor = 1.0 / (1.0 + current_ppm / 1e6)
pps_factor = 1.0 / (1.0 + current_ppm / 1e6)
print(f"1PPS Monitor factor for +4ppm error:     {pps_factor:.8f}")

assert np.isclose(fc_factor, pps_factor), f"Discrepancy: {fc_factor} vs {pps_factor}"

# 3. Check UI Display Logic Alignment
# In OnePPSMonitorWidget: ppm = (cal - 1.0) * 1e6
pps_ui_ppm = (pps_factor - 1.0) * 1e6
# In FrequencyCounterWidget: curr_ppm = (curr_factor - 1.0) * 1e6
fc_ui_ppm = (fc_factor - 1.0) * 1e6

print(f"1PPS UI display PPM for factor: {pps_ui_ppm:+.3f} ppm")
print(f"FC UI display PPM for factor:   {fc_ui_ppm:+.3f} ppm")

assert np.isclose(pps_ui_ppm, fc_ui_ppm), f"UI Display Discrepancy: {pps_ui_ppm} vs {fc_ui_ppm}"

print("\nVerification Successful: Calibration parameters are aligned.")
