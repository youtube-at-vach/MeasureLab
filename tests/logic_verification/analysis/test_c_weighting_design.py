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

def test_design_c_weighting_response_shape():
    """Verify roughly C-weighting shape."""
    sr = 48000
    b, a = design_c_weighting(sr)

    # w1 = 20.6 Hz, w2 = 12194 Hz are the poles.
    # Since they are double poles, the attenuation at these frequencies should be approx -6 dB relative to passband center.

    freqs = [20.6, 1000, 12194]
    w, h = scipy.signal.freqz(b, a, worN=freqs, fs=sr)
    gains = 20 * np.log10(np.abs(h))

    # 1kHz is 0dB reference
    assert np.isclose(gains[1], 0.0, atol=0.1)

    # Check approximate attenuation at corner frequencies
    # Expecting roughly -6dB (since transfer function has (s+w)^2 in denominator)
    # The magnitude of 1/(s+w)^2 at s=jw is 1/|jw+w|^2 = 1/|w(j+1)|^2 = 1/(2w^2).
    # At DC (s -> 0)? No, s^2 in numerator.
    # At passband (w >> w1, w << w2), H ~ s^2 / (s^2 * w2^2 / s^2?) -> 1.

    # Let's just assert they are attenuated.
    assert gains[0] < -2.0, f"Expected attenuation at 20.6Hz, got {gains[0]} dB"
    assert gains[2] < -2.0, f"Expected attenuation at 12194Hz, got {gains[2]} dB"
