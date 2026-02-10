import unittest
import numpy as np
import warnings
from src.core.analysis import AudioCalc


class TestLockInComprehensive(unittest.TestCase):
    def setUp(self):
        self.fs = 48000
        self.freq = 1000.0
        self.N = 48000  # 1 second
        self.t = np.arange(self.N) / self.fs

    def test_basic_sine_waves(self):
        """Verify magnitude and phase for standard sine waves at 0, 90, 180, -90 degrees."""
        # 0 degrees
        signal = 1.0 * np.sin(2 * np.pi * self.freq * self.t)
        mag, phase = AudioCalc.calculate_lockin_measurement(signal, self.freq, self.fs)
        self.assertAlmostEqual(mag, 1.0, places=4)
        self.assertAlmostEqual(phase, 0.0, places=1)

        # 90 degrees
        signal = 1.0 * np.sin(2 * np.pi * self.freq * self.t + np.pi / 2)
        mag, phase = AudioCalc.calculate_lockin_measurement(signal, self.freq, self.fs)
        self.assertAlmostEqual(mag, 1.0, places=4)
        self.assertAlmostEqual(phase, 90.0, places=1)

        # 180 degrees
        signal = 1.0 * np.sin(2 * np.pi * self.freq * self.t + np.pi)
        mag, phase = AudioCalc.calculate_lockin_measurement(signal, self.freq, self.fs)
        self.assertAlmostEqual(mag, 1.0, places=4)
        # Phase can be 180 or -180 depending on float precision near the boundary
        self.assertTrue(abs(abs(phase) - 180.0) < 0.1, f"Phase {phase} should be +/- 180")

        # -90 degrees
        signal = 1.0 * np.sin(2 * np.pi * self.freq * self.t - np.pi / 2)
        mag, phase = AudioCalc.calculate_lockin_measurement(signal, self.freq, self.fs)
        self.assertAlmostEqual(mag, 1.0, places=4)
        self.assertAlmostEqual(phase, -90.0, places=1)

    def test_amplitude_linearity(self):
        """Verify that scaling input signal scales magnitude linearly."""
        amplitudes = [0.1, 0.5, 2.0, 10.0]
        for amp in amplitudes:
            signal = amp * np.sin(2 * np.pi * self.freq * self.t)
            mag, phase = AudioCalc.calculate_lockin_measurement(signal, self.freq, self.fs)
            self.assertAlmostEqual(mag, amp, places=4, msg=f"Failed for amplitude {amp}")
            self.assertAlmostEqual(phase, 0.0, places=1, msg=f"Failed phase for amplitude {amp}")

    def test_phase_reference(self):
        """Verify phase_ref parameter correctly shifts the measured phase."""
        # Signal phase 30 degrees
        signal_phase_deg = 30.0
        signal = 1.0 * np.sin(2 * np.pi * self.freq * self.t + np.radians(signal_phase_deg))

        # 1. Reference phase matching signal phase -> Measured phase should be 0
        ref_phase_deg = 30.0
        mag, phase = AudioCalc.calculate_lockin_measurement(
            signal, self.freq, self.fs, phase_ref=np.radians(ref_phase_deg)
        )
        self.assertAlmostEqual(mag, 1.0, places=4)
        self.assertAlmostEqual(phase, 0.0, places=1)

        # 2. Reference phase 0 -> Measured phase should be 30
        mag, phase = AudioCalc.calculate_lockin_measurement(
            signal, self.freq, self.fs, phase_ref=0.0
        )
        self.assertAlmostEqual(mag, 1.0, places=4)
        self.assertAlmostEqual(phase, 30.0, places=1)

        # 3. Reference phase 90 -> Measured phase should be -60 (30 - 90)
        ref_phase_deg = 90.0
        mag, phase = AudioCalc.calculate_lockin_measurement(
            signal, self.freq, self.fs, phase_ref=np.radians(ref_phase_deg)
        )
        self.assertAlmostEqual(mag, 1.0, places=4)
        self.assertAlmostEqual(phase, -60.0, places=1)

    def test_noise_rejection(self):
        """Verify rejection of orthogonal signals."""
        # Signal at 1kHz, Noise at 2kHz (orthogonal over integer cycles)
        signal = 1.0 * np.sin(2 * np.pi * self.freq * self.t)
        noise = 0.5 * np.sin(2 * np.pi * 2000.0 * self.t)
        combined = signal + noise

        mag, phase = AudioCalc.calculate_lockin_measurement(combined, self.freq, self.fs)
        self.assertAlmostEqual(mag, 1.0, places=3)
        self.assertAlmostEqual(phase, 0.0, places=1)

    def test_dc_rejection(self):
        """Verify rejection of DC offset."""
        signal = 1.0 * np.sin(2 * np.pi * self.freq * self.t)
        dc_offset = 0.5
        combined = signal + dc_offset

        mag, phase = AudioCalc.calculate_lockin_measurement(combined, self.freq, self.fs)
        self.assertAlmostEqual(mag, 1.0, places=3)
        self.assertAlmostEqual(phase, 0.0, places=1)

    def test_window_types(self):
        """Verify functionality with different window types."""
        signal = 1.0 * np.sin(2 * np.pi * self.freq * self.t)

        # Boxcar (Rectangular)
        mag, phase = AudioCalc.calculate_lockin_measurement(
            signal, self.freq, self.fs, window_name="boxcar"
        )
        self.assertAlmostEqual(mag, 1.0, places=4)
        self.assertAlmostEqual(phase, 0.0, places=1)

        # Blackman
        mag, phase = AudioCalc.calculate_lockin_measurement(
            signal, self.freq, self.fs, window_name="blackman"
        )
        self.assertAlmostEqual(mag, 1.0, places=3) # Windowing introduces some spectral leakage/gain variation if not perfectly aligned
        self.assertAlmostEqual(phase, 0.0, places=1)

    def test_frequency_mismatch(self):
        """Verify behavior with slight frequency mismatch."""
        # Signal slightly off frequency (1001 Hz vs 1000 Hz reference)
        signal_freq = 1001.0
        signal = 1.0 * np.sin(2 * np.pi * signal_freq * self.t)

        # Use boxcar window for perfect cancellation over 1 second (1 Hz difference)
        mag, phase = AudioCalc.calculate_lockin_measurement(
            signal, self.freq, self.fs, window_name="boxcar"
        )

        # 1 Hz difference over 1 second means exactly 1 full cycle phase drift.
        # Boxcar window should average this to 0.
        self.assertLess(mag, 0.001, "Should reject close frequency with boxcar window over full cycle")

        # Test with Hann window and 2 Hz difference (orthogonal to Hann window main lobe)
        signal_freq_2 = 1002.0
        signal_2 = 1.0 * np.sin(2 * np.pi * signal_freq_2 * self.t)
        mag_hann, _ = AudioCalc.calculate_lockin_measurement(
            signal_2, self.freq, self.fs, window_name="hann"
        )
        self.assertLess(mag_hann, 0.001, "Should reject 2Hz offset with Hann window over 1s")


    def test_short_signal(self):
        """Verify behavior with short signal."""
        N_short = 100
        t_short = np.arange(N_short) / self.fs
        signal = 1.0 * np.sin(2 * np.pi * self.freq * t_short)

        mag, phase = AudioCalc.calculate_lockin_measurement(signal, self.freq, self.fs)
        # With very short signal, windowing effects are significant, but basic functionality should hold.
        self.assertAlmostEqual(mag, 1.0, delta=0.1) # Allow more deviation

    def test_empty_signal(self):
        """Verify behavior with empty signal."""
        signal = np.array([])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                mag, phase = AudioCalc.calculate_lockin_measurement(signal, self.freq, self.fs)
                if np.isnan(mag) or np.isinf(mag):
                     pass # Acceptable
            except ZeroDivisionError:
                 pass # Acceptable
            except Exception as e:
                 self.fail(f"Raised unexpected exception: {e}")

if __name__ == "__main__":
    unittest.main()
