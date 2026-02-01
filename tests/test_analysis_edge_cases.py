
import numpy as np
import pytest
from src.core.analysis import AudioCalc

def test_optimize_frequency_empty_signal():
    """Test optimize_frequency with empty signal."""
    signal = np.array([])
    sr = 48000
    # Should not crash
    freq = AudioCalc.optimize_frequency(signal, sr, 1000)
    # Expectation: Returns the guess or NaN, but definitely not crash
    assert freq == 1000 or np.isnan(freq)

def test_optimize_frequency_zero_sr():
    """Test optimize_frequency with zero sampling rate."""
    signal = np.zeros(100)
    sr = 0
    # Should not crash
    freq = AudioCalc.optimize_frequency(signal, sr, 1000)
    assert freq == 1000 or np.isnan(freq)

def test_optimize_frequency_return_full_empty():
    """Test optimize_frequency with return_full=True and empty signal."""
    signal = np.array([])
    sr = 48000
    ret = AudioCalc.optimize_frequency(signal, sr, 1000, return_full=True)
    # Should return a tuple of 3
    assert len(ret) == 3
    best_freq, coeffs, M = ret
    # best_freq should be guess or NaN
    assert best_freq == 1000 or np.isnan(best_freq)
    # coeffs and M might be None or empty
    if M is not None:
        assert len(M) == 0

def test_resample_zero_sr():
    """Test resample with zero source SR."""
    data = np.zeros(100)
    # Should return original data or handle gracefully
    res = AudioCalc.resample(data, 0, 48000)
    assert np.array_equal(res, data)

def test_resample_zero_target_sr():
    """Test resample with zero target SR."""
    data = np.zeros(100)
    res = AudioCalc.resample(data, 48000, 0)
    assert np.array_equal(res, data)

def test_calculate_thdn_sine_fit_empty():
    """Test calculate_thdn_sine_fit with empty signal."""
    signal = np.array([])
    sr = 48000
    thdn, fund, noise = AudioCalc.calculate_thdn_sine_fit(signal, sr, 1000)
    # Should return -140dB or similar "no signal" result
    assert thdn == -140.0
    assert fund == 0.0
    assert noise == 0.0
