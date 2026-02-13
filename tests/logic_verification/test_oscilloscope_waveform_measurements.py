import os
import sys
from unittest.mock import MagicMock
import numpy as np

# Dependencies are installed in the environment, so we can import directly.
from src.gui.widgets.oscilloscope import Oscilloscope

def test_estimate_frequency_hz_sine():
    sr = 48000
    f = 1000.0
    t = np.arange(sr // 10) / sr  # 0.1s
    y = 0.8 * np.sin(2 * np.pi * f * t)
    est = Oscilloscope.estimate_frequency_hz(t, y)
    assert est is not None
    assert abs(est - f) < 5.0


def test_estimate_rise_fall_times_step_like_square():
    sr = 48000
    t = np.arange(sr // 200) / sr  # 5ms

    # Create a single rising edge then falling edge within the window.
    y = np.full_like(t, -1.0)
    y[t >= 0.001] = 1.0
    y[t >= 0.003] = -1.0

    rise_s, fall_s, low, high = Oscilloscope.estimate_rise_fall_times_s(t, y)

    # Ideal step has ~0 rise/fall; estimator may return None (too sharp) or a tiny positive.
    assert low is not None and high is not None
    assert high > low
    if rise_s is not None:
        assert 0 <= rise_s < 1e-3
    if fall_s is not None:
        assert 0 <= fall_s < 1e-3


def test_estimate_rise_fall_times_ramp_has_expected_10_90_time():
    # Create a clean low->high ramp of 25us so 10-90% should be 20us.
    dt = 1e-6
    t = np.arange(0.0, 200e-6, dt)
    y = np.full_like(t, -1.0)

    t0 = 50e-6
    ramp = 25e-6
    t1 = t0 + ramp
    # Rising ramp
    idx = (t >= t0) & (t <= t1)
    y[idx] = -1.0 + 2.0 * ((t[idx] - t0) / ramp)
    y[t > t1] = 1.0

    # Falling ramp later
    t2 = 120e-6
    t3 = t2 + ramp
    idx2 = (t >= t2) & (t <= t3)
    y[idx2] = 1.0 - 2.0 * ((t[idx2] - t2) / ramp)
    y[t > t3] = -1.0

    rise_s, fall_s, low, high = Oscilloscope.estimate_rise_fall_times_s(t, y)
    assert low is not None and high is not None
    assert rise_s is not None
    assert fall_s is not None

    assert abs(rise_s - 20e-6) < 2e-6
    assert abs(fall_s - 20e-6) < 2e-6

def test_frequency_estimation_edge_cases():
    # Insufficient data
    t = np.array([0, 1, 2])
    y = np.array([0, 1, 0])
    assert Oscilloscope.estimate_frequency_hz(t, y) is None

    assert Oscilloscope.estimate_frequency_hz(None, None) is None

    # No crossings
    sample_rate = 1000
    t = np.arange(100) / sample_rate
    y = np.ones(100)
    assert Oscilloscope.estimate_frequency_hz(t, y) is None

    # Exact zero crossings (< 2)
    t = np.array([0, 1, 2, 3, 4], dtype=float)
    y = np.array([-1, 0, 1, 0, -1], dtype=float)
    assert Oscilloscope.estimate_frequency_hz(t, y) is None

    # Exact zero crossings (>= 2)
    t = np.arange(10, dtype=float)
    y = np.array([-1, 1, -1, 1, -1, 1, -1, 1, -1, 1], dtype=float)
    est = Oscilloscope.estimate_frequency_hz(t, y)
    assert est is not None
    assert abs(est - 0.5) < 1e-6

def test_measurements_apply_calibration():
    # Mock AudioEngine with calibration
    mock_engine = MagicMock()
    mock_engine.sample_rate = 48000
    # Setup calibration mock
    mock_engine.calibration = MagicMock()
    mock_engine.calibration.input_sensitivity = 1.0 # Default

    # Instantiate Oscilloscope
    osc = Oscilloscope(mock_engine)

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
    mock_engine.calibration.input_sensitivity = 2.0
    meas_cal = osc.get_measurements(data)

    # RMS should double
    assert abs(meas_cal['l_rms'] - (expected_l_rms * 2.0)) < 1e-3
    assert abs(meas_cal['l_vpp'] - 2.0) < 1e-3 # 1.0 * 2.0 = 2.0 Vpp

def test_measurements_none_data():
    mock_engine = MagicMock()
    osc = Oscilloscope(mock_engine)
    meas = osc.get_measurements(None)
    assert meas['l_rms'] == 0.0
