import pytest
import numpy as np
from src.core.analysis import AudioCalc

def test_k_weighting_coefficients():
    """Verify that get_k_weighting_filter returns the expected coefficients for 48kHz."""
    b0, a0, b1, a1 = AudioCalc.get_k_weighting_filter(48000)

    # Expected values (from ITU-R BS.1770-4 Table 1)
    expected_b0 = np.array([1.53512485958697, -2.69169618940638, 1.19839281085285], dtype=np.float32)
    expected_a0 = np.array([1.0, -1.69065929318241, 0.73248077421585], dtype=np.float32)
    expected_b1 = np.array([1.0, -2.0, 1.0], dtype=np.float32)
    expected_a1 = np.array([1.0, -1.99004745483398, 0.99007225036621], dtype=np.float32)

    assert np.allclose(b0, expected_b0), "b0 coefficients mismatch"
    assert np.allclose(a0, expected_a0), "a0 coefficients mismatch"
    assert np.allclose(b1, expected_b1), "b1 coefficients mismatch"
    assert np.allclose(a1, expected_a1), "a1 coefficients mismatch"

    assert b0.dtype == np.float32
    assert a0.dtype == np.float32

def test_c_weighting_design():
    """Verify that design_c_weighting returns coefficients."""
    sr = 48000
    b, a = AudioCalc.design_c_weighting(sr)

    assert isinstance(b, np.ndarray)
    assert isinstance(a, np.ndarray)
    assert b.dtype == np.float32
    assert a.dtype == np.float32
    assert len(b) > 0
    assert len(a) > 0

    # Sanity check: gain at 1kHz should be roughly 0dB (magnitude 1.0)
    # We need freqz
    from scipy.signal import freqz
    w, h = freqz(b, a, worN=[1000], fs=sr)
    magnitude = np.abs(h[0])

    # Should be close to 1.0 (0 dB)
    assert 0.95 < magnitude < 1.05

def test_c_weighting_invalid_sr():
    """Verify that design_c_weighting raises error for invalid sr."""
    with pytest.raises(ValueError):
        AudioCalc.design_c_weighting(0)
