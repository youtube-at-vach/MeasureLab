import sys
from unittest.mock import MagicMock
sys.modules['sounddevice'] = MagicMock()
import time
import numpy as np
import scipy.signal as signal

def benchmark():
    sr = 48000

    start = time.time()
    for _ in range(500):
        sos_pre = signal.butter(1, 200, btype="highpass", fs=sr, output="sos")
        mod_sos = signal.butter(2, [0.5, 20], btype="bandpass", fs=sr, output="sos")
    time_taken = time.time() - start

    print(f"Time to compute filters 500 times: {time_taken:.4f} seconds")

if __name__ == "__main__":
    benchmark()
