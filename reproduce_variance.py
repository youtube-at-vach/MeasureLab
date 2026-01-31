
import sys
import os

# Add the project root to sys.path
sys.path.append(os.getcwd())


# Mock UI dependencies
import sys
from unittest.mock import MagicMock

sys.modules['pyqtgraph'] = MagicMock()
sys.modules['PyQt6'] = MagicMock()
sys.modules['PyQt6.QtCore'] = MagicMock()
sys.modules['PyQt6.QtWidgets'] = MagicMock()

# Mock localization because it is imported
sys.modules['src.core.localization'] = MagicMock()
sys.modules['src.core.localization'].tr = lambda x: x

import numpy as np  # noqa: E402
from src.gui.widgets.lock_in_frequency_counter import LockInFrequencyCounter  # noqa: E402

class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000
    def register_callback(self, cb):
        return 1
    def unregister_callback(self, id):
        pass

def run_test_case(target_freq, noise_std=0.0, use_float32=False):
    print(f"\n--- Running Test Case: {target_freq} Hz, Noise={noise_std}, F32={use_float32} ---")
    engine = MockAudioEngine()
    counter = LockInFrequencyCounter(engine)

    # Configure
    counter.buffer_size = 4096
    counter.nco_avg_count = 100
    counter.gen_frequency = target_freq # Start locked (simulate lock)
    counter.locked = True
    counter.signal_channel = 0

    # Start analysis
    counter.start_analysis()

    sr = engine.sample_rate
    total_samples = 0
    measured_freqs = []

    # Run loop
    for _ in range(200): # 200 iterations
        t = (np.arange(counter.buffer_size) + total_samples) / sr
        sig = 1.0 * np.cos(2 * np.pi * target_freq * t)

        if noise_std > 0:
            sig += np.random.normal(0, noise_std, size=len(sig))

        if use_float32:
            sig = sig.astype(np.float32)

        counter.input_data[:, 0] = sig
        counter._samples_received += counter.buffer_size # Cheat to keep it running

        counter.process_data()

        measured_freqs.append(counter.gen_frequency)
        total_samples += counter.buffer_size

    # Stats from last 100
    last_100 = measured_freqs[-100:]
    std = np.std(last_100)
    print(f"Result Std: {std:.6e}")
    return std

def reproduce():
    # Case 1: 1000 Hz (Non-integer cycles in 1024 window. 2000Hz * 1024/48000 = 42.66 cycles)
    std_1000 = run_test_case(1000.0, noise_std=0.0)

    # Case 2: 937.5 Hz (Integer cycles. 1875Hz * 1024/48000 = 40 cycles)
    std_9375 = run_test_case(937.5, noise_std=0.0)

    # Case 3: 1000 Hz with Noise
    std_noise = run_test_case(1000.0, noise_std=2e-5) # ~ -94dB noise

    # Case 4: 1000 Hz with High Noise (-60dB)
    std_high_noise = run_test_case(1000.0, noise_std=1e-3)

    # Case 5: 1000 Hz with Float32 Truncation
    std_f32 = run_test_case(1000.0, noise_std=0.0, use_float32=True)

    print("\nSummary:")
    print(f"1000 Hz (Non-integer): {std_1000:.6e}")
    print(f"937.5 Hz (Integer):   {std_9375:.6e}")
    print(f"1000 Hz + Noise (-94dB): {std_noise:.6e}")
    print(f"1000 Hz + Noise (-60dB): {std_high_noise:.6e}")
    print(f"1000 Hz + Float32:    {std_f32:.6e}")

if __name__ == "__main__":
    reproduce()
