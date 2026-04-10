import os
import sys
import time

import numpy as np

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.gui.widgets.lock_in_amplifier import LockInAmplifier
from unittest.mock import MagicMock

def test_lpf_performance():
    engine = MagicMock()
    engine.sample_rate = 48000
    lockin = LockInAmplifier(engine)
    lockin.postmix_lpf_order = 8
    lockin.postmix_lpf_tau_s = 0.1
    lockin.buffer_size = 4096

    # Mock data
    sig = np.random.randn(4096)
    ref = np.random.randn(4096)
    lockin.audio_engine.get_last_buffer = MagicMock(return_value=(sig, ref))

    lockin._last_process_time = time.time() - 0.1
    lockin.process_data()

    N = 10000
    t0 = time.perf_counter()
    for _ in range(N):
        lockin._last_process_time -= 0.1
        lockin.process_data()
    t1 = time.perf_counter()

    print(f"Time for {N} iterations: {t1-t0:.4f} s")

if __name__ == "__main__":
    test_lpf_performance()
