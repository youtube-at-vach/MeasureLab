import time
import numpy as np
from unittest.mock import MagicMock
from src.gui.widgets.lock_in_amplifier import LockInAmplifier

def run_benchmark():
    engine = MagicMock()
    engine.sample_rate = 48000
    lockin = LockInAmplifier(engine)

    # Set parameters
    lockin.postmix_lpf_order = 8
    lockin.postmix_lpf_tau_s = 0.1
    lockin.buffer_size = 4096

    # Mock data
    sig = np.random.randn(4096)
    ref = np.random.randn(4096)

    # Warmup and initialize
    lockin.audio_engine.get_last_buffer = MagicMock(return_value=(sig, ref))
    lockin._last_process_time = time.time() - 0.1
    lockin.process_data()

    N = 5000
    t0 = time.perf_counter()
    for _ in range(N):
        # We need to simulate dt correctly, let's mock time or just bypass the early exit
        lockin._last_process_time -= 0.1
        lockin.process_data()
    t1 = time.perf_counter()

    print(f"Total time for {N} iterations: {t1-t0:.4f} seconds")
    print(f"Time per iteration: {(t1-t0)/N*1000:.4f} ms")

if __name__ == "__main__":
    run_benchmark()
