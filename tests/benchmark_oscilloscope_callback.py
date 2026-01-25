import time
import numpy as np
import sys
import os
from unittest.mock import MagicMock

# Mock sounddevice
sys.modules['sounddevice'] = MagicMock()

# Add src to path
sys.path.insert(0, os.getcwd())

from src.gui.widgets.oscilloscope import Oscilloscope

# Parameters
BLOCK_SIZE = 512
CHANNELS = 2
ITERATIONS = 10000

def run_benchmark():
    # Mock Engine
    engine = MagicMock()
    engine.sample_rate = 48000
    engine.register_callback.return_value = 1

    osc = Oscilloscope(engine)
    osc.start_analysis()

    # Get callback
    # register_callback was called
    args = engine.register_callback.call_args
    if args:
        callback = args[0][0]
    else:
        print("Error: callback not registered")
        return

    # Prepare data
    indata = np.random.rand(BLOCK_SIZE, CHANNELS).astype(np.float32)
    outdata = np.zeros_like(indata)

    print(f"Running benchmark with {ITERATIONS} iterations on actual Oscilloscope class...")

    start_time = time.time()
    for _ in range(ITERATIONS):
        callback(indata, outdata, BLOCK_SIZE, None, None)
    end_time = time.time()

    duration = end_time - start_time
    print(f"Total time: {duration:.4f}s")
    print(f"Time per callback: {duration/ITERATIONS*1e6:.2f} us")

if __name__ == "__main__":
    run_benchmark()
