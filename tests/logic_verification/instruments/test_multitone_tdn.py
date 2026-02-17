import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))
import unittest
import numpy as np
from src.core.analysis import AudioCalc

class TestMultitoneTDN(unittest.TestCase):
    def setUp(self):
        # Create a frequency axis: 0 to 1000 Hz, 1 Hz resolution
        self.freqs = np.linspace(0, 1000, 1001)
        # Empty magnitude spectrum
        self.mag = np.zeros_like(self.freqs)

    def test_calculate_multitone_tdn_basic(self):
        """
        Test basic single tone + single noise bin scenario.
        """
        # Tone at 500 Hz
        tone_idx = 500
        self.mag[tone_idx] = 1.0

        # Noise at 100 Hz
        noise_idx = 100
        self.mag[noise_idx] = 0.1

        # Expected:
        # Tone energy = 1.0^2 = 1.0
        # Noise energy = 0.1^2 = 0.01
        # TDN = sqrt(0.01 / 1.0) = 0.1
        # TDN dB = 20 * log10(0.1) = -20 dB

        result = AudioCalc.calculate_multitone_tdn(self.mag, self.freqs, [500])

        self.assertAlmostEqual(result['tdn'], 10.0, places=4) # TDN is in percent
        self.assertAlmostEqual(result['tdn_db'], -20.0, places=4)

    def test_calculate_multitone_tdn_multiple_tones(self):
        """
        Test multiple tones.
        """
        # Tones at 200 Hz and 800 Hz
        self.mag[200] = 1.0
        self.mag[800] = 1.0

        # Noise at 500 Hz
        self.mag[500] = 0.1

        # Tone energy = 1^2 + 1^2 = 2.0
        # Noise energy = 0.01
        # TDN = sqrt(0.01 / 2.0) = sqrt(0.005) ~= 0.07071
        # TDN % = 7.071...

        result = AudioCalc.calculate_multitone_tdn(self.mag, self.freqs, [200, 800])

        expected_tdn = np.sqrt(0.01 / 2.0)
        self.assertAlmostEqual(result['tdn'], expected_tdn * 100, places=4)

    def test_calculate_multitone_tdn_no_noise(self):
        """
        Test with only tones (perfect signal).
        """
        self.mag[500] = 1.0
        result = AudioCalc.calculate_multitone_tdn(self.mag, self.freqs, [500])

        self.assertEqual(result['tdn'], 0.0)
        self.assertEqual(result['tdn_db'], -100.0)

    def test_calculate_multitone_tdn_no_signal(self):
        """
        Test with silence (no tones).
        """
        result = AudioCalc.calculate_multitone_tdn(self.mag, self.freqs, [500])

        # If tone energy is 0, it should return 0 TDN, -100 dB (as per implementation)
        self.assertEqual(result['tdn'], 0.0)
        self.assertEqual(result['tdn_db'], -100.0)

    def test_calculate_multitone_tdn_nearby_noise(self):
        """
        Test that noise close to the tone is counted as tone energy (skirt).
        The mask is +/- 4 bins around peak.
        """
        # Tone at 500 Hz
        self.mag[500] = 1.0

        # "Noise" at 502 Hz (within +2 bins)
        # Should be included in tone mask
        self.mag[502] = 0.5

        # Real noise at 100 Hz
        self.mag[100] = 0.1

        # Tone energy should be 1.0^2 + 0.5^2 = 1.25
        # Noise energy should be 0.1^2 = 0.01

        result = AudioCalc.calculate_multitone_tdn(self.mag, self.freqs, [500])

        expected_tdn = np.sqrt(0.01 / 1.25)
        self.assertAlmostEqual(result['tdn'], expected_tdn * 100, places=4)

    def test_with_synthetic_fft(self):
        """
        End-to-end test with synthetic time-domain signal and FFT.
        """
        sr = 10000
        duration = 1.0
        t = np.arange(int(sr * duration)) / sr

        # Tone at 1000 Hz, Amplitude 1.0
        signal = 1.0 * np.sin(2 * np.pi * 1000 * t)

        # Tone at 2000 Hz, Amplitude 0.5
        signal += 0.5 * np.sin(2 * np.pi * 2000 * t)

        # Add White Noise
        np.random.seed(42)
        noise_amp = 0.01
        noise = np.random.normal(0, noise_amp, len(t))

        full_signal = signal + noise

        # Compute FFT
        # Use simple numpy rfft
        fft_res = np.fft.rfft(full_signal)
        mag = np.abs(fft_res)
        freqs = np.fft.rfftfreq(len(full_signal), 1/sr)

        # Analyze
        result = AudioCalc.calculate_multitone_tdn(mag, freqs, [1000, 2000])

        # Verification
        # Total signal energy (Parseval's theorem mostly holds, but we are working in freq domain)
        # We can approximate expected TDN.
        # Signal Power ~ (1.0^2/2 + 0.5^2/2) = 0.5 + 0.125 = 0.625 (RMS squared)
        # Noise Power ~ noise_amp^2 = 0.01^2 = 0.0001

        # TDN ratio (Amplitude) ~ sqrt(Noise Power / Signal Power)
        # Note: AudioCalc works on FFT magnitude bins.
        # FFT Magnitude of sine wave amplitude A is A * N/2.
        # FFT Magnitude of white noise is spread. Sum of squares of FFT bins = Sum of squares of time samples * N (or similar scaling).
        # ratio = sqrt( sum(noise_bins^2) / sum(tone_bins^2) )
        # This is equivalent to RMS ratio.

        # expected_ratio = np.sqrt(0.0001 / 0.625)
        # expected_ratio ~= sqrt(0.00016) = 0.0126
        # TDN % ~= 1.26%

        # Allow some tolerance because windowing/spectral leakage might affect bin separation
        # and noise is random.
        self.assertTrue(0.5 < result['tdn'] < 2.0, f"Expected TDN around 1.26%, got {result['tdn']}%")

if __name__ == '__main__':
    unittest.main()
