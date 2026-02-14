import numpy as np
import scipy.signal
import pytest
from src.core.analysis import design_c_weighting

def test_design_c_weighting_returns_tuple():
    sr = 48000
    res = design_c_weighting(sr)
    assert isinstance(res, tuple)
    assert len(res) == 2
    b, a = res
    assert isinstance(b, np.ndarray)
    assert isinstance(a, np.ndarray)

def test_design_c_weighting_invalid_sr():
    with pytest.raises(ValueError):
        design_c_weighting(0)
    with pytest.raises(ValueError):
        design_c_weighting(-100)

def test_design_c_weighting_response_at_1k():
    sr = 48000
    b, a = design_c_weighting(sr)

    # Check at 1kHz
    w, h = scipy.signal.freqz(b, a, worN=[1000], fs=sr)
    gain_db = 20 * np.log10(np.abs(h[0]))

    # Should be 0 dB (normalized)
    assert np.isclose(gain_db, 0.0, atol=0.1)

def test_design_c_weighting_response_wide():
    """Verify roughly C-weighting shape at key frequencies."""
    # Use higher SR to match the original test's accuracy requirement
    sr = 192000
    b, a = design_c_weighting(sr)

    # Test frequencies: 20Hz, 1kHz, 20kHz
    freqs = [20.0, 1000.0, 20000.0]
    w, h = scipy.signal.freqz(b, a, worN=freqs, fs=sr)
    gains = 20 * np.log10(np.abs(h) + 1e-12)

    # 20 Hz: approx -6.2 dB
    assert np.isclose(gains[0], -6.2, atol=0.5), f"Gain at 20Hz: {gains[0]} (expected ~ -6.2)"

    # 1 kHz: approx 0 dB
    assert np.isclose(gains[1], 0.0, atol=0.1), f"Gain at 1kHz: {gains[1]} (expected ~ 0.0)"

    # 20 kHz: approx -11.2 dB (with some rolloff/warping depending on SR, but test expects ~ -11.2)
    assert np.isclose(gains[2], -11.2, atol=1.0), f"Gain at 20kHz: {gains[2]} (expected ~ -11.2)"

def test_design_c_weighting_response_shape_corners():
    """Verify approximate attenuation at corner frequencies (20.6Hz, 12194Hz)."""
    sr = 48000
    b, a = design_c_weighting(sr)

    freqs = [20.6, 12194]
    w, h = scipy.signal.freqz(b, a, worN=freqs, fs=sr)
    gains = 20 * np.log10(np.abs(h))

    # Expect roughly -3dB to -6dB attenuation relative to passband center
    assert gains[0] < -2.0, f"Expected attenuation at 20.6Hz, got {gains[0]} dB"
    assert gains[1] < -2.0, f"Expected attenuation at 12194Hz, got {gains[1]} dB"
