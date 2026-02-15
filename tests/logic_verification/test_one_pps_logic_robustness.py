import time
import pytest
np = pytest.importorskip("numpy")
pytest.importorskip("PyQt6")

try:
    from src.gui.widgets.one_pps_monitor import OnePPSMonitor
except ImportError:
    pytest.skip("Skipping due to import errors", allow_module_level=True)

def wait_for_monitor(monitor, timeout=2.0):
    start = time.time()
    while not monitor.data_queue.empty() and (time.time() - start) < timeout:
        time.sleep(0.01)
    # Give it a tiny bit more for the last item to be processed
    time.sleep(0.1)

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

def test_gate_filter_logic():
    engine = MockAudioEngine()
    monitor = OnePPSMonitor(engine)
    monitor.threshold_fs = 0.5
    monitor.nominal_rate = 1000.0
    monitor.start_analysis()
    monitor.warmup_count = 0

    callback = list(engine.callbacks.values())[0]

    # Pulses:
    # 0 (Start)
    # 1000 (Accepted, Delta 1000)
    # 2500 (1500 away. 50% gate is 500. So max deviation allowed is 500. 1500 - 1000 = 500. Just on the edge? > 500 REJECT)
    # Actually gate is: abs(delta - nominal) > 0.5 * nominal
    # 1500 - 1000 = 500. Condition: > 500. It is NOT > 500. It IS 500. accepted?
    # Let's use 1600.

    pulse_locations = [0, 1000, 2600, 3600] 
    # 0 -> 1000: Delta 1000. OK.
    # 1000 -> 2600: Delta 1600. Deviation 600 > 500. REJECT.
    # If rejected, last trigger remains at 1000.
    # Next pulse at 3600. Delta = 3600 - 1000 = 2600. Deviation 1600 > 500. REJECT.
    # Wait, if we reject, we lose sync if the signal actually jumped?
    # Yes, for 1PPS we assume stable clock. If it jumped, it's garbage.
    # If it was a double pulse: 1000, 1010. Delta 10. Deviation 990 > 500. REJECT.
    # Then 2000 comes. Delta = 2000 - 1000 = 1000. ACCEPT.

    pulse_locations = [0, 1000, 1010, 2000]

    total_len = 3000
    sig = np.zeros(total_len, dtype=np.float32)
    for p in pulse_locations:
        sig[p] = 1.0

    indata = np.column_stack((sig, sig))
    outdata = np.zeros_like(indata)
    callback(indata, outdata, len(sig), None, None)

    wait_for_monitor(monitor)
    t, ip, cp = monitor.get_history_arrays()

    # Should have 3 intervals:
    # 1. 0->1000 (Delta 1000)
    # 2. 1000->1010 (Delta 10)
    # 3. 1010->2000 (Delta 990)

    assert len(ip) == 3
    # First one should be 1000 samples -> 0 ppm
    assert np.allclose(ip[0], 0.0)

def test_gate_filter_massive_glitch():
    engine = MockAudioEngine()
    monitor = OnePPSMonitor(engine)
    monitor.nominal_rate = 48000.0 
    monitor.start_analysis()
    monitor.warmup_count = 0

    callback = list(engine.callbacks.values())[0]

    # 0, 48000, 96000 (Normal)
    # 100000 (Glitch? 4000 away? No 100k - 96k = 4000. 4000 is way less than 48000/2. Outlier?)
    # Wait, 4000 sample interval? Nominal is 48000.
    # 4000 - 48000 = -44000. Abs > 24000. REJECT.

    pulse_locations = [0, 48000, 52000, 96000]
    # 0->48k: OK.
    # 48k->52k: Delta 4000. Deviation 44k > 24k. REJECT.
    # 48k->96k: Delta 48000. OK.

    sig = np.zeros(100000, dtype=np.float32)
    for p in pulse_locations:
        sig[p] = 1.0

    indata = np.column_stack((sig, sig))
    outdata = np.zeros_like(indata)
    callback(indata, outdata, len(sig), None, None)

    wait_for_monitor(monitor)
    t, ip, cp = monitor.get_history_arrays()

    # Should have 3 intervals:
    # 1. 0->48k: OK.
    # 2. 48k->52k: Delta 4000.
    # 3. 52k->96k: Delta 44k000.

    assert len(ip) == 3
    # First one should be 48000 samples -> 0 ppm
    assert np.allclose(ip[0], 0.0)

def test_mad_death_spiral():
    engine = MockAudioEngine()
    monitor = OnePPSMonitor(engine)
    monitor.threshold_fs = 0.5
    monitor.nominal_rate = 1000.0

    # Enable filter
    monitor.filter_enabled = True
    monitor.filter_window_size = 5
    monitor.filter_tolerance_sigma = 3.0

    monitor.start_analysis()
    monitor.warmup_count = 0

    callback = list(engine.callbacks.values())[0]

    # Sequence:
    # 5 good pulses (1000 delta) -> Median 1000. MAD extremely small.
    # 1 "Bad" pulse (1050 delta). Within Gate (500), but MAD rejects (50 > 3*mad).
    # Next pulse comes 1000 later. Total delta from PREVIOUS VALID (if not updated) = 2050.
    # 2050 is > Gate (1500 limit). Gate rejects.
    # System stops tracking.

    # Pulse locations:
    # 0, 1000, 2000, 3000, 4000, 5000 (Good history)
    # 6050 (Bad pulse, delta 1050).
    # 7050 (Good relative pulse, delta 1000 from 6050).

    pulse_locations = [0, 1000, 2000, 3000, 4000, 5000, 6050, 7050]

    total_len = 8000
    sig = np.zeros(total_len, dtype=np.float32)
    for p in pulse_locations:
        sig[p] = 1.0

    indata = np.column_stack((sig, sig))
    outdata = np.zeros_like(indata)
    callback(indata, outdata, len(sig), None, None)
    wait_for_monitor(monitor)
    t, ip, cp = monitor.get_history_arrays()

    # With bug:
    # 6050 rejected by MAD. Last valid = 5000.
    # 7050 comes. Delta = 7050 - 5000 = 2050.
    # Gate threshold = 500. Error = 1050. REJECTED by GATE.
    # So 7050 is lost.
    # Total accepted = 5 (0->5000).

    # With fix:
    # 6050 rejected by MAD. BUT Last valid updated to 6050.
    # 7050 comes. Delta = 7050 - 6050 = 1000. Accepted.
    # Total accepted = 6. (The 1050 one is not in history, but next one is).

    # Wait, if 6050 is rejected by MAD, do we want it in history? No.
    # So len(ip) should be 5 + 1 (last one) = 6?
    # Yes. The 6050 pulse is NOT in history.
    # But the 7050 pulse IS in history (with delta 1000).

    # Checking IP values
    # First 5 are 0.0.
    # Last one is 0.0.

    assert len(ip) == 6
    assert np.allclose(ip, 0.0)
