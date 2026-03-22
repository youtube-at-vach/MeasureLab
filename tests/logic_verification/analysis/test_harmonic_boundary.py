import unittest
import numpy as np
from src.core.analysis import AudioCalc


class TestHarmonicBoundary(unittest.TestCase):
    def test_harmonic_near_nyquist(self):
        # Setup: Freqs up to 100Hz.
        # Fundamental at 49.5Hz.
        # 2nd Harmonic at 99.0Hz.
        # SR = 200. Nyquist = 100.
        # Harmonic < Nyquist.

        freqs = np.array([0.0, 49.5, 99.0, 100.0])
        # Spectrum: Peak at 49.5Hz and 99.0Hz.
        amplitude_spectrum = np.array([0.0, 1.0, 0.5, 0.0])

        max_freq = 49.5
        max_amplitude = 1.0
        sampling_rate = 200.0
        search_window = 5.0  # Window +/- 5Hz.
        min_db = -100.0

        # Harmonic 2: 99.0Hz.
        # Window: 94.0 - 104.0.
        # searchsorted(freqs, 94.0) -> index 2 (99.0).
        # searchsorted(freqs, 104.0) -> index 4 (len).

        # Original code:
        # h_idx_max = 4. len = 4.
        # if 4 < 4: False. Harmonic skipped.

        # Fixed code:
        # if 4 <= 4: True.
        # subset = amp[2:4] -> [0.5, 0.0].
        # argmax -> 0.
        # found.

        results, amplitudes = AudioCalc._analyze_harmonics_list(
            freqs, amplitude_spectrum, max_freq, max_amplitude, sampling_rate, search_window, min_db
        )

        # Check if harmonic 2 is found
        found_harmonic_2 = False
        for h in results:
            if h["order"] == 2:
                if h["amplitude_linear"] > 0:
                    found_harmonic_2 = True
                    self.assertAlmostEqual(h["amplitude_linear"], 0.5)

        if not found_harmonic_2:
            print("\nBug reproduced: 2nd harmonic near Nyquist was not detected.")
        else:
            print("\nTest passed: 2nd harmonic detected.")

        self.assertTrue(found_harmonic_2, "Harmonic near Nyquist should be detected")


if __name__ == "__main__":
    unittest.main()
