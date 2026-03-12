import unittest
import numpy as np
import sys
import os

# Add src to path if not already there
# Current dir: tests/logic_verification/analysis
# Root is ../../../
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../../')))

from src.core.frequency_analysis import calculate_allan_deviation, calculate_frequency_metrics

class TestFrequencyAnalysis(unittest.TestCase):
    def test_allan_deviation_white_noise(self):
        # White Noise FM: Slope should be -1/2 in log-log (sigma ~ tau^-0.5)
        np.random.seed(42)
        n = 1000
        noise = np.random.normal(1000, 1.0, n)

        # dt = 0.1s (10Hz)
        dt = 0.1
        taus, devs = calculate_allan_deviation(noise, dt)

        self.assertGreater(len(taus), 5)
        self.assertGreater(len(devs), 5)

        # Check slope roughly
        # log(sigma) = -0.5 * log(tau) + C
        log_taus = np.log10(taus)
        log_devs = np.log10(devs)

        slope, intercept = np.polyfit(log_taus, log_devs, 1)

        # For white noise FM, slope is -0.5
        # Allow some margin due to limited sample size
        self.assertAlmostEqual(slope, -0.5, delta=0.2)

    def test_allan_deviation_random_walk(self):
        # Random Walk FM: Slope should be +1/2 (sigma ~ tau^0.5)
        np.random.seed(42)
        n = 1000
        steps = np.random.normal(0, 0.1, n)
        walk = 1000 + np.cumsum(steps)

        dt = 0.1
        taus, devs = calculate_allan_deviation(walk, dt)

        log_taus = np.log10(taus)
        log_devs = np.log10(devs)

        slope, intercept = np.polyfit(log_taus, log_devs, 1)

        # For random walk FM, slope is +0.5
        self.assertAlmostEqual(slope, 0.5, delta=0.2)

    def test_allan_deviation_known_values(self):
        """Test calculate_allan_deviation with a known simple sequence."""
        # Simple predictable sequence
        data = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0])
        dt = 1.0
        taus, devs = calculate_allan_deviation(data, dt)

        # For m=1: diffs = [1, 1, 1, 1, 1, 1, 1]
        # sigma = sqrt(0.5 * mean(1^2)) = sqrt(0.5) ≈ 0.7071
        # For m=2: y = [1.5, 3.5, 5.5, 7.5], diffs = [2, 2, 2]
        # sigma = sqrt(0.5 * mean(2^2)) = sqrt(2) ≈ 1.414
        # For m=4: y = [2.5, 6.5], diffs = [4]
        # sigma = sqrt(0.5 * mean(4^2)) = sqrt(8) ≈ 2.828

        expected_taus = [1.0, 2.0, 4.0]
        expected_devs = [np.sqrt(0.5), np.sqrt(2.0), np.sqrt(8.0)]

        self.assertEqual(taus, expected_taus)
        for d, e in zip(devs, expected_devs):
            self.assertAlmostEqual(d, e, places=4)

    def test_calculate_frequency_metrics_gate(self):
        # Silence
        data = np.zeros(1000)
        sr = 48000
        gate = -60.0

        freq, db = calculate_frequency_metrics(data, sr, gate)
        self.assertIsNone(freq)
        self.assertLess(db, gate)

    def test_calculate_frequency_metrics_sine(self):
        # 1kHz Sine
        sr = 48000
        t = np.arange(1000) / sr
        freq_target = 1000.0
        signal = np.sin(2 * np.pi * freq_target * t)

        gate = -60.0
        freq, db = calculate_frequency_metrics(signal, sr, gate)

        self.assertIsNotNone(freq)
        self.assertAlmostEqual(freq, freq_target, places=1)
        # RMS of sine amplitude 1 is 0.707 -> -3dB
        self.assertAlmostEqual(db, -3.0, delta=0.5)

    def test_calculate_frequency_metrics_zero_division(self):
        # Provide a signal that passes the gate and has coarse_freq > 10Hz,
        # but triggers an exception inside optimize_frequency (e.g. ZeroDivisionError).
        import unittest.mock as mock

        sr = 48000
        t = np.arange(1000) / sr
        freq_target = 1000.0
        signal = np.sin(2 * np.pi * freq_target * t)
        gate = -60.0

        with mock.patch('src.core.frequency_analysis.AudioCalc.optimize_frequency', side_effect=ZeroDivisionError):
            freq, db = calculate_frequency_metrics(signal, sr, gate)

            # The function should catch the exception and return the coarse frequency and correct db
            self.assertIsNotNone(freq)
            # 1kHz coarse frequency from 1000 samples @ 48kHz is ~960Hz or 1008Hz due to bins
            # freqs = np.fft.rfftfreq(1000, 1/48000) -> bin size 48Hz. 1008Hz is bin 21.
            self.assertTrue(900 < freq < 1100)
            self.assertAlmostEqual(db, -3.0, delta=0.5)

    def test_calculate_frequency_metrics_empty_array(self):
        # Empty array causes a zero division initially which results in RuntimeWarning
        # Then it causes a ValueError in get_cached_window because Nx=0
        data = np.array([])
        sr = 48000
        gate = -60.0

        with self.assertRaises(ValueError):
            calculate_frequency_metrics(data, sr, gate)

if __name__ == '__main__':
    unittest.main()
