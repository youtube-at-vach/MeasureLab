import numpy as np
import pytest
from scipy import signal

from src.core.true_peak import TruePeakMeter, estimate_true_peak


@pytest.mark.parametrize("block_size", [1, 7, 64, 1024])
def test_streaming_peak_matches_continuous_interpolation(block_size):
    rng = np.random.default_rng(25)
    samples = rng.uniform(-0.99, 0.99, (2081, 2))
    meter = TruePeakMeter(2)
    peaks = np.zeros(2)
    for start in range(0, len(samples), block_size):
        peaks = np.maximum(peaks, meter.process(samples[start : start + block_size]))
    peaks = np.maximum(peaks, meter.flush())
    reference = signal.resample_poly(np.pad(samples, ((20, 20), (0, 0))), 4, 1, axis=0)
    np.testing.assert_allclose(peaks, np.max(np.abs(reference), axis=0), atol=1e-12)


def test_intersample_peak_and_reset():
    samples = np.tile([0.99, 0.99, -0.99, -0.99], 1024)
    assert estimate_true_peak(samples) > 1.4
    meter = TruePeakMeter(1)
    meter.process(samples)
    meter.reset()
    assert meter.process(np.zeros(50))[0] == 0
    assert estimate_true_peak(np.zeros((0, 2))) == 0
    with pytest.raises(ValueError, match="finite"):
        meter.process(np.array([np.nan]))


def test_low_frequency_tone_has_no_artificial_block_edge_peaks():
    meter = TruePeakMeter(1)
    samples = 0.9 * np.sin(2 * np.pi * 1000 * np.arange(8192) / 48000)
    peak = max(meter.process(samples[start : start + 64])[0] for start in range(0, len(samples), 64))
    assert 20 * np.log10(peak) == pytest.approx(20 * np.log10(0.9), abs=0.01)
