import unittest
import numpy as np
from src.core.frequency_analysis import calculate_frequency_metrics


class TestFrequencyAnalysisCore(unittest.TestCase):
    def test_calculate_frequency_metrics_parameterized(self):
        """Test with different frequencies, sample rates, and amplitudes."""
        test_cases = [
            {"freq": 1000.0, "sr": 48000, "amp": 1.0, "gate": -60.0, "expected_db": -3.01},
            {"freq": 500.0, "sr": 44100, "amp": 0.5, "gate": -60.0, "expected_db": -9.03},
            {"freq": 100.0, "sr": 96000, "amp": 0.1, "gate": -60.0, "expected_db": -23.01},
            {"freq": 5000.0, "sr": 48000, "amp": 0.01, "gate": -60.0, "expected_db": -43.01},
            # Below gate threshold
            {"freq": 1000.0, "sr": 48000, "amp": 0.0001, "gate": -40.0, "expected_db": -83.01, "expected_freq": None},
        ]

        for tc in test_cases:
            with self.subTest(freq=tc["freq"], sr=tc["sr"], amp=tc["amp"]):
                t = np.arange(2048) / tc["sr"]
                signal = tc["amp"] * np.sin(2 * np.pi * tc["freq"] * t)
                freq, db = calculate_frequency_metrics(signal, tc["sr"], tc["gate"])

                self.assertAlmostEqual(db, tc["expected_db"], delta=0.5)

                if tc.get("expected_freq") is None and "expected_freq" in tc:
                    self.assertIsNone(freq)
                else:
                    self.assertIsNotNone(freq)
                    self.assertAlmostEqual(freq, tc["freq"], delta=10.0)

    def test_calculate_frequency_metrics_empty(self):
        with self.assertRaisesRegex(ValueError, "Empty audio data buffer"):
            calculate_frequency_metrics(np.array([]), 48000, -60.0)

    def test_calculate_frequency_metrics_calibration(self):
        t = np.arange(2048) / 48000
        signal = np.sin(2 * np.pi * 1000.0 * t)
        freq, db = calculate_frequency_metrics(signal, 48000, -60.0, calibration_factor=1.01)
        self.assertIsNotNone(freq)
        self.assertAlmostEqual(freq, 1010.0, delta=10.0)


if __name__ == "__main__":
    unittest.main()
