import unittest
import sys
import os
import numpy as np

sys.path.append(os.getcwd())

from src.core.bit_perfect_logic import PRBSGenerator, find_sequence_delay, diagnose_bit_perfection

class TestBitPerfectLogic(unittest.TestCase):
    def test_prbs_generator_basic(self):
        """Test PRBS sequence generation and deterministic outputs."""
        gen15 = PRBSGenerator(mode="PRBS-15")
        gen9 = PRBSGenerator(mode="PRBS-9")

        # Test PRBS-15 sequence reproducibility
        seq1 = gen15.generate_reference_sequence(100, bit_depth=24)
        seq2 = gen15.generate_reference_sequence(100, bit_depth=24)
        self.assertEqual(len(seq1), 100)
        self.assertTrue(np.allclose(seq1, seq2))

        # Test PRBS-9 sequence reproducibility
        seq9_1 = gen9.generate_reference_sequence(100, bit_depth=16)
        seq9_2 = gen9.generate_reference_sequence(100, bit_depth=16)
        self.assertEqual(len(seq9_1), 100)
        self.assertTrue(np.allclose(seq9_1, seq9_2))

        # Test 16-bit vs 24-bit range
        seq_16 = gen15.generate_reference_sequence(100, bit_depth=16)
        self.assertTrue(np.max(np.abs(seq_16)) <= 1.0)
        self.assertTrue(np.min(np.abs(seq_16)) >= 0.0)

    def test_find_sequence_delay(self):
        """Test delay estimation via normalized cross-correlation."""
        gen = PRBSGenerator(mode="PRBS-15")
        ref_cycle = gen.generate_reference_sequence(32767, bit_depth=24)

        # Simulate delay (recorded signal starts later, so rx[0] corresponds to ref[delay])
        delay = 1234
        rx_segment = np.roll(ref_cycle, -delay)[:1024]

        offset, corr = find_sequence_delay(rx_segment, ref_cycle)
        self.assertEqual(offset, delay)
        self.assertGreater(corr, 0.99)

        # Delayed + scaled volume
        rx_segment_scaled = rx_segment * 0.5
        offset_scaled, corr_scaled = find_sequence_delay(rx_segment_scaled, ref_cycle)
        self.assertEqual(offset_scaled, delay)
        self.assertGreater(corr_scaled, 0.99)

    def test_diagnose_bit_perfection_success(self):
        """Test perfect bit-for-bit match diagnosis."""
        gen = PRBSGenerator(mode="PRBS-15")
        ref = gen.generate_reference_sequence(1024, bit_depth=24)
        rx = ref.copy()

        diag = diagnose_bit_perfection(rx, ref)
        self.assertTrue(diag["bit_perfect"])
        self.assertEqual(diag["gain_db"], 0.0)
        self.assertEqual(diag["bit_depth"], 24)
        self.assertEqual(diag["bit_errors"], 0)

    def test_diagnose_bit_perfection_gain(self):
        """Test diagnosis of volume gain modification (Not Bit-Perfect)."""
        gen = PRBSGenerator(mode="PRBS-15")
        ref = gen.generate_reference_sequence(1024, bit_depth=24)

        # Scale volume by -3 dB
        scale = 10**(-3.0 / 20.0)
        rx = ref * scale

        diag = diagnose_bit_perfection(rx, ref)
        self.assertFalse(diag["bit_perfect"])
        self.assertAlmostEqual(diag["gain_db"], -3.0, places=2)
        self.assertEqual(diag["bit_depth"], 24)

    def test_diagnose_bit_perfection_truncation(self):
        """Test bit truncation detection (e.g. 24-bit truncated to 16-bit)."""
        gen = PRBSGenerator(mode="PRBS-15")
        ref = gen.generate_reference_sequence(1024, bit_depth=24)

        # Truncate ref to 16-bit
        rx = np.round(ref * 32768.0) / 32768.0

        diag = diagnose_bit_perfection(rx, ref)
        self.assertFalse(diag["bit_perfect"])
        self.assertEqual(diag["bit_depth"], 16)
        self.assertIn("16-bit", diag["reason"])

    def test_diagnose_bit_perfection_heavy_alteration(self):
        """Test heavily altered signals (e.g. processing or resampling)."""
        gen = PRBSGenerator(mode="PRBS-15")
        ref = gen.generate_reference_sequence(1024, bit_depth=24)
        rx = np.sin(ref) # Non-linear distortion

        diag = diagnose_bit_perfection(rx, ref)
        self.assertFalse(diag["bit_perfect"])
        self.assertEqual(diag["bit_depth"], 0)
        self.assertIn("Signal altered", diag["reason"])

if __name__ == "__main__":
    unittest.main()
