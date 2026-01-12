
import numpy as np
import time
import os
from pathlib import Path
import pyfftw
from src.core.fft_manager import fft_manager

SIZE = 65536 * 4 # Use a large size to make MEASURE planning noticeable
WISDOM_PATH = fft_manager.wisdom_path

def run_test():
    print(f"Testing FFT Wisdom Persistence (Size: {SIZE})")
    
    # Ensure no wisdom exists initially for clean test
    if WISDOM_PATH.exists():
        print("Removing existing wisdom for test...")
        WISDOM_PATH.unlink()

    # Reset manager to force reload (though we deleted the file)
    # Re-instantiating FFTManager won't clear internal pyfftw state entirely if the process is same,
    # but our logic loads from file on init.
    
    print("\n--- Run 1: Cold Start (Should be slow due to MEASURE) ---")
    data = np.random.rand(SIZE)
    
    t0 = time.time()
    # first call triggers planning
    fft_manager.rfft(data)
    t1 = time.time()
    print(f"Run 1 Planning + Exec Time: {t1 - t0:.4f} seconds")
    
    if WISDOM_PATH.exists():
        print(f"SUCCESS: Wisdom file created at {WISDOM_PATH}")
    else:
        print("FAILURE: Wisdom file NOT created!")

    print("\n--- Run 2: Restart Simulation (Reloading Wisdom) ---")
    # Simulate restart by clearing plans in manager (internal state of manager)
    # However, pyfftw keeps wisdom in memory.
    # To truly test persistence, we should run this in a separate process, but for this script:
    # We will "forget" wisdom in pyfftw and reload from file.
    
    pyfftw.forget_wisdom()
    fft_manager._plans.clear()
    
    # Load wisdom manually to simulate startup
    fft_manager.load_wisdom()
    
    t0 = time.time()
    fft_manager.rfft(data)
    t1 = time.time()
    print(f"Run 2 (Wisdom Loaded) Planning + Exec Time: {t1 - t0:.4f} seconds")
    
    # Verify speedup
    # Note: Plan creation with wisdom should be much faster than MEASURE.
    
    print("\n--- Run 3: Testing Warmup (Simulated) ---")
    
    def callback(msg):
        print(f"Callback received: {msg}")
        
    # Force warmup (re-measure) with exhaustive flag
    try:
        t0 = time.time()
        # NOTE: This might take a long time if we actually ran all sizes (up to 4M). 
        # For this test, we accept it might run long or we could mock WARMUP_SIZES but let's just run it 
        # to be sure it doesn't crash.
        fft_manager.warmup(callback=callback, force=True, exhaustive=True)
        t1 = time.time()
        print(f"Exhaustive Warmup Time: {t1 - t0:.4f} seconds")
    except Exception as e:
        print(f"Warmup failed: {e}")


    print("\nTest completed.")

if __name__ == "__main__":
    run_test()

