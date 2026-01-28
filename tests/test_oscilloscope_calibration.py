
import os
import sys
import numpy as np

sys.path.append(os.getcwd())

from src.gui.widgets.oscilloscope import Oscilloscope

class MockCalibration:
    def __init__(self):
        self.input_sensitivity = 1.0

class MockAudioEngine:
    def __init__(self):
        self.calibration = MockCalibration()
        self.sample_rate = 48000

def test_oscilloscope_get_measurements_applies_calibration():
    # Setup
    engine = MockAudioEngine()
    osc = Oscilloscope(engine)

    # 1. Test with default sensitivity (1.0)
    # 0.5 Amplitude Sine Wave -> RMS = 0.5 / sqrt(2) ~= 0.3535
    t = np.linspace(0, 1, 1000)
    data = np.zeros((1000, 2))
    data[:, 0] = 0.5 * np.sin(2 * np.pi * 50 * t) # Left
    data[:, 1] = 0.2 * np.sin(2 * np.pi * 50 * t) # Right

    meas = osc.get_measurements(data)

    expected_l_rms = 0.5 / np.sqrt(2)
    expected_r_rms = 0.2 / np.sqrt(2)

    assert abs(meas['l_rms'] - expected_l_rms) < 1e-3
    assert abs(meas['l_vpp'] - 1.0) < 1e-3 # 0.5 to -0.5 -> 1.0 Vpp
    assert abs(meas['r_rms'] - expected_r_rms) < 1e-3

    # 2. Test with sensitivity = 2.0 (1.0 FS = 2.0 Volts)
    engine.calibration.input_sensitivity = 2.0
    meas_cal = osc.get_measurements(data)

    # RMS should double
    assert abs(meas_cal['l_rms'] - (expected_l_rms * 2.0)) < 1e-3
    assert abs(meas_cal['l_vpp'] - 2.0) < 1e-3 # 1.0 * 2.0 = 2.0 Vpp

def test_oscilloscope_get_measurements_none_data():
    engine = MockAudioEngine()
    osc = Oscilloscope(engine)
    meas = osc.get_measurements(None)
    assert meas['l_rms'] == 0.0
