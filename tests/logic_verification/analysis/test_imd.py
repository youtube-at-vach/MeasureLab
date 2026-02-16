import unittest
import numpy as np
from scipy.signal import get_window
from src.core.analysis import AudioCalc

class TestIMDAnalysis(unittest.TestCase):
    def setUp(self):
        # Setup for a 1 second signal at 48kHz
        self.sr = 48000
        self.N = 48000
        self.freqs = np.fft.rfftfreq(self.N, 1/self.sr)
        self.t = np.arange(self.N) / self.sr
        # Use Blackman-Harris window for good dynamic range (low side lobes)
        self.window = get_window('blackmanharris', self.N)
        self.coherent_gain = np.sum(self.window) / self.N

    def _get_mag(self, signal):
        """Helper to get magnitude spectrum scaled to peak amplitude."""
        fft_res = np.fft.rfft(signal * self.window)
        # Scale: |X|/N * 2 / coherent_gain
        return np.abs(fft_res) / self.N * 2 / self.coherent_gain

    def test_calculate_imd_smpte_clean(self):
        """Test SMPTE IMD calculation with a clean signal (should be ~0)."""
        # SMPTE Standard: 60Hz and 7kHz, 4:1 amplitude ratio
        f1 = 60.0
        f2 = 7000.0
        amp_f1 = 0.8
        amp_f2 = 0.2

        signal = amp_f1 * np.sin(2 * np.pi * f1 * self.t) + \
                 amp_f2 * np.sin(2 * np.pi * f2 * self.t)

        mag = self._get_mag(signal)

        result = AudioCalc.calculate_imd_smpte(mag, self.freqs, f1, f2)

        # Expect very low IMD (floating point noise + window leakage)
        # Should be below -100dB or very small percentage
        self.assertLess(result['imd'], 0.001)  # < 0.001%
        self.assertLess(result['imd_db'], -80.0)

    def test_calculate_imd_smpte_distortion(self):
        """Test SMPTE IMD calculation with known sidebands."""
        f1 = 60.0
        f2 = 7000.0
        amp_f1 = 0.8
        amp_f2 = 0.2

        # Inject sidebands at f2 +/- f1
        target_imd_percent = 1.0
        target_imd = target_imd_percent / 100.0

        # Solve for sideband amplitude to achieve exactly 1% IMD
        # IMD = sqrt(sum(sidebands^2)) / amp_f2
        # A_sb = (target_imd * amp_f2) / np.sqrt(2)
        A_sb = (target_imd * amp_f2) / np.sqrt(2)

        signal = amp_f1 * np.sin(2 * np.pi * f1 * self.t) + \
                 amp_f2 * np.sin(2 * np.pi * f2 * self.t) + \
                 A_sb * np.sin(2 * np.pi * (f2 - f1) * self.t) + \
                 A_sb * np.sin(2 * np.pi * (f2 + f1) * self.t)

        mag = self._get_mag(signal)

        result = AudioCalc.calculate_imd_smpte(mag, self.freqs, f1, f2)

        # Verify result is close to 1%
        self.assertAlmostEqual(result['imd'], target_imd_percent, delta=0.05)
        self.assertAlmostEqual(result['imd_db'], -40.0, delta=0.5)

    def test_calculate_imd_smpte_no_signal(self):
        """Test SMPTE IMD calculation with silence."""
        signal = np.zeros_like(self.t)
        mag = self._get_mag(signal)
        result = AudioCalc.calculate_imd_smpte(mag, self.freqs, 60.0, 7000.0)
        self.assertEqual(result['imd'], 0.0)
        self.assertEqual(result['imd_db'], -100.0)

    def test_calculate_imd_ccif(self):
        """Test CCIF IMD Calculation logic (from manual check)."""
        # CCIF: 19kHz and 20kHz, 1:1 amplitude
        f1 = 19000.0
        f2 = 20000.0
        amp = 0.25

        # Generate Clean Signal
        signal = amp * np.sin(2 * np.pi * f1 * self.t) + \
                 amp * np.sin(2 * np.pi * f2 * self.t)

        # Add IMD product (d2 = f2-f1 = 1kHz)
        # 1% of total amplitude (sum of carriers = 0.5)
        # Note: manual check used: imd_amp = (amp + amp) * 0.01 = 0.5 * 0.01 = 0.005
        imd_amp = (amp + amp) * 0.01
        signal += imd_amp * np.sin(2 * np.pi * (f2 - f1) * self.t)

        mag = self._get_mag(signal)

        res = AudioCalc.calculate_imd_ccif(mag, self.freqs, f1, f2)

        # Assertions
        # Expected ~1.0%
        # AudioCalc.calculate_imd_ccif likely calculates ratio of d2 to sum of carriers (or similar standard)
        self.assertAlmostEqual(res['imd'], 1.0, delta=0.1)
