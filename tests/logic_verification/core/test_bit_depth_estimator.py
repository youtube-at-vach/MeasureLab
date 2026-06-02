import pytest
import numpy as np
from src.core.bit_depth_estimator import BitDepthEstimator


@pytest.fixture
def estimator():
    return BitDepthEstimator()


def test_initial_state(estimator):
    """Verify that initially the estimator returns None."""
    assert estimator.analyze() is None


def test_insufficient_data(estimator):
    """Verify that estimator returns None if less than 2 samples are added."""
    estimator.add_samples(np.array([0.5]))
    assert estimator.analyze() is None


def test_reset(estimator):
    """Verify that reset clears the buffer."""
    estimator.add_samples(np.array([0.1, 0.2]))
    estimator.reset()
    assert estimator.analyze() is None


def test_bit_depth_16bit(estimator):
    """Verify 16-bit depth estimation."""
    # 16-bit step size: 2 / 2^16 (full range 2.0) -> 1 / 2^15
    step = 2.0 / 65536.0

    # Create a signal that ramps up by exactly 1 step per sample
    # to ensure we capture the smallest delta
    quantized_signal = np.arange(-10, 10) * step

    estimator.add_samples(quantized_signal)
    results = estimator.analyze()

    assert results is not None
    # Expect ~16.0
    assert abs(results["bit_depth"] - 16.0) < 0.1


def test_bit_depth_24bit(estimator):
    """Verify 24-bit depth estimation."""
    step = 2.0 / (2**24)
    # Ramp with 1 step per sample
    quantized_signal = np.arange(-10, 10) * step

    estimator.add_samples(quantized_signal)
    results = estimator.analyze()

    assert results is not None
    # Expect ~24.0
    assert abs(results["bit_depth"] - 24.0) < 0.1


def test_silence(estimator):
    """Verify behavior with digital silence (all zeros)."""
    silence = np.zeros(1000)
    estimator.add_samples(silence)
    results = estimator.analyze()

    assert results is not None
    assert results["bit_depth"] == 0.0
    assert results["delta_hist"] is None
    # Bit distribution should be all zeros (for 0 input)
    np.testing.assert_array_equal(results["bit_distribution"], np.zeros(32))


def test_bit_distribution(estimator):
    """Verify bit distribution calculation with known patterns."""
    # Test with +1.0 (0x7FFFFFFF)
    # In 2's complement 32-bit:
    # 0x7FFFFFFF = 0111...111 (31 bits set, MSB 0)
    # So bits 0-30 are 1, bit 31 is 0.

    samples_ones = np.ones(100)
    estimator.add_samples(samples_ones)
    results = estimator.analyze()

    bit_dist = results["bit_distribution"]
    # Check bits 0-30 are 1.0 (100% probability)
    np.testing.assert_allclose(bit_dist[:31], 1.0)
    # Check bit 31 is 0.0
    assert bit_dist[31] == 0.0

    estimator.reset()

    # Test with -1.0
    # In sign-magnitude representation:
    # -1.0 scales to -2147483647, which has magnitude 2147483647 (0x7FFFFFFF, bits 0-30 set)
    # and sign bit set (bit 31 set).
    # So all bits 0 to 31 are set to 1.0.

    samples_neg = -np.ones(100)
    estimator.add_samples(samples_neg)
    results = estimator.analyze()

    bit_dist = results["bit_distribution"]
    np.testing.assert_allclose(bit_dist, 1.0)


def test_histogram(estimator):
    """Verify histogram structure."""
    # Create random noise to ensure distribution
    np.random.seed(42)
    noise = np.random.uniform(-0.1, 0.1, 1000)
    estimator.add_samples(noise)
    results = estimator.analyze()

    hist_data = results["delta_hist"]
    assert hist_data is not None
    hist, bin_edges = hist_data

    assert len(hist) == 50
    assert len(bin_edges) == 51
    assert bin_edges[0] == -13
    assert bin_edges[-1] == 0


def test_high_bit_depth_limit(estimator):
    """Verify bit depth estimation near the implementation limit."""
    # The implementation filters diffs <= 1e-12.
    # 1e-12 corresponds to roughly 40 bits.
    # Let's test with a diff slightly larger than 1e-12.

    small_step = 1.1e-12
    # log2(1.1e-12) ~ -39.7
    # 1 - (-39.7) ~ 40.7

    signal = np.array([0, small_step, 2 * small_step])
    estimator.add_samples(signal)
    results = estimator.analyze()

    assert results["bit_depth"] > 40.0
    assert results["bit_depth"] < 41.0


def test_clamping_low(estimator):
    """Verify bit depth clamping at 0."""
    # Large steps -> small bit depth
    # step = 0.5
    # log2(0.5) = -1
    # 1 - (-1) = 2.0

    # If step is 4.0 (possible if signal is not normalized to -1..1 but logic handles it)
    # log2(4) = 2. 1 - 2 = -1. Should clamp to 0.

    large_step_signal = np.array([0, 4.0, 8.0])
    estimator.add_samples(large_step_signal)
    results = estimator.analyze()

    assert results["bit_depth"] == 0.0


def test_bit_depth_8bit(estimator):
    """Verify 8-bit depth estimation."""
    step = 2.0 / 256.0
    quantized_signal = np.arange(-10, 10) * step
    estimator.add_samples(quantized_signal)
    results = estimator.analyze()
    assert results is not None
    assert abs(results["bit_depth"] - 8.0) < 0.1


def test_bit_depth_robust_to_outliers(estimator):
    """Verify that bit depth estimation is immune to sparse floating point outliers or rounding errors."""
    # 16-bit steps
    step = 2.0 / 65536.0
    # Ramp with 400 samples
    quantized_signal = np.arange(-200, 200) * step

    # Inject a tiny outlier (e.g. 1e-11 step, representing a rounding error or jitter)
    # The old algorithm would have detected this and reported ~37 bits instead of 16 bits.
    quantized_signal[200] += 1e-11

    estimator.add_samples(quantized_signal)
    results = estimator.analyze()

    assert results is not None
    # Highly robust check: should still report ~16.0 bits, NOT ~37 bits!
    assert abs(results["bit_depth"] - 16.0) < 0.2
