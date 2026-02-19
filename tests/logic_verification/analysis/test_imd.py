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

    def test_calculate_imd_ccif_negative_freq(self):
        """Test CCIF IMD with wide spacing causing negative 2*f1-f2 frequency."""
        f1 = 2000.0
        f2 = 5000.0
        # 2*f1 - f2 = -1000 Hz (wraps to 1000 Hz)
        # 2*f2 - f1 = 8000 Hz

        # Use synthetic magnitude spectrum directly to avoid windowing/aliasing issues in signal gen
        # and ensure precise amplitude injection.
        freqs = np.linspace(0, 10000, 10001)
        mag = np.zeros_like(freqs)

        idx_f1 = 2000
        idx_f2 = 5000
        idx_d3_low = 1000 # abs(2*2000 - 5000)
        idx_d3_high = 8000 # 2*5000 - 2000

        mag[idx_f1] = 1.0
        mag[idx_f2] = 1.0

        # Inject distortion
        dist_amp = 0.1
        mag[idx_d3_low] = dist_amp
        mag[idx_d3_high] = dist_amp

        # Calculate
        res = AudioCalc.calculate_imd_ccif(mag, freqs, f1, f2)

        # Expected:
        # Total Amp = 2.0
        # Distortion RMS = sqrt(0^2 + 0.1^2 + 0.1^2) = sqrt(0.02) = 0.14142
        # IMD = 0.14142 / 2.0 = 0.07071 (7.07%)

        self.assertAlmostEqual(res['imd'], 7.071, places=3)

    def test_calculate_pim_clean(self):
        """Test PIM calculation with clean carriers (should be very low)."""
        # Synthetic spectrum
        # 1Hz bins, up to 24kHz
        freqs = np.linspace(0, 24000, 24001)
        mag = np.zeros_like(freqs)

        f1 = 2000.0
        f2 = 3000.0

        idx_f1 = 2000
        idx_f2 = 3000

        mag[idx_f1] = 1.0
        mag[idx_f2] = 1.0

        res = AudioCalc.calculate_pim(mag, freqs, f1, f2)

        # Expect negligible PIM
        self.assertLess(res['pim_db'], -100.0)
        self.assertEqual(len(res['products']), 1)  # Order 3 loop runs
        self.assertEqual(res['products'][0]['amp_low'], 0.0)

    def test_calculate_pim_no_signal(self):
        """Test PIM calculation with no signal."""
        freqs = np.linspace(0, 24000, 24001)
        mag = np.zeros_like(freqs)

        res = AudioCalc.calculate_pim(mag, freqs, 1000.0, 2000.0)

        self.assertEqual(res['pim_db'], -100.0)
        self.assertEqual(res['products'], [])

    def test_calculate_pim_im3(self):
        """Test PIM calculation with known IM3 products."""
        freqs = np.linspace(0, 24000, 24001)
        mag = np.zeros_like(freqs)

        f1 = 2000.0
        f2 = 3000.0
        idx_f1 = 2000
        idx_f2 = 3000

        # Carriers
        mag[idx_f1] = 1.0
        mag[idx_f2] = 1.0

        # IM3: 2*f1 - f2 = 1000, 2*f2 - f1 = 4000
        idx_im3_low = 1000
        idx_im3_high = 4000

        im3_amp = 0.01
        mag[idx_im3_low] = im3_amp
        mag[idx_im3_high] = im3_amp

        res = AudioCalc.calculate_pim(mag, freqs, f1, f2, order=3)

        # Expected Calculation:
        # Carrier Amp = (1+1)/2 = 1.0
        # PIM RMS = sqrt(0.01^2 + 0.01^2) = sqrt(2e-4) = 0.0141421356
        # PIM dB = 20 * log10(0.0141421356) = -36.9897 dB

        expected_rms = np.sqrt(2 * (im3_amp**2))
        expected_db = 20 * np.log10(expected_rms)

        self.assertAlmostEqual(res['pim_db'], expected_db, places=3)
        self.assertEqual(len(res['products']), 1)
        self.assertAlmostEqual(res['products'][0]['amp_low'], im3_amp, places=6)
        self.assertAlmostEqual(res['products'][0]['amp_high'], im3_amp, places=6)

    def test_calculate_pim_im5(self):
        """Test PIM calculation with IM3 and IM5 products."""
        freqs = np.linspace(0, 24000, 24001)
        mag = np.zeros_like(freqs)

        f1 = 2000.0
        f2 = 3000.0

        # Carriers
        mag[2000] = 1.0
        mag[3000] = 1.0

        # IM3: 1000, 4000
        im3_amp = 0.01
        mag[1000] = im3_amp
        mag[4000] = im3_amp

        # IM5: 3*2000 - 2*3000 = 0.  (Index 0)
        # 3*3000 - 2*2000 = 5000.
        im5_amp = 0.005
        mag[0] = im5_amp
        mag[5000] = im5_amp

        # Calculate with order=5
        res = AudioCalc.calculate_pim(mag, freqs, f1, f2, order=5)

        # Expected RMS = sqrt(2*0.01^2 + 2*0.005^2)
        # = sqrt(2e-4 + 2*2.5e-5) = sqrt(2e-4 + 0.5e-4) = sqrt(2.5e-4) = 0.015811
        expected_rms = np.sqrt(2*(im3_amp**2) + 2*(im5_amp**2))
        expected_db = 20 * np.log10(expected_rms)

        self.assertAlmostEqual(res['pim_db'], expected_db, places=3)
        self.assertEqual(len(res['products']), 2) # Order 3 and Order 5

        # Check IM5 product details
        # products[0] is order 3, products[1] is order 5
        self.assertEqual(res['products'][1]['order'], 5)
        self.assertAlmostEqual(res['products'][1]['amp_low'], im5_amp, places=6)
        self.assertAlmostEqual(res['products'][1]['amp_high'], im5_amp, places=6)

        # Check filtering (if we run with order=3, IM5 should be ignored)
        res_order3 = AudioCalc.calculate_pim(mag, freqs, f1, f2, order=3)
        expected_rms_3 = np.sqrt(2 * (im3_amp**2))
        expected_db_3 = 20 * np.log10(expected_rms_3)
        self.assertAlmostEqual(res_order3['pim_db'], expected_db_3, places=3)
        self.assertEqual(len(res_order3['products']), 1)

    def test_calculate_pim_negative_freq(self):
        """Test PIM calculation where products wrap around DC (negative frequencies)."""
        freqs = np.linspace(0, 10000, 10001)
        mag = np.zeros_like(freqs)

        f1 = 2000.0
        f2 = 5000.0

        mag[2000] = 1.0
        mag[5000] = 1.0

        # IM3: 2*f1 - f2 = 4000 - 5000 = -1000 -> 1000
        # 2*f2 - f1 = 10000 - 2000 = 8000

        im3_amp = 0.01
        mag[1000] = im3_amp
        mag[8000] = im3_amp

        res = AudioCalc.calculate_pim(mag, freqs, f1, f2, order=3)

        expected_rms = np.sqrt(2 * (im3_amp**2))
        expected_db = 20 * np.log10(expected_rms)

        self.assertAlmostEqual(res['pim_db'], expected_db, places=3)

        # Check that it correctly identified the negative freq product at positive index
        prod = res['products'][0]
        self.assertEqual(prod['freq_low'], -1000.0)
        self.assertAlmostEqual(prod['amp_low'], im3_amp, places=6)
