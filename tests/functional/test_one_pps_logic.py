
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

def test_outlier_rejection():
    engine = MockAudioEngine()
    monitor = OnePPSMonitor(engine)
    monitor.threshold_fs = 0.5
    monitor.nominal_rate = 1000.0
    
    # Enable filter
    monitor.filter_enabled = True
    monitor.filter_window_size = 5
    monitor.filter_tolerance_sigma = 3.0
    
    monitor.start_analysis()
    
    callback = list(engine.callbacks.values())[0]
    
    # Sequence of deltas to simulate:
    # 1000, 1000, 1000, 1000, 1000 (Set baseline)
    # 2000 (Outlier -> Reject)
    # 1000 (Normal -> Accept)
    
    # We need to craft signal to produce these deltas.
    # Signal: High for 1 sample every N samples.
    
    deltas = [1000, 1000, 1000, 1000, 1000, 2000, 1000]
    
    # Construct signal
    total_len = sum(deltas) + 2000 # padding
    sig = np.zeros(total_len, dtype=np.float32)
    
    current_idx = 100 # start offset
    
    # Pulse 0 (Reference)
    sig[current_idx] = 1.0
    
    pulse_indices = [current_idx]
    
    for d in deltas:
        current_idx += d
        sig[current_idx] = 1.0
        pulse_indices.append(current_idx)
        
    # Process
    indata = np.column_stack((sig, sig))
    outdata = np.zeros_like(indata)
    callback(indata, outdata, len(sig), None, None)
    
    t, d = monitor.get_history_arrays()
    
    print(f"Stored Deltas: {d}")
    
    # We expect the 5 initial 1000s to be accepted.
    # The 6th delta (2000) should be REJECTED.
    # The 7th delta (1000) should be ACCEPTED.
    # Result should have 6 items, all 1000.
    
    # Note on outlier filter:
    # Window needs to fill up first?
    # Logic: if len(window) >= size: filter.
    # Prior to window filling, all accepted.
    # After 5 samples (1000, 1000, 1000, 1000, 1000), window is full. Med=1000, MAD=0.
    # Threshold = max(0 * 3, 1.0) = 1.0. 
    # Next is 2000. Abs(2000-1000) = 1000 > 1.0. REJECT.
    # Next is 1000. Abs(1000-1000) = 0 < 1.0. ACCEPT.
    
    assert len(d) == 6
    assert np.all(d == 1000.0)
