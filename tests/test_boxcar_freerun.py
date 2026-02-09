
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

def test_boxcar_freerun_accumulation():
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
    assert averager.count == 2
    
    # Check accumulator value
    # Each sample accumulated 2 times (once per block)
    # Value is 0.5
    # averager.accumulator is float64 by default (use_int64=False by default)
    # Expected value: 0.5 + 0.5 = 1.0
    assert np.allclose(averager.accumulator, 1.0)

def test_boxcar_freerun_int64_accumulation():
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
    
    assert averager.count == 3
    
    # Expected int64 value: 
    # 0.25 * 2^31 = 536870912
    # Accumulated 3 times = 1610612736
    expected = int(0.25 * 2147483648.0) * 3
    assert np.allclose(averager.accumulator, expected)
