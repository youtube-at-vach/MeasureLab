import unittest
import numpy as np
import os
import sys
import tempfile

# Ensure we can import from src
sys.path.append(os.getcwd())

from src.gui.widgets.boxcar_averager import BoxcarAverager

class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000
        self.callbacks = {}

    def register_callback(self, cb):
        return 1

    def unregister_callback(self, cid):
        pass

def _feed(boxcar: BoxcarAverager, frames: int, start_value: int):
    """Helper to feed deterministic input to boxcar."""
    left = np.arange(start_value, start_value + frames, dtype=float)
    right = np.zeros(frames, dtype=float)
    indata = np.column_stack((left, right))
    outdata = np.zeros_like(indata)
    boxcar._callback(indata, outdata, frames, 0, None)
    boxcar.process()

def _mls16_expected(n: int, seed: int = 0xACE1) -> np.ndarray:
    reg = seed & 0xFFFF
    if reg == 0:
        reg = 1
    out = np.empty((n,), dtype=np.float64)
    for i in range(n):
        lsb = reg & 1
        out[i] = 1.0 if lsb else -1.0
        reg >>= 1
        if lsb:
            reg ^= 0xB400
    return out

class TestBoxcarLogic(unittest.TestCase):

    # From test_boxcar_crash.py
    def test_boxcar_int64_nan_handling(self):
        """Test that int64 accumulation handles NaN/Inf without crashing."""
        engine = MockAudioEngine()
        averager = BoxcarAverager(engine)
        averager.use_int64 = True
        averager.period_samples = 100
        averager.start_analysis()

        # Create input with NaNs and Infs
        input_data = np.zeros((100, 2), dtype=np.float32)
        input_data[10, 0] = np.nan
        input_data[20, 1] = np.inf
        input_data[30, 0] = -np.inf
        input_data[40, :] = 0.5

        # 1. Callback fills ring buffer
        outdata = np.zeros((100, 2), dtype=np.float32)
        averager._callback(input_data, outdata, 100, None, None)

        # 2. Process accumulates - SHOULD NOT CRASH
        try:
            averager.process()
        except Exception as e:
            self.fail(f"Process crashed with: {e}")

        self.assertEqual(averager.count, 1)
        # Check that NaNs were treated as 0
        # 0.5 * 2^31 = 1073741824
        expected = int(0.5 * 2147483648.0)

        # Index 10 (NaN) should be 0
        self.assertEqual(averager.accumulator[10, 0], 0)

        # Index 20 (Inf) should be max int? or handled?
        self.assertEqual(averager.accumulator[20, 1], 2147483648)

        # Index 30 (-Inf) -> -1.0 * 2^31
        self.assertEqual(averager.accumulator[30, 0], -2147483648)

        # Index 40 (0.5) -> expected
        self.assertEqual(averager.accumulator[40, 0], expected)

    # From test_boxcar_gate.py
    def test_internal_gate_accumulates_only_within_window(self):
        engine = MockAudioEngine()
        boxcar = BoxcarAverager(engine)

        boxcar.mode = "Internal Pulse"
        boxcar.input_channel = "Left"
        boxcar.period_samples = 10

        boxcar.gate_enabled = True
        boxcar.gate_start_samples = 0
        boxcar.gate_length_samples = 3  # bins 0,1,2

        boxcar.start_analysis()

        # Two periods worth of samples: 0..19
        _feed(boxcar, frames=20, start_value=0)

        self.assertEqual(boxcar.count, 2)

        # Only bins 0..2 should have data.
        acc = boxcar.accumulator[:, 0]

        # For bin k: values were k (period0) and 10+k (period1)
        expected_acc = np.zeros(10, dtype=float)
        expected_acc[0:3] = np.array([0 + 10, 1 + 11, 2 + 12], dtype=float)

        np.testing.assert_allclose(acc, expected_acc, rtol=0, atol=1e-12)

    def test_internal_gate_wraps_across_period_end(self):
        engine = MockAudioEngine()
        boxcar = BoxcarAverager(engine)

        boxcar.mode = "Internal Pulse"
        boxcar.input_channel = "Left"
        boxcar.period_samples = 10

        boxcar.gate_enabled = True
        boxcar.gate_start_samples = 8
        boxcar.gate_length_samples = 4  # bins 8,9,0,1

        boxcar.start_analysis()

        _feed(boxcar, frames=20, start_value=0)

        self.assertEqual(boxcar.count, 2)

        acc = boxcar.accumulator[:, 0]

        expected_acc = np.zeros(10, dtype=float)
        # bin8: 8 and 18
        expected_acc[8] = 8 + 18
        # bin9: 9 and 19
        expected_acc[9] = 9 + 19
        # bin0: 0 and 10
        expected_acc[0] = 0 + 10
        # bin1: 1 and 11
        expected_acc[1] = 1 + 11

        np.testing.assert_allclose(acc, expected_acc, rtol=0, atol=1e-12)

    # From test_boxcar_ref_sync.py
    def test_boxcar_ref_sync(self):
        engine = MockAudioEngine()
        boxcar = BoxcarAverager(engine)

        # Setup
        boxcar.mode = 'External Reference'
        boxcar.ref_channel = 1 # Right
        boxcar.input_channel = 'Left'
        boxcar.period_samples = 100
        boxcar.trigger_level = 0.0
        boxcar.trigger_edge = 'Rising'

        boxcar.start_analysis()

        # Create Test Data
        frames = 1000

        # Ref: Rising edge at 50, 250, 450...
        ref = np.zeros(frames)
        ref[50:150] = 1.0
        ref[250:350] = 1.0
        ref[450:550] = 1.0
        ref[650:750] = 1.0
        ref[850:950] = 1.0
        ref -= 0.5 # Center at 0

        # Sig: Ramp 0 to 1 over 100 samples starting at trigger
        sig = np.zeros(frames)

        # Fill signal segments corresponding to triggers
        for start in [50, 250, 450, 650, 850]:
            sig[start:start+100] = np.linspace(0, 1, 100)

        data = np.column_stack((sig, ref))

        # Feed data to callback
        outdata = np.zeros_like(data)
        boxcar._callback(data, outdata, frames, 0, None)

        # Process
        boxcar.process()

        self.assertEqual(boxcar.count, 5) # Should have captured 5 windows

        # Check Accumulator
        # Should be sum of 5 ramps -> 5 * linspace(0, 1, 100)
        expected = np.linspace(0, 1, 100) * 5

        # Accumulator is (period, 2)
        # We recorded Left channel
        acc_l = boxcar.accumulator[:, 0]

        # Verify
        diff = np.abs(acc_l - expected)
        max_diff = np.max(diff)
        self.assertLess(max_diff, 1e-5)

    # From test_boxcar_window_stability.py
    def test_internal_reset_keeps_window_aligned_to_absolute_period_boundary(self):
        engine = MockAudioEngine()
        boxcar = BoxcarAverager(engine)

        boxcar.mode = "Internal Pulse"
        boxcar.input_channel = "Left"
        boxcar.period_samples = 10

        boxcar.start_analysis()

        # Feed 7 samples: indices 0..6
        _feed(boxcar, frames=7, start_value=0)

        # Reset mid-stream. The next accumulation should start at the next period boundary
        # (absolute index 10), not at the next processed chunk boundary.
        boxcar.reset_average()

        # Feed indices 7..13 then 14..19. The reset logic should skip 7..9,
        # and the first full accumulated period should be exactly 10..19.
        _feed(boxcar, frames=7, start_value=7)
        _feed(boxcar, frames=6, start_value=14)

        self.assertEqual(boxcar.count, 1)

        expected = np.arange(10, 20, dtype=float)
        got = boxcar.accumulator[:, 0] / boxcar.count

        np.testing.assert_allclose(got, expected, rtol=0, atol=1e-12)

    # From test_boxcar_extension.py
    def test_boxcar_int64_accumulation(self):
        """Test that int64 accumulation works and preserves precision."""
        engine = MockAudioEngine()
        averager = BoxcarAverager(engine)
        averager.use_int64 = True
        averager.period_samples = 100
        averager.start_analysis()

        # Simulate input: constant 0.5
        input_data = np.full((100, 2), 0.5, dtype=np.float32)

        # 1. Callback fills ring buffer
        outdata = np.zeros((100, 2), dtype=np.float32)
        averager._callback(input_data, outdata, 100, None, None)

        # 2. Process accumulates
        averager.process()

        self.assertEqual(averager.count, 1)
        expected_int_val = int(0.5 * 2147483648.0)
        self.assertEqual(averager.accumulator.dtype, np.int64)
        self.assertEqual(averager.accumulator[0, 0], expected_int_val)

        # Accumulate again
        averager._callback(input_data, outdata, 100, None, None)
        averager.process()

        self.assertEqual(averager.count, 2)
        self.assertEqual(averager.accumulator[0, 0], expected_int_val * 2)

    def test_boxcar_export_normalization(self):
        """Test that export converts int64 back to float correctly."""
        engine = MockAudioEngine()
        averager = BoxcarAverager(engine)
        averager.use_int64 = True
        averager.period_samples = 10
        averager.start_analysis()

        # Manually seed accumulator
        averager.count = 2
        # Value corresponding to 0.75
        val_int = int(0.75 * 2147483648.0) * 2
        averager.accumulator.fill(val_int)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            success, msg = averager.export_to_file(tmp_path)
            self.assertTrue(success)
            self.assertTrue(os.path.exists(tmp_path))
            self.assertGreater(os.path.getsize(tmp_path), 0)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_boxcar_block_size_change(self):
        """Test that changing period_samples resets accumulator."""
        engine = MockAudioEngine()
        averager = BoxcarAverager(engine)
        averager.start_analysis()

        averager.accumulator.fill(100)
        averager.count = 50

        # Change period
        averager.period_samples = 200
        averager.reset_average()

        self.assertEqual(averager.accumulator.shape, (200, 2))
        self.assertTrue(np.all(averager.accumulator == 0))
        self.assertEqual(averager.count, 0)

    # From test_boxcar_freerun.py
    def test_boxcar_freerun_accumulation(self):
        """Test that Free Run mode accumulates data without triggers."""
        engine = MockAudioEngine()
        averager = BoxcarAverager(engine)
        averager.mode = "External Reference"
        averager.trigger_edge = "Free Run"
        averager.ref_channel = 1
        averager.period_samples = 100
        averager.start_analysis()

        # Create input data (e.g., constant DC, no edges)
        # 200 samples (2 blocks worth)
        input_data = np.ones((200, 2), dtype=np.float32) * 0.5

        # 1. Callback fills ring buffer
        outdata = np.zeros((200, 2), dtype=np.float32)
        averager._callback(input_data, outdata, 200, None, None)

        # 2. Process accumulates
        averager.process()

        # Should have accumulated 2 blocks
        self.assertEqual(averager.count, 2)

        # Check accumulator value
        # Each sample accumulated 2 times (once per block)
        # Value is 0.5
        # averager.accumulator is float64 by default (use_int64=False by default)
        # Expected value: 0.5 + 0.5 = 1.0
        np.testing.assert_allclose(averager.accumulator, 1.0)

    def test_boxcar_freerun_int64_accumulation(self):
        """Test Free Run mode with Int64 accumulation."""
        engine = MockAudioEngine()
        averager = BoxcarAverager(engine)
        averager.mode = "External Reference"
        averager.trigger_edge = "Free Run"
        averager.use_int64 = True
        averager.period_samples = 50
        averager.start_analysis()

        # 150 samples (3 blocks)
        input_data = np.ones((150, 2), dtype=np.float32) * 0.25
        outdata = np.zeros((150, 2), dtype=np.float32)
        averager._callback(input_data, outdata, 150, None, None)

        averager.process()

        self.assertEqual(averager.count, 3)

        # Expected int64 value:
        # 0.25 * 2^31 = 536870912
        # Accumulated 3 times = 1610612736
        expected = int(0.25 * 2147483648.0) * 3
        np.testing.assert_allclose(averager.accumulator, expected)

    # From test_boxcar_internal_generators.py
    def test_internal_impulse_is_one_sample_per_period(self):
        engine = MockAudioEngine()
        boxcar = BoxcarAverager(engine)
        boxcar.mode = "Internal Impulse"
        boxcar.input_channel = "Left"
        boxcar.period_samples = 8

        boxcar.start_analysis()

        frames = 8
        indata = np.zeros((frames, 2), dtype=float)

        out = np.zeros_like(indata)
        boxcar._callback(indata, out, frames, 0, None)

        expected = np.zeros(frames, dtype=float)
        expected[0] = 0.5
        np.testing.assert_allclose(out[:, 0], expected, rtol=0, atol=1e-12)

        # Next period should repeat impulse at first sample again
        out2 = np.zeros_like(indata)
        boxcar._callback(indata, out2, frames, 0, None)
        np.testing.assert_allclose(out2[:, 0], expected, rtol=0, atol=1e-12)

    def test_internal_prbs_mls_repeats_per_period_deterministically(self):
        engine = MockAudioEngine()
        boxcar = BoxcarAverager(engine)
        boxcar.mode = "Internal PRBS/MLS"
        boxcar.input_channel = "Left"
        boxcar.period_samples = 8

        boxcar.start_analysis()

        frames = 8
        indata = np.zeros((frames, 2), dtype=float)

        out = np.zeros_like(indata)
        boxcar._callback(indata, out, frames, 0, None)

        mls = _mls16_expected(8)
        expected = 0.5 * mls
        np.testing.assert_allclose(out[:, 0], expected, rtol=0, atol=1e-12)

        # Next period should repeat the same cached sequence
        out2 = np.zeros_like(indata)
        boxcar._callback(indata, out2, frames, 0, None)
        np.testing.assert_allclose(out2[:, 0], expected, rtol=0, atol=1e-12)

if __name__ == '__main__':
    unittest.main()
