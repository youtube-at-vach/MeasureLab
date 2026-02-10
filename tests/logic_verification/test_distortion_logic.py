import unittest
import numpy as np
from scipy.signal import get_window
from src.core.analysis import AudioCalc

class TestDistortionLogic(unittest.TestCase):
    def setUp(self):
        self.sr = 48000
        self.duration = 1.0
        self.t = np.linspace(0, self.duration, int(self.sr * self.duration), endpoint=False)

    # From test_thd_calculation.py
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

    # From test_thdn_edge_cases.py
    def test_thdn_sine_fit_small_n(self):
        """
        Test that calculate_thdn_sine_fit handles small N (< 8) without returning NaN.
        When N < 8, trim = N//8 = 0.
        The code currently executes residual[0:-0] which is empty, resulting in NaN.
        """
        sr = 48000
        # Create a simple sine wave
        t = np.linspace(0, 1, sr, endpoint=False)
        signal = np.sin(2 * np.pi * 1000 * t)

        # Test with N=7
        small_signal = signal[:7]
        thdn_db, fund_rms, noise_rms = AudioCalc.calculate_thdn_sine_fit(small_signal, sr, 1000)

        self.assertFalse(np.isnan(thdn_db), "THD+N should not be NaN for N=7")
        self.assertFalse(np.isnan(fund_rms), "Fund RMS should not be NaN for N=7")
        self.assertFalse(np.isnan(noise_rms), "Noise RMS should not be NaN for N=7")

    # From test_thdn_sine_fit_accuracy.py
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
        """Verify algorithm finds correct frequency even with poor initial guess."""
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
        """Verify how DC offset is handled."""
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
        self.assertLess(thdn_db, -40.0)

    # From test_advanced_distortion_logic.py
    def test_mim(self):
        """Test MIM (Multitone Intermodulation Distortion)."""
        sr = 48000
        N = 32768
        freqs = np.fft.rfftfreq(N, 1/sr)

        # Generate Multitone (3 tones)
        tones = [100, 1000, 5000]
        sig = np.zeros(N)
        t = np.arange(N) / sr
        for f in tones:
            sig += 0.1 * np.sin(2*np.pi*f*t)

        # Add noise
        noise = np.random.normal(0, 0.0001, N)
        sig += noise

        window = get_window('blackmanharris', N)
        fft_res = np.fft.rfft(sig * window)
        mag = np.abs(fft_res) * 2 / np.sum(window)

        res = AudioCalc.calculate_multitone_tdn(mag, freqs, tones)

        # Expected TD+N should be reasonably low (noise floor -80dB relative to signal)
        self.assertLess(res['tdn_db'], -40, "TD+N too high (expected low noise)")

    def test_spdr(self):
        """Test SPDR (Spurious-Free Dynamic Range)."""
        sr = 48000
        N = 32768
        freqs = np.fft.rfftfreq(N, 1/sr)

        # Fundamental 1kHz
        t = np.arange(N) / sr
        sig = 1.0 * np.sin(2*np.pi*1000*t)

        # Spur at 2.5kHz, -60dB
        sig += 0.001 * np.sin(2*np.pi*2500*t)

        window = get_window('blackmanharris', N)
        fft_res = np.fft.rfft(sig * window)
        mag = np.abs(fft_res) * 2 / np.sum(window)

        res = AudioCalc.calculate_spdr(mag, freqs, 1000.0)

        self.assertAlmostEqual(res['spdr_db'], 60, delta=1, msg=f"Expected ~60dB, got {res['spdr_db']:.2f}")

    def test_pim(self):
        """Test PIM (Passive Intermodulation) - simulated with math."""
        sr = 48000
        N = 32768
        freqs = np.fft.rfftfreq(N, 1/sr)

        f1 = 1800
        f2 = 2100
        t = np.arange(N) / sr

        # Carriers
        sig = 0.5 * np.sin(2*np.pi*f1*t) + 0.5 * np.sin(2*np.pi*f2*t)

        # IM3 Lower: 2f1 - f2 = 3600 - 2100 = 1500
        # IM3 Upper: 2f2 - f1 = 4200 - 1800 = 2400
        # Add IM3 at -80dBc (relative to 0.5) => 0.00005
        sig += 0.00005 * np.sin(2*np.pi*1500*t)
        sig += 0.00005 * np.sin(2*np.pi*2400*t)

        window = get_window('blackmanharris', N)
        fft_res = np.fft.rfft(sig * window)
        mag = np.abs(fft_res) * 2 / np.sum(window)

        res = AudioCalc.calculate_pim(mag, freqs, f1, f2)

        # Combined RMS of two -80dBc signals is -77dBc (3dB increase)
        self.assertAlmostEqual(res['pim_db'], -77, delta=2, msg=f"Expected ~-77dB, got {res['pim_db']:.2f}")

if __name__ == "__main__":
    unittest.main()
