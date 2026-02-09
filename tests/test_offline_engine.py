
import time
import sys
import os
import numpy as np

# Adjust path to find src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.audio_engine import AudioEngine
from src.core.config_manager import ConfigManager

def test_offline_mode():
    print("Initializing ConfigManager...")
    config = ConfigManager("test_config.json")
    
    # Force offline mode in config
    print("Setting offline mode = True")
    config.set_offline_mode(True)
    config.set_offline_sample_rate(44100)
    
    print("Initializing AudioEngine...")
    engine = AudioEngine()
    engine.set_offline_mode(config.is_offline_mode())
    engine.set_sample_rate(config.get_offline_sample_rate())
    
    # Start stream by registering a callback that checks for input
    print("Registering signal checker...")
    
    output_signal_gen = False
    input_signal_detected = False
    
    def signal_checker_callback(indata, outdata, frames, time, status):
        nonlocal input_signal_detected, output_signal_gen
        # Generate some noise on output
        noise = np.random.uniform(-0.1, 0.1, (frames, outdata.shape[1])).astype(np.float32)
        outdata[:] = noise
        output_signal_gen = True
        
        # Check if input has signal (loopback)
        if np.max(np.abs(indata)) > 0.001:
            input_signal_detected = True

    cid = engine.register_callback(signal_checker_callback)
    time.sleep(1.0) # Wait for a few blocks
    
    status = engine.get_status()
    print(f"Engine status after start: {status}")
    
    if not status["offline_mode"]:
        print("FAIL: Engine is not in offline mode!")
        sys.exit(1)
        
    if not output_signal_gen:
        print("FAIL: Callback was never called (no output generated).")
        sys.exit(1)
        
    if not input_signal_detected:
        print("FAIL: No signal detected on input! Loopback might be missing.")
        sys.exit(1)
        
    print("Signal detected on input (Loopback working).")
    
    engine.unregister_callback(cid)
    engine.set_offline_mode(False)
    print("Offline mode test PASSED.")

if __name__ == "__main__":
    try:
        test_offline_mode()
    finally:
        if os.path.exists("test_config.json"):
            os.remove("test_config.json")
