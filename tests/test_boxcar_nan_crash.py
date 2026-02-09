
import numpy as np
import pytest
from src.gui.widgets.boxcar_averager import BoxcarAverager

class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000
        self.callbacks = {}

    def register_callback(self, cb):
        return 1

    def unregister_callback(self, cid):
        pass

def test_boxcar_int64_nan_handling():
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
        pytest.fail(f"Process crashed with: {e}")

    assert averager.count == 1
    # Check that NaNs were treated as 0
    # 0.5 * 2^31 = 1073741824
    expected = int(0.5 * 2147483648.0)

    # Index 10 (NaN) should be 0
    assert averager.accumulator[10, 0] == 0

    # Index 20 (Inf) should be max int? or handled? 
    # np.nan_to_num replaces Inf with large number. 
    # posinf=1.0, neginf=-1.0 was used in fix. So it should be 2^31.
    assert averager.accumulator[20, 1] == 2147483648

    # Index 30 (-Inf) -> -1.0 * 2^31
    assert averager.accumulator[30, 0] == -2147483648

    # Index 40 (0.5) -> expected
    assert averager.accumulator[40, 0] == expected
