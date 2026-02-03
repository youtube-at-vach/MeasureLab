
import unittest
import numpy as np
from src.core.analysis import AudioCalc

class TestSineFitCorrectness(unittest.TestCase):
    def test_sine_fit_accuracy(self):
        sampling_rate = 48000
        duration = 0.1
        N = int(sampling_rate * duration)
        t = np.arange(N) / sampling_rate
        freq_target = 1000.0

        # Generate signal: Sinewave + DC + drift + noise
        # 1.0 * sin(2pi*1000*t) + 0.5 * cos(2pi*1000*t) + 0.2 (DC)
        # Amplitude = sqrt(1^2 + 0.5^2) = 1.118
        # Phase = atan2(0.5, 1.0)
        signal = 1.0 * np.sin(2 * np.pi * freq_target * t) + \
                 0.5 * np.cos(2 * np.pi * freq_target * t) + \
                 0.2 + \
                 0.01 * np.random.randn(N)

        # Initial guess
        freq_guess = 1005.0

        best_freq, coeffs, M = AudioCalc.optimize_frequency(signal, sampling_rate, freq_guess, return_full=True)

        # Check frequency accuracy
        self.assertAlmostEqual(best_freq, freq_target, places=1)

        # Check coeffs
        # coeffs order is [sin, cos, offset]
        # Expected: ~1.0, ~0.5, ~0.2
        self.assertAlmostEqual(coeffs[0], 1.0, delta=0.1)
        self.assertAlmostEqual(coeffs[1], 0.5, delta=0.1)
        self.assertAlmostEqual(coeffs[2], 0.2, delta=0.1)

        # Check residual RMS is small (close to noise floor)
        fitted = M @ coeffs
        residual = signal - fitted
        rms = np.sqrt(np.mean(residual**2))
        self.assertLess(rms, 0.02) # Noise is 0.01 rms

if __name__ == "__main__":
    unittest.main()
