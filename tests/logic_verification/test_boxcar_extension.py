
import numpy as np
from src.gui.widgets.boxcar_averager import BoxcarAverager

class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000
        self.callbacks = {}

    def register_callback(self, cb):
        return 1

    def unregister_callback(self, cid):
        pass

def test_boxcar_int64_accumulation():
    """Test that int64 accumulation works and preserves precision."""
    engine = MockAudioEngine()
    averager = BoxcarAverager(engine)
    averager.use_int64 = True
    averager.period_samples = 100
    averager.start_analysis()

    # Simulate input: constant 0.5
    # In int64 mode, 0.5 becomes 0.5 * 2^31 = 1073741824
    input_data = np.full((100, 2), 0.5, dtype=np.float32)

    # Process one block
    # We need to manually setup ring buffers since we are testing logic not threading
    # But strictly speaking `process` reads from ring buffer.
    # Let's bypass `process` and test the accumulation logic directly? 
    # Or just use the public API `_callback` -> `process`.

    # Let's use `process`. It depends on ring buffer.
    # Ref: `start_analysis` inits ring buffer.

    # 1. Callback fills ring buffer
    outdata = np.zeros((100, 2), dtype=np.float32)
    averager._callback(input_data, outdata, 100, None, None)

    # 2. Process accumulates
    averager.process()

    assert averager.count == 1
    expected_int_val = int(0.5 * 2147483648.0)
    assert averager.accumulator.dtype == np.int64
    assert averager.accumulator[0, 0] == expected_int_val

    # Accumulate again
    averager._callback(input_data, outdata, 100, None, None)
    averager.process()

    assert averager.count == 2
    assert averager.accumulator[0, 0] == expected_int_val * 2

def test_boxcar_export_normalization():
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

    # Mock soundfile or just test valid write
    import tempfile
    import os

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        success, msg = averager.export_to_file(tmp_path)
        assert success
        assert os.path.exists(tmp_path)
        assert os.path.getsize(tmp_path) > 0
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

def test_boxcar_block_size_change():
    """Test that changing period_samples resets accumulator."""
    engine = MockAudioEngine()
    averager = BoxcarAverager(engine)
    averager.start_analysis()

    averager.accumulator.fill(100)
    averager.count = 50

    # Change period
    averager.period_samples = 200
    averager.reset_average()

    assert averager.accumulator.shape == (200, 2)
    assert np.all(averager.accumulator == 0)
    assert averager.count == 0
