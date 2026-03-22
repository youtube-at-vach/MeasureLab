import unittest
import numpy as np
import scipy.signal
import scipy.stats
from unittest.mock import patch
from src.core.generators import PinkNoise


class TestPinkNoise(unittest.TestCase):
    """Tests for the PinkNoise generator logic."""

    def test_initialization(self):
        """Verify that a new instance has correct initial state."""
        pn = PinkNoise()
        self.assertEqual(pn.b0, 0.0)
        self.assertEqual(pn.b1, 0.0)
        self.assertEqual(pn.b2, 0.0)
        self.assertEqual(pn.b3, 0.0)
        self.assertEqual(pn.b4, 0.0)
        self.assertEqual(pn.b5, 0.0)
        self.assertEqual(pn.b6, 0.0)

    def test_output_format(self):
        """Verify output shape and data type."""
        pn = PinkNoise()
        n = 1024
        out = pn.generate(n)

        self.assertIsInstance(out, np.ndarray)
        self.assertEqual(out.shape, (n,))
        self.assertEqual(out.dtype, np.float32)

    def test_spectral_slope(self):
        """Verify that the generated noise has a -10 dB/decade slope (pink noise)."""
        pn = PinkNoise()
        sample_rate = 48000
        duration = 5.0
        n_samples = int(sample_rate * duration)

        # Use a fixed seed for reproducibility of the random noise input
        np.random.seed(42)
        noise = pn.generate(n_samples)

        # Compute Power Spectral Density using Welch's method
        f, Pxx = scipy.signal.welch(noise, fs=sample_rate, nperseg=4096)

        # Select frequency range for slope calculation (100 Hz to 10 kHz)
        # Avoid DC/very low freq and Nyquist edge
        low_cutoff = 100
        high_cutoff = 10000
        idx = np.where((f >= low_cutoff) & (f <= high_cutoff))[0]

        f_sub = f[idx]
        Pxx_sub = Pxx[idx]

        # Log-log scale
        log_f = np.log10(f_sub)
        log_P = 10 * np.log10(Pxx_sub + 1e-12)  # Power in dB

        # Linear regression to find slope
        slope, intercept, r_value, p_value, std_err = scipy.stats.linregress(log_f, log_P)

        # Pink noise should have a slope of -10 dB/decade
        # We allow a tolerance because it's a stochastic process and an approximation filter
        self.assertAlmostEqual(
            slope, -10.0, delta=1.0, msg=f"Spectral slope {slope:.2f} dB/dec should be close to -10 dB/dec"
        )

    def test_statefulness(self):
        """Verify that internal state updates across calls."""
        pn = PinkNoise()

        # Mock random.randn to return a known constant sequence (e.g., all 1.0)
        # This makes the filter deterministic for testing state evolution
        with patch("numpy.random.randn") as mock_randn:
            mock_randn.return_value = np.ones(10, dtype=np.float32)

            # First call
            _ = pn.generate(10)

            # Check that state variables are no longer 0
            state_vars = [pn.b0, pn.b1, pn.b2, pn.b3, pn.b4, pn.b5, pn.b6]
            self.assertTrue(any(v != 0.0 for v in state_vars), "State variables should update after generation")

            # Capture state after first call
            state_after_first = list(state_vars)

            # Second call (mock still returns ones)
            _ = pn.generate(10)

            # Check that state has evolved further
            state_after_second = [pn.b0, pn.b1, pn.b2, pn.b3, pn.b4, pn.b5, pn.b6]
            self.assertNotEqual(
                state_after_first, state_after_second, "State should continue to evolve on subsequent calls"
            )


if __name__ == "__main__":
    unittest.main()
