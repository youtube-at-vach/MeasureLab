import unittest
import numpy as np
from scipy.signal import get_window
from src.core.analysis import AudioCalc


class TestSPDRLogic(unittest.TestCase):
    def setUp(self):
        self.sr = 48000
        self.duration = 1.0
        self.N = int(self.sr * self.duration)
        self.t = np.arange(self.N) / self.sr
        self.freqs = np.fft.rfftfreq(self.N, 1 / self.sr)
        self.window = get_window("blackmanharris", self.N)

    def _get_spectrum(self, signal):
        windowed_signal = signal * self.window
        fft_res = np.fft.rfft(windowed_signal)
        # Normalize to peak amplitude
        mag = np.abs(fft_res) * 2 / np.sum(self.window)
        return mag

    def test_spdr_basic(self):
        """Test SPDR with a clear fundamental and a single spur."""
        fund_freq = 1000.0
        spur_freq = 2500.0
        spur_db = -60.0
        spur_amp = 10 ** (spur_db / 20)

        sig = np.sin(2 * np.pi * fund_freq * self.t)
        sig += spur_amp * np.sin(2 * np.pi * spur_freq * self.t)

        mag = self._get_spectrum(sig)
        res = AudioCalc.calculate_spdr(mag, self.freqs, fund_freq)

        self.assertAlmostEqual(res["spdr_db"], -spur_db, delta=1.0)
        self.assertAlmostEqual(res["max_spur_freq"], spur_freq, delta=self.sr / self.N)
        self.assertAlmostEqual(res["max_spur_amp"], spur_amp, delta=spur_amp * 0.1)

    def test_spdr_clean_signal(self):
        """Test SPDR with a clean sine wave (should be high)."""
        fund_freq = 1000.0
        sig = np.sin(2 * np.pi * fund_freq * self.t)

        mag = self._get_spectrum(sig)
        res = AudioCalc.calculate_spdr(mag, self.freqs, fund_freq)

        # Expected SPDR > 100dB (limited by window leakage and numerical noise)
        self.assertGreater(res["spdr_db"], 100.0)

    def test_spdr_no_fundamental(self):
        """Test SPDR when fundamental is missing (should return 0)."""
        fund_freq = 1000.0
        # Signal only has noise/spur
        sig = 0.001 * np.sin(2 * np.pi * 2500.0 * self.t)

        mag = self._get_spectrum(sig)
        # We tell it fundamental is at 1000, but there is none there
        res = AudioCalc.calculate_spdr(mag, self.freqs, fund_freq)

        self.assertEqual(res["spdr_db"], 0.0)
        self.assertEqual(res["max_spur_amp"], 0.0)

    def test_spdr_weak_fundamental(self):
        """Test SPDR when fundamental is too weak (< 1e-9)."""
        fund_freq = 1000.0
        weak_amp = 1e-10
        sig = weak_amp * np.sin(2 * np.pi * fund_freq * self.t)

        mag = self._get_spectrum(sig)
        res = AudioCalc.calculate_spdr(mag, self.freqs, fund_freq)

        self.assertEqual(res["spdr_db"], 0.0)

    def test_spdr_dc_rejection(self):
        """Test that DC component is ignored as a spur."""
        fund_freq = 1000.0
        spur_freq = 2500.0
        spur_db = -60.0
        spur_amp = 10 ** (spur_db / 20)

        # Add large DC offset
        dc_amp = 0.5
        sig = np.sin(2 * np.pi * fund_freq * self.t) + dc_amp
        sig += spur_amp * np.sin(2 * np.pi * spur_freq * self.t)

        mag = self._get_spectrum(sig)
        res = AudioCalc.calculate_spdr(mag, self.freqs, fund_freq)

        # Should still detect the spur at 2500Hz, not DC
        self.assertAlmostEqual(res["spdr_db"], -spur_db, delta=1.0)
        self.assertAlmostEqual(res["max_spur_freq"], spur_freq, delta=self.sr / self.N)

    def test_spdr_harmonic_vs_non_harmonic(self):
        """Test that SPDR picks the largest spur regardless of harmonic relationship."""
        fund_freq = 1000.0

        # Harmonic spur (2nd harmonic) at -70dB
        h2_freq = 2000.0
        h2_amp = 10 ** (-70 / 20)

        # Non-harmonic spur at -60dB (this should be picked)
        nh_freq = 2500.0
        nh_amp = 10 ** (-60 / 20)

        sig = np.sin(2 * np.pi * fund_freq * self.t)
        sig += h2_amp * np.sin(2 * np.pi * h2_freq * self.t)
        sig += nh_amp * np.sin(2 * np.pi * nh_freq * self.t)

        mag = self._get_spectrum(sig)
        res = AudioCalc.calculate_spdr(mag, self.freqs, fund_freq)

        self.assertAlmostEqual(res["spdr_db"], 60.0, delta=1.0)
        self.assertAlmostEqual(res["max_spur_freq"], nh_freq, delta=self.sr / self.N)

    def test_spdr_window_width(self):
        """Test that window_width_pct affects fundamental masking."""
        fund_freq = 1000.0
        # Create a "spur" very close to fundamental
        # If window is wide, it might be masked out (considered part of fundamental)
        # If window is narrow, it might be detected as spur

        # 1000Hz fundamental
        # 1050Hz close spur
        close_freq = 1050.0
        close_amp = 0.01  # -40dB

        sig = np.sin(2 * np.pi * fund_freq * self.t)
        sig += close_amp * np.sin(2 * np.pi * close_freq * self.t)

        mag = self._get_spectrum(sig)

        # Default window is 10% (100Hz width for 1000Hz fund).
        # +/- 100Hz around 1000Hz -> 900Hz to 1100Hz.
        # So 1050Hz should be masked out.
        res_wide = AudioCalc.calculate_spdr(mag, self.freqs, fund_freq, window_width_pct=0.1)
        # Should not find the 1050Hz spur, so SPDR should be high (finding next noise/spur)
        self.assertGreater(res_wide["spdr_db"], 80.0)

        # Narrow window: 1% (10Hz width).
        # +/- 10Hz -> 990Hz to 1010Hz.
        # 1050Hz should be detected as spur.
        res_narrow = AudioCalc.calculate_spdr(mag, self.freqs, fund_freq, window_width_pct=0.01)
        self.assertAlmostEqual(res_narrow["spdr_db"], 40.0, delta=1.0)
        self.assertAlmostEqual(res_narrow["max_spur_freq"], close_freq, delta=self.sr / self.N)


if __name__ == "__main__":
    unittest.main()
