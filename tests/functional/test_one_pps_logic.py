
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
    # Pulses at index 1000, 49000 (delta = 48000) -> 0 PPM
    # Pulse 3 at 97005 (delta = 48005) -> +104.16 PPM
    
    total_len = 100000
    sig = np.zeros(total_len, dtype=np.float32)
    
    # Pulse 1 (Start)
    sig[1000:1010] = 0.8
    # Pulse 2 (48000 samples later)
    sig[49000:49010] = 0.8
    # Pulse 3 (48005 samples later)
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
    t, ip, cp = monitor.get_history_arrays()
    
    print(f"Detected IP: {ip}")
    print(f"Detected CP: {cp}")
    
    assert len(ip) == 2
    # First interval: 48000 -> 0 error -> 0 ppm
    assert ip[0] == 0.0
    
    # Second interval: 48005 -> 5 error -> (5/48000)*1e6 = 104.166...
    expected_ppm = (5 / 48000.0) * 1e6
    assert abs(ip[1] - expected_ppm) < 0.01
    
    # Cumulative check
    # Total samples = 48000 + 48005 = 96005
    # Total seconds = round(96005/48000) = 2
    # Avg Rate = 96005 / 2 = 48002.5
    # Error = 2.5
    # CP = (2.5 / 48000) * 1e6 = 52.0833...
    expected_cp = (2.5 / 48000.0) * 1e6
    assert abs(cp[1] - expected_cp) < 0.01
    
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
    
    # OnePPSMonitor only records deltas (needs 3 pulses for 2 intervals, or 2 pulses for 1 interval)
    # Here we have 2 pulses (Trigger 1 and Trigger 2).
    # This gives 1 interval.
    # Pulse 1 at 3. Pulse 2 at 10. Delta = 7.
    
    t, ip, cp = monitor.get_history_arrays()
    assert len(ip) == 1
    
    # Nominal is 48000 default. Delta 7 is huge negative error.
    # Just check it exists.
    assert ip[0] != 0

def test_outlier_rejection():
    engine = MockAudioEngine()
    monitor = OnePPSMonitor(engine)
    monitor.threshold_fs = 0.5
    monitor.nominal_rate = 1000.0 # set low for easy maths
    
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
    
    t, ip, cp = monitor.get_history_arrays()
    
    # We expect the 5 initial 1000s to be accepted (0 PPM).
    # The 6th delta (2000) should be REJECTED.
    # The 7th delta (1000) should be ACCEPTED.
    # Result should have 6 items, all 0 PPM.
    
    assert len(ip) == 6
    assert np.all(ip == 0.0)

def test_cumulative_precision():
    engine = MockAudioEngine()
    monitor = OnePPSMonitor(engine)
    monitor.nominal_rate = 1000.0
    monitor.start_analysis()
    
    callback = list(engine.callbacks.values())[0]
    
    # Simulate a clock that is consistently off by +1 sample per 1000.
    # Actual rate = 1001 Hz.
    # Expected PPM = (1/1000)*1e6 = 1000 PPM.
    
    deltas = [1001] * 20
    
    total_len = sum(deltas) + 5000
    sig = np.zeros(total_len, dtype=np.float32)
    
    current_idx = 100
    sig[current_idx] = 1.0
    
    for d in deltas:
        current_idx += d
        sig[current_idx] = 1.0
        
    indata = np.column_stack((sig, sig))
    outdata = np.zeros_like(indata)
    callback(indata, outdata, len(sig), None, None)
    
    t, ip, cp = monitor.get_history_arrays()
    
    assert len(ip) == 20
    
    # Instantaneous should be exactly 1000 PPM (1 error sample)
    # (1001 - 1000) / 1000 * 1e6 = 1000.0
    assert np.allclose(ip, 1000.0)
    
    # Cumulative should also converge to 1000 PPM.
    # At step N (1-based):
    # Total samples = N * 1001
    # Total seconds = round(N * 1001 / 1000) = N (since 1001/1000 = 1.001, rounds to 1)
    # Avg Rate = (N * 1001) / N = 1001.
    # PPM = 1000.
    
    assert np.allclose(cp, 1000.0)
    
    # Now simulate a jittery clock but perfect average
    # 1002, 998, 1002, 998...
    # Avg is 1000. PPM should be 0.
    
    monitor.stop_analysis()
    monitor.start_analysis() # Reset
    callback = list(engine.callbacks.values())[0] # The mock engine might reuse ID or we just get the one active one
    
    deltas_jitter = [1002, 998] * 10
    total_len = sum(deltas_jitter) + 5000
    sig = np.zeros(total_len, dtype=np.float32)
    current_idx = 100
    sig[current_idx] = 1.0
    for d in deltas_jitter:
        current_idx += d
        sig[current_idx] = 1.0
        
    indata = np.column_stack((sig, sig))
    outdata = np.zeros_like(indata)
    callback(indata, outdata, len(sig), None, None)
    
    t, ip, cp = monitor.get_history_arrays()
    
    # Instantaneous will bounce:
    # 1002 -> +2 err -> +2000 PPM
    # 998 -> -2 err -> -2000 PPM
    assert abs(ip[0] - 2000.0) < 0.1
    assert abs(ip[1] + 2000.0) < 0.1
    
    # Cumulative:
    # Step 1: d=1002. Total=1002. Secs=1. Rate=1002. CP=2000.
    # Step 2: d=998. Total=2000. Secs=2. Rate=1000. CP=0.
    # Step 3: d=1002. Total=3002. Secs=3. Rate=1000.666. CP=666.66
    # Step 4: d=998. Total=4000. Secs=4. Rate=1000. CP=0.
    
    # Even steps should be perfect 0.
    even_steps_cp = cp[1::2]
    assert np.allclose(even_steps_cp, 0.0)
    
    # Odd steps should decay: 2000, 666, 400, 285...
    # 2000 / N_odd?
    # Step 1 (1st interval): 2 error / 1 sec = 2.
    # Step 3 (3rd interval): 2 error / 3 sec = 0.66.
    # Step 5: 2 error / 5 sec = 0.4.
    
    print(f"Jitter CP: {cp}")
