import unittest
from unittest.mock import MagicMock
import numpy as np
import sys
import os

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.gui.widgets.one_pps_monitor import OnePPSMonitor

class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000.0
        self.calibration = MagicMock()
        self.calibration.frequency_calibration_1pps = 1.0

    def register_callback(self, cb):
        return 123

    def unregister_callback(self, id):
        pass

class TestOnePPSMonitorLogic(unittest.TestCase):
    def setUp(self):
        self.engine = MockAudioEngine()
        self.monitor = OnePPSMonitor(self.engine)
        self.monitor.nominal_rate = 48000.0
        self.monitor.threshold_fs = 0.5
        self.monitor.hysteresis_fs = 0.05
        # Disable filter for simple logic test
        self.monitor.filter_enabled = False
        self.monitor.warmup_count = 0 # Immediate results

    def tearDown(self):
        if self.monitor.is_running:
            self.monitor.stop_analysis()

    def test_perfect_1pps(self):
        """
        Verify that a perfect 1PPS signal (pulse every 48000 samples)
        results in 0 PPM error and correct Effective Rate.
        """
        self.monitor.start_analysis()

        # Create a buffer with pulses exactly 48000 samples apart.
        # Let's simulate 3 seconds (3 pulses).
        # We need to feed data in chunks.
        chunk_size = 4800
        total_samples = 48000 * 3 + 1000 # 3 full seconds + buffer

        signal = np.zeros(total_samples, dtype=np.float32)
        # Pulse at 0, 48000, 96000, 144000
        # Wait, pulse logic triggers on rising edge.
        # Let's put pulse at index 100, 48100, 96100.
        # Interval = 48000.
        indices = [100, 48100, 96100]
        for idx in indices:
            signal[idx] = 1.0 # High
            signal[idx+1] = 0.0 # Low

        # Feed data
        for i in range(0, total_samples, chunk_size):
            chunk = signal[i:i+chunk_size]
            self.monitor.data_queue.put((chunk, len(chunk)))

        # Stop signal
        self.monitor.data_queue.put(None)

        # Wait for thread
        if self.monitor.process_thread:
            self.monitor.process_thread.join()

        # Verify results
        t, ip, cp = self.monitor.get_history_arrays()

        # We expect 2 intervals measured (between 1st-2nd, 2nd-3rd)
        # The first pulse just starts the timer.
        # So we expect 2 data points.
        self.assertGreaterEqual(len(ip), 2)

        # PPM should be 0 because interval is exactly nominal
        self.assertTrue(np.allclose(ip, 0.0, atol=1e-3), f"Instant PPM should be 0, got {ip}")
        self.assertTrue(np.allclose(cp, 0.0, atol=1e-3), f"Cumulative PPM should be 0, got {cp}")

        # Check Effective Rate Formula Logic
        last_cp = cp[-1] # 0.0
        nominal = self.monitor.nominal_rate # 48000
        eff_rate = nominal * (1.0 + last_cp / 1e6)

        self.assertAlmostEqual(eff_rate, 48000.0, places=3)


    def test_fast_sample_rate(self):
        """
        Simulate a condition where the "Sample Rate" is faster than nominal.
        If Sample Rate is 48048 Hz (nominal 48000), then 1 second is 48048 samples.
        So pulses will arrive every 48048 samples.

        PPM Error Calculation:
        Interval = 48048. Nominal = 48000.
        Error = 48 - 0 = 48 samples.
        PPM = (48 / 48000) * 1e6 = 1000 PPM.

        Effective Rate Calculation:
        eff_rate = 48000 * (1 + 1000/1e6) = 48000 * 1.001 = 48048.
        This matches the actual sample interval.
        """
        self.monitor.start_analysis()

        interval = 48048
        # Create pulses
        indices = [100, 100 + interval, 100 + 2*interval]

        total_samples = indices[-1] + 1000
        signal = np.zeros(total_samples, dtype=np.float32)

        for idx in indices:
            signal[idx] = 1.0
            signal[idx+1] = 0.0

        # Feed all at once for simplicity (if supported) or chunked
        # Chunking is safer
        chunk_size = 4800
        for i in range(0, total_samples, chunk_size):
            chunk = signal[i:i+chunk_size]
            # Handle last chunk size
            real_len = len(chunk)
            self.monitor.data_queue.put((chunk, real_len))

        self.monitor.data_queue.put(None)
        self.monitor.process_thread.join()

        t, ip, cp = self.monitor.get_history_arrays()

        self.assertGreaterEqual(len(ip), 2)

        # Expected PPM = 1000
        expected_ppm = 1000.0
        self.assertTrue(np.allclose(ip, expected_ppm, atol=1e-1), f"Instant PPM should be 1000, got {ip}")
        # Cumulative might take a bit to settle if regression is used, but for exact linear inputs it should be close.
        # With only 2 points, regression slope is exact.
        self.assertTrue(np.allclose(cp, expected_ppm, atol=1e-1), f"Cumulative PPM should be 1000, got {cp}")

        # Verify Effective Rate
        last_cp = cp[-1]
        nominal = self.monitor.nominal_rate
        eff_rate = nominal * (1.0 + last_cp / 1e6)

        self.assertAlmostEqual(eff_rate, 48048.0, places=1)

if __name__ == '__main__':
    unittest.main()
