import unittest
import sys
import os
import numpy as np

sys.path.append(os.getcwd())

from src.core.transmission_logic import (
    PRBSGenerator,
    find_sequence_delay,
    track_jitter,
    extract_impulse_response,
    extract_frequency_response,
    calculate_evm,
    calculate_equalized_evm,
    diagnose_bit_perfection,
    estimate_fractional_delay,
    shift_signal_fractional,
    track_jitter_fractional,
    calculate_step_response,
    analyze_step_transient,
)


class TestTransmissionLogic(unittest.TestCase):
    def test_prbs_generator_all_modes(self):
        """Test PRBS sequence generation, bounds and length for all PRBS7/9/15/23/31 modes."""
        modes = ["PRBS-7", "PRBS-9", "PRBS-15", "PRBS-23", "PRBS-31"]
        for mode in modes:
            gen = PRBSGenerator(mode=mode)
            self.assertEqual(gen.mode, mode)

            # Deterministic test
            seq1 = gen.generate_reference_sequence(100, bit_depth=24)
            seq2 = gen.generate_reference_sequence(100, bit_depth=24)
            self.assertEqual(len(seq1), 100)
            self.assertTrue(np.allclose(seq1, seq2))

            # Float bounds check
            self.assertTrue(np.max(seq1) <= 1.0)
            self.assertTrue(np.min(seq1) >= -1.0)

    def test_prbs_bit_depth_output(self):
        """Test 16-bit and 8-bit output variations."""
        gen = PRBSGenerator("PRBS-9")
        seq_16 = gen.generate_reference_sequence(50, bit_depth=16)
        seq_8 = gen.generate_reference_sequence(50, bit_depth=8)

        # Test ranges
        self.assertTrue(np.max(np.abs(seq_16)) <= 1.0)
        self.assertTrue(np.max(np.abs(seq_8)) <= 1.0)

    def test_find_sequence_delay(self):
        """Test delay sync estimation using sliding Pearson correlation."""
        gen = PRBSGenerator(mode="PRBS-9")
        ref_cycle = gen.generate_reference_sequence(511, bit_depth=24)

        # Shift signal
        delay = 45
        rx_segment = np.roll(ref_cycle, -delay)[:128]

        offset, corr = find_sequence_delay(rx_segment, ref_cycle)
        self.assertEqual(offset, delay)
        self.assertGreater(corr, 0.99)

        # Scale signal
        rx_scaled = rx_segment * 0.25
        offset_scaled, corr_scaled = find_sequence_delay(rx_scaled, ref_cycle)
        self.assertEqual(offset_scaled, delay)
        self.assertGreater(corr_scaled, 0.99)

    def test_track_jitter(self):
        """Test block-by-block phase/jitter tracking."""
        gen = PRBSGenerator(mode="PRBS-9")
        # Generate enough history
        tx_history = gen.generate_reference_sequence(1024, bit_depth=24)

        # Simulate initial lock
        last_offset = 200
        rx_block = tx_history[last_offset : last_offset + 128]

        # 1. Constant offset
        new_offset, corr = track_jitter(rx_block, tx_history, last_offset)
        self.assertEqual(new_offset, last_offset)
        self.assertGreater(corr, 0.99)

        # 2. Phase shift (+2 samples jitter)
        rx_shifted = tx_history[last_offset + 2 : last_offset + 130]
        shifted_offset, corr_shift = track_jitter(rx_shifted, tx_history, last_offset)
        self.assertEqual(shifted_offset, last_offset + 2)
        self.assertGreater(corr_shift, 0.99)

    def test_extract_impulse_response(self):
        """Test impulse response deconvolution."""
        gen = PRBSGenerator("PRBS-9")
        tx = gen.generate_reference_sequence(512, bit_depth=24)

        # Simple loopback (impulse at t=0)
        rx = tx.copy()

        h = extract_impulse_response(rx, tx)
        self.assertEqual(len(h), 512)

        # The peak of the impulse should be near index 0
        peak = np.argmax(np.abs(h))
        self.assertEqual(peak, 0)
        self.assertGreater(np.abs(h[0]), 0.5)

    def test_extract_frequency_response(self):
        """Test magnitude frequency response extraction."""
        gen = PRBSGenerator("PRBS-9")
        tx = gen.generate_reference_sequence(512, bit_depth=24)

        # Flat response loopback
        rx = tx.copy()

        freqs, mag_db = extract_frequency_response(rx, tx, 48000)
        self.assertEqual(len(freqs), 257)
        self.assertEqual(len(mag_db), 257)

        # Magnitude should be close to 0 dB across all frequencies
        self.assertTrue(np.all(np.abs(mag_db) < 1.0))

    def test_calculate_evm(self):
        """Test Error Vector Magnitude calculations."""
        gen = PRBSGenerator("PRBS-9")
        tx = gen.generate_reference_sequence(256, bit_depth=24)

        # 1. Exact copy should have ~0% EVM
        evm_perfect = calculate_evm(tx, tx)
        self.assertLess(evm_perfect, 0.01)

        # 2. Altered wave should have significant EVM
        rng = np.random.RandomState(42)
        rx_altered = tx + 0.1 * rng.normal(size=256)
        evm_noise = calculate_evm(rx_altered, tx)
        self.assertGreater(evm_noise, 1.0)

    def test_calculate_evm_zero_tx(self):
        """Test Error Vector Magnitude handles effectively zero tx_block inputs."""
        rx = np.ones(256)

        # Exact zero
        tx_zero = np.zeros(256)
        evm_zero = calculate_evm(rx, tx_zero)
        self.assertEqual(evm_zero, 100.0)

        # Tiny tx (dot product < 1e-12)
        # e.g., 256 * (1e-8)^2 = 256e-16 < 1e-12
        tx_tiny = np.ones(256) * 1e-8
        evm_tiny = calculate_evm(rx, tx_tiny)
        self.assertEqual(evm_tiny, 100.0)

    def test_calculate_equalized_evm(self):
        """Test Equalized EVM calculations under linear frequency/phase distortions."""
        gen = PRBSGenerator("PRBS-9")
        tx = gen.generate_reference_sequence(512, bit_depth=24)

        # 1. Exact copy should have ~0% EVM
        evm_perfect = calculate_equalized_evm(tx, tx)
        self.assertLess(evm_perfect, 0.01)

        # 2. Simulated linear amplitude distortion (simple high-frequency roll-off filter)
        # H(z) = 0.8 + 0.2*z^-1
        rx_linear = 0.8 * tx + 0.2 * np.roll(tx, 1)

        # Unequalized EVM should be high due to amplitude/phase mismatch
        evm_unequalized = calculate_evm(rx_linear, tx)
        self.assertGreater(evm_unequalized, 10.0)

        # Equalized EVM should dynamically correct the transfer response H and yield a very low EVM
        evm_equalized = calculate_equalized_evm(rx_linear, tx)
        self.assertLess(evm_equalized, 0.5)

        # 3. Altered wave with random noise (non-linear/additive noise distortion)
        # Add high noise with deterministic generator
        rng = np.random.RandomState(42)
        rx_noisy = rx_linear + 0.15 * rng.normal(size=512)
        evm_noisy_equalized = calculate_equalized_evm(rx_noisy, tx)

        # Noise cannot be corrected by linear equalization, so EVM should still reflect the noise level
        self.assertGreater(evm_noisy_equalized, 0.5)
        self.assertLess(evm_noisy_equalized, evm_unequalized)  # Equalization still removes linear part

    def test_diagnose_bit_perfection_success(self):
        """Test transparent bit-for-bit diagnosis."""
        gen = PRBSGenerator(mode="PRBS-9")
        ref = gen.generate_reference_sequence(512, bit_depth=24)
        rx = ref.copy()

        diag = diagnose_bit_perfection(rx, ref)
        self.assertTrue(diag["bit_perfect"])
        self.assertEqual(diag["gain_db"], 0.0)
        self.assertEqual(diag["bit_depth"], 24)
        self.assertEqual(diag["bit_errors"], 0)

    def test_diagnose_bit_perfection_gain(self):
        """Test volume scaling modification diagnostics."""
        gen = PRBSGenerator(mode="PRBS-9")
        ref = gen.generate_reference_sequence(512, bit_depth=24)

        # Scale by -6 dB
        rx = ref * 0.5

        diag = diagnose_bit_perfection(rx, ref)
        self.assertFalse(diag["bit_perfect"])
        self.assertAlmostEqual(diag["gain_db"], -6.02, places=2)
        self.assertEqual(diag["bit_depth"], 24)
        self.assertEqual(diag["dsp_detected"], "Volume/Gain Scaler")

    def test_diagnose_bit_perfection_truncation(self):
        """Test bit truncation detection (24 to 16 bit)."""
        gen = PRBSGenerator(mode="PRBS-9")
        ref = gen.generate_reference_sequence(512, bit_depth=24)

        # Truncate to 16 bit
        rx = np.round(ref * 32768.0) / 32768.0

        diag = diagnose_bit_perfection(rx, ref)
        self.assertFalse(diag["bit_perfect"])
        self.assertEqual(diag["bit_depth"], 16)
        self.assertEqual(diag["dsp_detected"], "Bit Truncation (16-bit)")

    def test_diagnose_bit_perfection_empty_array(self):
        """Test diagnose_bit_perfection with zero length inputs."""
        rx = np.array([])
        ref = np.array([])

        diag = diagnose_bit_perfection(rx, ref)
        self.assertFalse(diag["bit_perfect"])
        self.assertEqual(diag["reason"], "Empty input array.")
        self.assertEqual(diag["bit_depth"], 0)
        self.assertEqual(diag["bit_errors"], 0)
        self.assertEqual(diag["error_rate"], 0.0)

    def test_shift_signal_fractional(self):
        """Test that frequency domain fractional phase shifting acts as a perfect all-pass filter (preserves amplitude/energy)."""
        gen = PRBSGenerator("PRBS-9")
        tx = gen.generate_reference_sequence(512, bit_depth=24)

        # Shift by a non-integer sample delay
        shift_val = 0.45
        tx_shifted = shift_signal_fractional(tx, shift_val)

        # Verify length and shape
        self.assertEqual(len(tx_shifted), 512)

        # Energy/RMS check (places=3 to account for minor boundary circular-shift leakage)
        rms_orig = np.sqrt(np.mean(tx**2))
        rms_shifted = np.sqrt(np.mean(tx_shifted**2))
        self.assertAlmostEqual(rms_orig, rms_shifted, places=3)

        # Verify that the shift successfully introduced the exact fractional delay
        est_delay = estimate_fractional_delay(tx_shifted, tx)
        self.assertAlmostEqual(est_delay, shift_val, delta=0.02)

    def test_estimate_fractional_delay(self):
        """Test estimation accuracy of sub-sample delays using simulated fractional offsets, using clipping to avoid boundary leakage."""
        gen = PRBSGenerator("PRBS-9")
        # Generate longer sequence to clip margins and prevent circular convolution boundary leakage
        tx_long = gen.generate_reference_sequence(1024, bit_depth=24)

        target_shift = 0.55
        tx_long_delayed = shift_signal_fractional(tx_long, target_shift)

        # Extract middle portion
        tx_segment = tx_long[256:768]
        tx_delayed_segment = tx_long_delayed[256:768]

        est_delay = estimate_fractional_delay(tx_delayed_segment, tx_segment)
        self.assertAlmostEqual(est_delay, target_shift, delta=0.02)

        # Negative shift check
        target_shift_neg = -0.35
        tx_long_delayed_neg = shift_signal_fractional(tx_long, target_shift_neg)
        tx_delayed_neg_segment = tx_long_delayed_neg[256:768]
        est_delay_neg = estimate_fractional_delay(tx_delayed_neg_segment, tx_segment)
        self.assertAlmostEqual(est_delay_neg, target_shift_neg, delta=0.02)

    def test_track_jitter_fractional_empty_array(self):
        """Test track_jitter_fractional with empty input arrays."""
        rx_block = np.array([])
        tx_history = np.array([])
        last_offset = 50

        best_offset, frac_corr, frac_delay = track_jitter_fractional(rx_block, tx_history, last_offset)

        self.assertEqual(best_offset, last_offset)
        self.assertEqual(frac_corr, 0.0)
        self.assertEqual(frac_delay, 0.0)

    def test_track_jitter_fractional(self):
        """Test hybrid integer-fractional tracking under simulated drifts, validating exact integer and fractional recovery."""
        gen = PRBSGenerator("PRBS-9")
        tx_history = gen.generate_reference_sequence(1024, bit_depth=24)

        last_offset = 200
        target_int_offset = last_offset + 2  # 202
        target_frac_delay = 0.42  # Keep slightly below 0.50 so the nearest integer is unambiguously target_int_offset

        # 1. Extract clean integer-aligned reference block
        rx_block_clean = tx_history[target_int_offset : target_int_offset + 256]
        # 2. Directly apply precision fractional shift to this block
        rx_block = shift_signal_fractional(rx_block_clean, target_frac_delay)

        best_offset, frac_corr, frac_delay = track_jitter_fractional(rx_block, tx_history, last_offset)

        # Validate that the integer tracker locked exactly on the target integer offset
        self.assertEqual(best_offset, target_int_offset)
        # Validate that the fractional estimator accurately recovered the fractional shift
        self.assertAlmostEqual(frac_delay, target_frac_delay, delta=0.02)
        # Validate that the final fractional correlation is extremely high
        self.assertGreater(frac_corr, 0.98)

    def test_calculate_step_response(self):
        """Test step response calculation from impulse response."""
        h = np.zeros(128, dtype=np.float32)
        h[0] = 1.0

        step_resp = calculate_step_response(h)
        self.assertEqual(len(step_resp), 128)
        # 後半のステップ値の変化特性を確認
        self.assertAlmostEqual(step_resp[0], 0.0, delta=0.1)

    def test_analyze_step_transient(self):
        """Test transient response metrics analysis (overshoot, settling time, droop)."""
        # Simulate a clean step rising at index 128
        step_y = np.zeros(512, dtype=np.float32)
        step_y[128:] = 1.0

        # 1. Ideal step response
        res = analyze_step_transient(step_y, 48000)
        self.assertTrue(res["valid"])
        self.assertAlmostEqual(res["overshoot_pct"], 0.0, delta=0.1)
        self.assertEqual(res["settling_samples"], 0)
        self.assertAlmostEqual(res["droop_pct"], 0.0, delta=0.1)

        # 2. Step response with overshoot & ringing settling
        step_y_ring = np.zeros(512, dtype=np.float32)
        step_y_ring[128:] = 1.0
        step_y_ring[128:135] = 1.2  # 20% Overshoot
        step_y_ring[135:150] = 1.05  # Rings outside 2% tolerance band

        res_ring = analyze_step_transient(step_y_ring, 48000)
        self.assertTrue(res_ring["valid"])
        self.assertAlmostEqual(res_ring["overshoot_pct"], 20.0, delta=1.0)
        self.assertGreater(res_ring["settling_samples"], 20)

    def test_analyze_step_transient_with_delay(self):
        """Test transient response metrics under varying delays and input lengths (dynamic edge-detection)."""
        # 1. Delayed step response (rising at index 220 in a 512-sample array)
        step_delayed = np.zeros(512, dtype=np.float32)
        step_delayed[220:] = 1.0

        res_delayed = analyze_step_transient(step_delayed, 48000)
        self.assertTrue(res_delayed["valid"])
        self.assertAlmostEqual(res_delayed["overshoot_pct"], 0.0, delta=0.1)
        self.assertEqual(res_delayed["settling_samples"], 0)
        self.assertAlmostEqual(res_delayed["droop_pct"], 0.0, delta=0.1)

        # 2. Short array (256 samples) rising at index 80
        step_short = np.zeros(256, dtype=np.float32)
        step_short[80:] = 1.0

        res_short = analyze_step_transient(step_short, 48000)
        self.assertTrue(res_short["valid"])
        self.assertAlmostEqual(res_short["overshoot_pct"], 0.0, delta=0.1)
        self.assertEqual(res_short["settling_samples"], 0)
        self.assertAlmostEqual(res_short["droop_pct"], 0.0, delta=0.1)

        # 3. Step response with droop (e.g. exponential decay due to high-pass filter)
        step_decay = np.zeros(512, dtype=np.float32)
        # Rising at index 128
        step_decay[128:] = 1.0
        # Simulated droop: decay factor after rising edge
        decay_factor = np.exp(-np.arange(384) / 500.0)  # Decay to ~46% over 384 samples
        step_decay[128:] *= decay_factor

        res_decay = analyze_step_transient(step_decay, 48000)
        self.assertTrue(res_decay["valid"])
        # Droop should be successfully detected (non-zero)
        self.assertGreater(res_decay["droop_pct"], 5.0)
        self.assertLess(res_decay["droop_pct"], 100.0)


if __name__ == "__main__":
    unittest.main()
