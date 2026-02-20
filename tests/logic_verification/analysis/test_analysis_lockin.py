
import unittest
import numpy as np
from src.core.analysis import AudioCalc

class TestLockInMeasurement(unittest.TestCase):
    def test_basic_sine(self):
        fs = 48000
        freq = 1000.0
        N = 48000 # 1 sec
        t = np.arange(N) / fs

        # Test Case 1: 0 degrees phase
        signal = 1.0 * np.sin(2 * np.pi * freq * t)
        mag, phase = AudioCalc.calculate_lockin_measurement(signal, freq, fs)

        self.assertAlmostEqual(mag, 1.0, places=4)
        # Phase should be 0, but might be small noise
        self.assertAlmostEqual(phase, 0.0, places=1) # Allow slight jitter

        # Test Case 2: 90 degrees phase
        # sin(wt + 90) = cos(wt)
        signal = 1.0 * np.sin(2 * np.pi * freq * t + np.pi/2)
        mag, phase = AudioCalc.calculate_lockin_measurement(signal, freq, fs)
        self.assertAlmostEqual(mag, 1.0, places=4)
        self.assertAlmostEqual(phase, 90.0, places=1)

        # Test Case 3: 45 degrees
        signal = 0.5 * np.sin(2 * np.pi * freq * t + np.pi/4)
        mag, phase = AudioCalc.calculate_lockin_measurement(signal, freq, fs)
        self.assertAlmostEqual(mag, 0.5, places=4)
        self.assertAlmostEqual(phase, 45.0, places=1)

    def test_noise_rejection(self):
        fs = 48000
        freq = 1000.0
        N = 48000
        t = np.arange(N) / fs

        # Signal + Noise
        # Noise at 2000 Hz (Orthogonal ideally)
        noise = 0.5 * np.sin(2 * np.pi * 2000.0 * t)
        signal = 1.0 * np.sin(2 * np.pi * freq * t)

        combined = signal + noise

        mag, phase = AudioCalc.calculate_lockin_measurement(combined, freq, fs)

        # Should reject 2000 Hz
        self.assertAlmostEqual(mag, 1.0, places=3)
        self.assertAlmostEqual(phase, 0.0, places=1)

    def test_phase_ref(self):
        fs = 48000
        freq = 1000.0
        N = 4800
        t = np.arange(N) / fs

        # Signal has phase 30
        signal = 1.0 * np.sin(2 * np.pi * freq * t + np.radians(30))

        # If we measure with phase_ref = 30 deg (in radians),
        # the reference will align with signal.
        # ref_sin = sin(wt + ref)
        # ref_cos = cos(wt + ref)
        # mix_x = sin(wt+30) * sin(wt+30) -> DC is max
        # mix_y = sin(wt+30) * cos(wt+30) -> DC is 0
        # So Phase result should be 0 relative to reference!

        ref_rad = np.radians(30)
        mag, phase = AudioCalc.calculate_lockin_measurement(signal, freq, fs, phase_ref=ref_rad)

        self.assertAlmostEqual(mag, 1.0, places=4)
        self.assertAlmostEqual(phase, 0.0, places=1)

if __name__ == "__main__":
    unittest.main()
