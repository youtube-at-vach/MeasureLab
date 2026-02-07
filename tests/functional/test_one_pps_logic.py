
import numpy as np
import pytest
from unittest.mock import MagicMock

from src.gui.widgets.one_pps_monitor import OnePPSMonitor

class MockAudioEngine:
    def __init__(self):
        self.callbacks = {}
        self.next_id = 0
        self.sample_rate = 48000

    def register_callback(self, cb):
        cid = self.next_id
        self.next_id += 1
        self.callbacks[cid] = cb
        return cid

    def unregister_callback(self, cid):
        if cid in self.callbacks:
            del self.callbacks[cid]

def test_one_pps_logic():
    engine = MockAudioEngine()
    monitor = OnePPSMonitor(engine)
    
    # Configure
    monitor.threshold_fs = 0.5
    monitor.hysteresis_fs = 0.05
    monitor.start_analysis()
    
    callback = list(engine.callbacks.values())[0]
    
    # Generate synthetic signal
    # 48000 Hz sample rate
    # Pulses at index 1000, 49000 (delta = 48000)
    
    total_len = 100000
    sig = np.zeros(total_len, dtype=np.float32)
    
    # Pulse 1
    sig[1000:1010] = 0.8
    # Pulse 2
    sig[49000:49010] = 0.8
    # Pulse 3 (Short interval test) at 97005 (delta = 48005)
    sig[97005:97015] = 0.8
    
    # Process in blocks
    block_size = 1024
    
    for i in range(0, total_len, block_size):
        chunk = sig[i:i+block_size]
        # Make it stereo
        indata = np.column_stack((chunk, chunk))
        outdata = np.zeros_like(indata)
        
        callback(indata, outdata, len(chunk), None, None)
        
    # Verify results
    t, d = monitor.get_history_arrays()
    
    print(f"Detected deltas: {d}")
    
    assert len(d) == 2
    assert d[0] == 48000
    assert d[1] == 48005
    
def test_hysteresis():
    engine = MockAudioEngine()
    monitor = OnePPSMonitor(engine)
    monitor.threshold_fs = 0.5
    monitor.hysteresis_fs = 0.1 # High: 0.5, Low: 0.4
    monitor.start_analysis()
    
    callback = list(engine.callbacks.values())[0]
    
    # Construct a noisy signal near threshold
    # 1. Rise to 0.45 (Should not trigger)
    # 2. Rise to 0.55 (Trigger)
    # 3. Drop to 0.45 (Should not reset)
    # 4. Rise to 0.55 (Should not re-trigger)
    # 5. Drop to 0.35 (Reset)
    # 6. Rise to 0.55 (Trigger 2)
    
    sig = np.array([
        0.0, 0.45, 0.45,   # No trigger
        0.55, 0.6,         # Trigger 1 (idx 3)
        0.45, 0.45,        # No reset
        0.55, 0.6,         # No re-trigger
        0.35, 0.0,         # Reset
        0.55, 0.6          # Trigger 2 (idx 10)
    ], dtype=np.float32)
    
    # Feed sample by sample to be precise or small blocks
    indata = np.column_stack((sig, sig))
    outdata = np.zeros_like(indata)
    callback(indata, outdata, len(sig), None, None)
    
    # We need at least 2 pulses to get a delta. 
    # This test checks trigger state mostly.
    # But OnePPSMonitor only records deltas.
    # We can check internal state `_triggered`
    
    assert monitor._triggered == True
    assert monitor._last_trigger_sample_index == 11
