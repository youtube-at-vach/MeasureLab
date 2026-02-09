import unittest
import numpy as np
import sys
import os

# Ensure src is in path if running directly
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.core.analysis import AudioCalc

class TestMultitoneTDN(unittest.TestCase):
    def setUp(self):
        # Create a basic frequency array: 0 to 1000 Hz, 1 Hz resolution
        self.freqs = np.linspace(0, 1000, 1001)
        self.mag = np.zeros_like(self.freqs)

    def test_calculate_multitone_tdn_basic(self):
        """
        Test with a single tone and single noise bin.
        Tone at 500 Hz (amp 1.0).
        Noise at 100 Hz (amp 0.1).
        Expected TDN: 0.1 / 1.0 = 0.1 (-20 dB).
        """
        # Tone at 500 Hz
        tone_idx = 500
        self.mag[tone_idx] = 1.0

        # Noise at 100 Hz
        noise_idx = 100
        self.mag[noise_idx] = 0.1

        # Calculate
        result = AudioCalc.calculate_multitone_tdn(self.mag, self.freqs, [500])

        # Verify
        # Expected TDN linear = sqrt(noise_energy / tone_energy)
        # noise_energy = 0.1^2 = 0.01
        # tone_energy = 1.0^2 = 1.0
        expected_tdn = np.sqrt(0.01 / 1.0)
        expected_tdn_db = 20 * np.log10(expected_tdn)

        self.assertAlmostEqual(result['tdn'], expected_tdn * 100, places=4)
        self.assertAlmostEqual(result['tdn_db'], expected_tdn_db, places=4)

    def test_calculate_multitone_tdn_multiple_tones(self):
        """
        Test with multiple tones and noise.
        Tones at 200 Hz (amp 1.0) and 800 Hz (amp 0.5).
        Noise at 500 Hz (amp 0.1).
        """
        # Tones
        self.mag[200] = 1.0
        self.mag[800] = 0.5

        # Noise
        self.mag[500] = 0.1

        # Calculate
        result = AudioCalc.calculate_multitone_tdn(self.mag, self.freqs, [200, 800])

        # Verify
        # tone_energy = 1.0^2 + 0.5^2 = 1.0 + 0.25 = 1.25
        # noise_energy = 0.1^2 = 0.01
        expected_tdn = np.sqrt(0.01 / 1.25)
        expected_tdn_db = 20 * np.log10(expected_tdn)

        self.assertAlmostEqual(result['tdn'], expected_tdn * 100, places=4)
        self.assertAlmostEqual(result['tdn_db'], expected_tdn_db, places=4)

    def test_calculate_multitone_tdn_no_noise(self):
        """
        Test with only tones, no noise.
        """
        self.mag[500] = 1.0

        result = AudioCalc.calculate_multitone_tdn(self.mag, self.freqs, [500])

        # Should be perfect (-100 dB or similar limit)
        self.assertEqual(result['tdn'], 0.0)
        self.assertEqual(result['tdn_db'], -100.0)

    def test_calculate_multitone_tdn_no_signal(self):
        """
        Test with zero magnitude.
        """
        result = AudioCalc.calculate_multitone_tdn(self.mag, self.freqs, [500])

        # Should handle gracefully
        self.assertEqual(result['tdn'], 0.0)
        self.assertEqual(result['tdn_db'], -100.0)

    def test_calculate_multitone_tdn_nearby_noise(self):
        """
        Test logic that masks bins around the peak.
        Tone at 500 Hz.
        "Noise" at 502 Hz.
        Since 502 is within +/- 4 bins of 500, it should be counted as tone energy, not noise.
        Real noise at 100 Hz.
        """
        self.mag[500] = 1.0
        self.mag[502] = 0.1 # Should be considered tone
        self.mag[100] = 0.05 # Real noise

        result = AudioCalc.calculate_multitone_tdn(self.mag, self.freqs, [500])

        # Verify
        # tone_energy = 1.0^2 + 0.1^2 = 1.01
        # noise_energy = 0.05^2 = 0.0025
        expected_tdn = np.sqrt(0.0025 / 1.01)
        expected_tdn_db = 20 * np.log10(expected_tdn)

        self.assertAlmostEqual(result['tdn'], expected_tdn * 100, places=4)
        self.assertAlmostEqual(result['tdn_db'], expected_tdn_db, places=4)

    def test_with_synthetic_fft(self):
        """
        Generate time-domain signal, compute FFT, and verify.
        Signal: 1kHz Sine + White Noise.
        """
        sampling_rate = 48000
        duration = 1.0
        N = int(sampling_rate * duration)
        t = np.arange(N) / sampling_rate

        # Signal: 1 kHz tone, amplitude 1.0
        freq_tone = 1000.0
        signal = 1.0 * np.sin(2 * np.pi * freq_tone * t)

        # Noise: Gaussian white noise, sigma = 0.001 (-60 dB)
        noise_amp = 0.001
        np.random.seed(42) # Deterministic
        noise = np.random.normal(0, noise_amp, N)

        full_signal = signal + noise

        # Compute FFT
        # Use Blackman-Harris window as implied by comments in code, or just Rect for simplicity with exact bins
        # Code comments mention "Blackman-Harris main lobe is approx +/- 4 bins"
        # Let's use a window to be realistic
        window = np.blackman(N)
        # Apply window
        windowed_signal = full_signal * window

        # FFT
        fft_result = np.fft.rfft(windowed_signal)
        mag = np.abs(fft_result)
        freqs = np.fft.rfftfreq(N, 1/sampling_rate)

        # We need to normalize mag to represent linear amplitude correctly if we want absolute values,
        # but TDN is a ratio, so scaling cancels out.
        # However, for consistency:
        # mag = mag / (sum(window)/2) ... roughly.

        # Call function
        result = AudioCalc.calculate_multitone_tdn(mag, freqs, [freq_tone])

        # Expected:
        # Signal Power ~ 1.0^2 / 2 (RMS squared)
        # Noise Power ~ noise_amp^2
        # SNR ~ (1/2) / (0.001^2) = 0.5 / 1e-6 = 500,000
        # TDN ~ 1/sqrt(SNR) or Noise/Signal
        # Wait, the function sums squared magnitudes.
        # Parseval's theorem: sum(x^2) = (1/N) * sum(|X|^2)
        # So ratio of spectral energies is ratio of time domain energies.

        # Expected Noise RMS = noise_amp (since it's sigma of gaussian)
        # Expected Signal RMS = 1.0 / sqrt(2) = 0.707
        # TDN = Noise RMS / Signal RMS = 0.001 / 0.707 = 0.001414
        # TDN dB = 20 * log10(0.001414) = -56.99 dB

        # Note: Windowing affects noise bandwidth (ENBW).
        # Blackman window has ENBW ~ 1.73 bins.
        # But ratio should still be roughly correct.

        # Let's just check it's in the ballpark (e.g. -55 to -65 dB)
        self.assertTrue(-65.0 < result['tdn_db'] < -55.0, f"TDN {result['tdn_db']} dB not in expected range")

if __name__ == '__main__':
    unittest.main()
