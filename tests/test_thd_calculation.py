import unittest
import numpy as np
from src.core.analysis import AudioCalc

class TestTHDCalculation(unittest.TestCase):
    def test_analyze_harmonics_thd(self):
        """
        Tests the THD calculation within analyze_harmonics with a known signal.
        """
        sampling_rate = 48000
        N = 4800
        t = np.arange(N) / sampling_rate
        fundamental_freq = 1000.0

        # Amplitudes
        fundamental_amp = 1.0
        h2_amp = 0.1
        h3_amp = 0.05
        h5_amp = 0.01

        # Create signal
        signal = fundamental_amp * np.sin(2 * np.pi * fundamental_freq * t)
        signal += h2_amp * np.sin(2 * np.pi * 2 * fundamental_freq * t)
        signal += h3_amp * np.sin(2 * np.pi * 3 * fundamental_freq * t)
        signal += h5_amp * np.sin(2 * np.pi * 5 * fundamental_freq * t)

        # Expected THD calculation
        # THD = sqrt(sum_of_harmonics_power) / fundamental_power
        # For amplitudes, it's sqrt(sum(h_amp^2)) / fund_amp
        sum_sq_harmonics = h2_amp**2 + h3_amp**2 + h5_amp**2
        expected_thd_linear = np.sqrt(sum_sq_harmonics) / fundamental_amp
        expected_thd_percent = expected_thd_linear * 100

        # Run analysis
        # Using a Hann window as it's common for harmonic analysis
        result = AudioCalc.analyze_harmonics(
            audio_data=signal,
            fundamental_freq=fundamental_freq,
            window_name='hann',
            sampling_rate=sampling_rate
        )

        # Assertions
        # Check if the fundamental was found correctly
        self.assertAlmostEqual(result['basic_wave']['frequency'], fundamental_freq, delta=1.0)
        self.assertAlmostEqual(result['basic_wave']['max_amplitude'], fundamental_amp, delta=0.01)

        # Check the main result: THD
        self.assertAlmostEqual(result['thd_percent'], expected_thd_percent, places=1)

        # Optional: Check individual harmonics
        harmonics = result['harmonics']
        # 2nd harmonic
        self.assertAlmostEqual(harmonics[0]['amplitude_linear'], h2_amp, delta=0.01)
        # 3rd harmonic
        self.assertAlmostEqual(harmonics[1]['amplitude_linear'], h3_amp, delta=0.01)
        # 4th harmonic should be near zero
        self.assertAlmostEqual(harmonics[2]['amplitude_linear'], 0.0, delta=0.01)
        # 5th harmonic
        self.assertAlmostEqual(harmonics[3]['amplitude_linear'], h5_amp, delta=0.01)

if __name__ == '__main__':
    unittest.main()
