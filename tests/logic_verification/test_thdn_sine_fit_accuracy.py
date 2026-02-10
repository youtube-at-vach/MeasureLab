import unittest
import numpy as np
from src.core.analysis import AudioCalc

class TestTHDNSineFitAccuracy(unittest.TestCase):
    def setUp(self):
        self.sr = 48000
        self.duration = 1.0
        self.t = np.linspace(0, self.duration, int(self.sr * self.duration), endpoint=False)

    def test_pure_sine_wave(self):
        """Verify THD+N for a pure sine wave is very low."""
        freq = 1000.0
        signal = np.sin(2 * np.pi * freq * self.t)

        # Pure sine wave, no noise
        thdn_db, fund_rms, noise_rms = AudioCalc.calculate_thdn_sine_fit(signal, self.sr, freq)

        # Expected fundamental RMS: 1/sqrt(2) approx 0.707
        expected_rms = 1.0 / np.sqrt(2)
        self.assertAlmostEqual(fund_rms, expected_rms, places=4)

        # Expected THD+N: limited by numerical precision, should be very low
        # With 64-bit float, we expect better than -140dB usually, but let's be safe with -100dB
        self.assertLess(thdn_db, -100.0)
        # 1e-5 corresponds to roughly -117 dB relative to 0.707
        self.assertLess(noise_rms, 1e-5)

    def test_sine_with_gaussian_noise(self):
        """Verify THD+N matches expected SNR with Gaussian noise."""
        freq = 1000.0
        signal_amp = 1.0
        signal = signal_amp * np.sin(2 * np.pi * freq * self.t)

        # Desired SNR = 60 dB
        # SNR_dB = 20 * log10(Signal_RMS / Noise_RMS)
        # Noise_RMS = Signal_RMS / 10^(SNR/20)
        target_snr_db = 60.0
        signal_rms = signal_amp / np.sqrt(2)
        noise_rms_target = signal_rms / (10 ** (target_snr_db / 20))

        # Generate noise
        np.random.seed(42) # Deterministic
        noise = np.random.normal(0, noise_rms_target, size=len(signal))

        # Combine
        noisy_signal = signal + noise

        thdn_db, fund_rms, meas_noise_rms = AudioCalc.calculate_thdn_sine_fit(noisy_signal, self.sr, freq)

        # Verify Fundamental RMS
        self.assertAlmostEqual(fund_rms, signal_rms, delta=signal_rms * 0.01) # 1% tolerance

        # Verify Noise RMS
        # Note: Filter (20Hz-20kHz) removes some noise power.
        # White noise bandwidth is SR/2 = 24kHz.
        # Passband is ~20kHz.
        # Expected measured noise should be slightly less: noise_rms_target * sqrt(20000/24000)
        expected_meas_noise = noise_rms_target * np.sqrt(20000/24000)

        # Allow 10% tolerance on noise measurement due to randomness and filter characteristics
        self.assertAlmostEqual(meas_noise_rms, expected_meas_noise, delta=expected_meas_noise * 0.15)

        # Verify THD+N dB
        # THD+N = 20 * log10(Meas_Noise_RMS / Meas_Fund_RMS)
        expected_thdn = 20 * np.log10(expected_meas_noise / signal_rms)
        self.assertAlmostEqual(thdn_db, expected_thdn, delta=1.5) # Within 1.5 dB

    def test_frequency_optimization_robustness(self):
        """Verify algorithm finds correct frequency even with poor initial guess.

        Note: AudioCalc.optimize_frequency has a limited search range defined by
        max(5.0 * bin_width, 5.0). For N=48000, bin_width=1Hz, so search width is 5Hz.
        The guess must be within this range.
        """
        freq = 1000.0
        signal = np.sin(2 * np.pi * freq * self.t)

        # Guess 1002 Hz (within search range of 5Hz)
        guess = 1002.0

        thdn_db, fund_rms, noise_rms = AudioCalc.calculate_thdn_sine_fit(signal, self.sr, guess)

        # If optimization works, THD+N should be very low (similar to pure sine case)
        # If it fails, residual will be large -> high THD+N
        self.assertLess(thdn_db, -80.0)
        self.assertAlmostEqual(fund_rms, 1.0/np.sqrt(2), places=4)

    def test_dc_offset_handling(self):
        """Verify how DC offset is handled.

        The sine fitting includes a DC term, so fitted_fund will include DC.
        The residual will be (signal + DC) - (fitted_sine + fitted_DC) ~= 0.
        So THD+N (noise part) should be low.
        However, fund_rms is calculated from fitted_fund, so it will include DC power.
        """
        freq = 1000.0
        signal_amp = 1.0
        dc_offset = 0.5
        signal = signal_amp * np.sin(2 * np.pi * freq * self.t) + dc_offset

        thdn_db, fund_rms, noise_rms = AudioCalc.calculate_thdn_sine_fit(signal, self.sr, freq)

        # Expected fundamental RMS (including DC): sqrt(RMS_sine^2 + DC^2)
        expected_rms = np.sqrt((1.0/np.sqrt(2))**2 + dc_offset**2)

        self.assertAlmostEqual(fund_rms, expected_rms, places=4)

        # Noise should be low because DC is fitted and removed from residual
        self.assertLess(thdn_db, -80.0)

    def test_out_of_band_rejection(self):
        """Verify that 20Hz HPF and 20kHz LPF reject out-of-band noise."""
        freq = 1000.0
        signal = np.sin(2 * np.pi * freq * self.t)

        # Add 10 Hz noise (high amplitude)
        # 10 Hz is below 20 Hz HPF
        noise_10hz_amp = 0.1
        noise_10hz = noise_10hz_amp * np.sin(2 * np.pi * 10 * self.t)

        # Add 23 kHz noise (high amplitude)
        # 23 kHz is above 20 kHz LPF (Nyquist 24k)
        noise_23khz_amp = 0.1
        noise_23khz = noise_23khz_amp * np.sin(2 * np.pi * 23000 * self.t)

        noisy_signal = signal + noise_10hz + noise_23khz

        thdn_db, fund_rms, noise_rms = AudioCalc.calculate_thdn_sine_fit(noisy_signal, self.sr, freq)

        # The noise should be largely filtered out.
        # If not filtered, noise RMS would be approx sqrt(0.07^2 + 0.07^2) = 0.1.
        # Signal RMS is 0.707.
        # Unfiltered THD+N ~ -17 dB.

        # We expect significant attenuation.
        # 10Hz attenuation for 8th order HPF at 20Hz is huge (>40dB).
        # 23kHz attenuation for 8th order LPF at 20kHz is moderate (>10dB).

        # Let's expect at least -40dB THD+N, which confirms filters are doing something.
        # (Ideally much better, but 23k is close to 20k)

        self.assertLess(thdn_db, -40.0)

if __name__ == "__main__":
    unittest.main()
