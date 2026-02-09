
import sys
import os
import logging

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.audio_engine import AudioEngine

# Configure logging
logging.basicConfig(level=logging.INFO)

def test_refresh_backend():
    print("Initializing AudioEngine...")
    engine = AudioEngine()
    
    print("Initial device list:")
    devices = engine.list_devices()
    print(f"Found {len(devices)} devices.")
    
    print("\nCalling refresh_backend()...")
    try:
        engine.refresh_backend()
        print("refresh_backend() returned successfully.")
    except Exception as e:
        print(f"FAILED: refresh_backend() raised exception: {e}")
        return

    print("\nDevice list after refresh:")
    devices_after = engine.list_devices()
    print(f"Found {len(devices_after)} devices.")
    
    if len(devices) > 0 and len(devices_after) > 0:
        print("\nSUCCESS: Device list populated after refresh.")
    else:
        print("\nWARNING: Device list empty (might be expected in some envs).")

if __name__ == "__main__":
    test_refresh_backend()
