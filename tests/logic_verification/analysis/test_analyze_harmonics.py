import unittest
import numpy as np
import os
import sys

# Ensure src is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))

from src.core.analysis import AudioCalc

class TestAnalyzeHarmonics(unittest.TestCase):
    def setUp(self):
        self.sampling_rate = 48000
        self.duration = 0.5
        self.t = np.arange(int(self.sampling_rate * self.duration)) / self.sampling_rate

    def test_basic_harmonics(self):
        """
        Test a signal with known harmonics:
        Fundamental (1kHz) @ -20dBFS (amp = 0.1)
        2nd Harmonic (2kHz) @ -40dBFS (amp = 0.01)
        3rd Harmonic (3kHz) @ -60dBFS (amp = 0.001)
        """
        f0 = 1000.0
        amp_fund = 0.1
        amp_h2 = 0.01
        amp_h3 = 0.001

        signal = amp_fund * np.sin(2 * np.pi * f0 * self.t)
        signal += amp_h2 * np.sin(2 * np.pi * 2 * f0 * self.t)
        signal += amp_h3 * np.sin(2 * np.pi * 3 * f0 * self.t)

        result = AudioCalc.analyze_harmonics(
            audio_data=signal,
            fundamental_freq=f0,
            window_name='hann',
            sampling_rate=self.sampling_rate
        )

        # Verify Fundamental
        self.assertAlmostEqual(result['basic_wave']['frequency'], f0, delta=1.0)
        self.assertAlmostEqual(result['basic_wave']['max_amplitude'], amp_fund, delta=0.005)

        # Verify Harmonics
        # harmonics[0] -> 2nd harmonic (2kHz)
        self.assertAlmostEqual(result['harmonics'][0]['frequency'], 2 * f0, delta=2.0)
        self.assertAlmostEqual(result['harmonics'][0]['amplitude_linear'], amp_h2, delta=0.0005)

        # harmonics[1] -> 3rd harmonic (3kHz)
        self.assertAlmostEqual(result['harmonics'][1]['frequency'], 3 * f0, delta=3.0)
        self.assertAlmostEqual(result['harmonics'][1]['amplitude_linear'], amp_h3, delta=0.0001)

    def test_pure_sine(self):
        """
        Test a pure sine wave (0dBFS). THD should be very low.
        """
        f0 = 1000.0
        amp = 1.0
        signal = amp * np.sin(2 * np.pi * f0 * self.t)

        result = AudioCalc.analyze_harmonics(
            audio_data=signal,
            fundamental_freq=f0,
            window_name='hann',
            sampling_rate=self.sampling_rate
        )

        self.assertAlmostEqual(result['basic_wave']['max_amplitude'], amp, delta=0.01)
        # THD should be negligible (< 0.001%)
        self.assertLess(result['thd_percent'], 0.001)

    def test_high_frequency_harmonics(self):
        """
        Test harmonics near/above Nyquist.
        Fundamental: 10kHz
        2nd Harmonic: 20kHz (Should be detected)
        3rd Harmonic: 30kHz (Above Nyquist 24kHz -> Should be ignored/handled)
        """
        f0 = 10000.0
        amp = 0.5
        signal = amp * np.sin(2 * np.pi * f0 * self.t)
        # Add 2nd harmonic
        signal += (amp * 0.1) * np.sin(2 * np.pi * 2 * f0 * self.t)

        # Add 3rd harmonic (aliased if simply generated, but for analyze_harmonics input,
        # the function should just stop checking harmonics above Nyquist)
        # Here we just check that analyze_harmonics returns consistent results.

        result = AudioCalc.analyze_harmonics(
            audio_data=signal,
            fundamental_freq=f0,
            window_name='hann',
            sampling_rate=self.sampling_rate
        )

        # 2nd Harmonic (20kHz) should be present
        h2 = result['harmonics'][0]
        self.assertAlmostEqual(h2['frequency'], 20000.0, delta=20.0)
        self.assertAlmostEqual(h2['amplitude_linear'], amp * 0.1, delta=0.01)

        # 3rd Harmonic (30kHz) should NOT be present in valid results
        # analyze_harmonics loop breaks if harmonic_freq >= sampling_rate / 2
        # So we expect subsequent harmonics to be missing or zeroed out

        # The implementation loops up to 10th harmonic.
        # It breaks loop: `if harmonic_freq >= sampling_rate / 2: break`
        # So harmonics list might be shorter than 9 elements.

        # We can explicitly check that all returned harmonics are below Nyquist
        for h in result['harmonics']:
            self.assertLess(h['frequency'], self.sampling_rate / 2)

        # However, looking at the code:
        # for i in range(2, 11): ... if harmonic_freq >= sampling_rate / 2: break
        # harmonic_results.append(...) is called inside the loop.
        # So if it breaks early, the list is shorter.

        self.assertEqual(len(result['harmonics']), 1)
        self.assertEqual(result['harmonics'][0]['order'], 2)


    def test_frequency_refinement(self):
        """
        Test frequency estimation precision for off-bin frequencies.
        Using shorter signal to make bins wider.
        """
        N = 4096
        t = np.arange(N) / self.sampling_rate
        # bin_width = self.sampling_rate / N # ~11.7 Hz (Unused variable removed)

        target_freq = 1000.5 # Mid-bin
        amp = 0.5
        signal = amp * np.sin(2 * np.pi * target_freq * t)

        result = AudioCalc.analyze_harmonics(
            audio_data=signal,
            fundamental_freq=1000.0, # Guess
            window_name='hann',
            sampling_rate=self.sampling_rate
        )

        detected_freq = result['basic_wave']['frequency']
        # Should be much closer than bin width (11.7Hz)
        self.assertAlmostEqual(detected_freq, target_freq, delta=1.0)

    def test_low_level_signal(self):
        """
        Test analysis with very low signal amplitude (-60dBFS).
        """
        f0 = 1000.0
        amp = 0.001 # -60dBFS
        signal = amp * np.sin(2 * np.pi * f0 * self.t)

        result = AudioCalc.analyze_harmonics(
            audio_data=signal,
            fundamental_freq=f0,
            window_name='hann',
            sampling_rate=self.sampling_rate
        )

        self.assertAlmostEqual(result['basic_wave']['max_amplitude'], amp, delta=0.0001)
        self.assertAlmostEqual(result['basic_wave']['frequency'], f0, delta=1.0)

if __name__ == '__main__':
    unittest.main()
