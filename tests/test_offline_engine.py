
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
    
    print(f"Engine status: {engine.get_status()}")
    
    # Start stream
    # Start stream by registering a callback
    print("Registering callback to start engine...")
    def dummy_callback(indata, outdata, frames, time, status):
        pass
    
    cid = engine.register_callback(dummy_callback)
    time.sleep(0.5)
    
    status = engine.get_status()
    print(f"Engine status after start: {status}")
    
    if not status["offline_mode"]:
        print("FAIL: Engine is not in offline mode!")
        sys.exit(1)
        
    if not status["active"]:
        print("FAIL: Engine is not active!")
        sys.exit(1)
        
    print(f"Stream type: {type(engine.stream)}")
    if "VirtualStream" not in str(type(engine.stream)):
        print("FAIL: Stream is not VirtualStream!")
        sys.exit(1)

    # Test sample rate change
    print("Changing sample rate to 96000...")
    engine.set_sample_rate(96000)
    time.sleep(0.5)
    
    status = engine.get_status()
    print(f"Engine status after SR change: {status}")
    
    if engine.sample_rate != 96000:
        print(f"FAIL: Sample rate is {engine.sample_rate}, expected 96000")
        sys.exit(1)
        
    print("Stopping engine...")
    engine.unregister_callback(cid)
    
    print("Disabling offline mode...")
    engine.set_offline_mode(False)
    # Start might fail if no hardware, but we just check flag
    if engine.offline_mode:
         print("FAIL: Engine still in offline mode!")
         sys.exit(1)

    print("Offline mode test PASSED.")

if __name__ == "__main__":
    try:
        test_offline_mode()
    finally:
        if os.path.exists("test_config.json"):
            os.remove("test_config.json")
