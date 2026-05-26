import sys
import os
sys.path.append("/Users/vach/MeasureLab")
import numpy as np
import time
from src.core.audio_engine import AudioEngine

def test_dither_in_loopback():
    engine = AudioEngine()
    engine.set_offline_mode(True)
    engine.dithering_enabled = True
    engine.dithering_bit_depth = "8"
    
    freq = 1000.0
    sr = 48000
    amp = 0.5
    
    called = []
    
    def cb(indata, outdata, frames, time_info, status):
        called.append(frames)
        t = np.arange(frames) / sr
        outdata[:, 0] = amp * np.sin(2 * np.pi * freq * t)
        if outdata.shape[1] > 1:
            outdata[:, 1] = outdata[:, 0]
            
    cid = engine.register_callback(cb)
    
    time.sleep(0.5)
    
    lb_buffer = engine.last_output_buffer
    
    # Get status to check errors
    status = engine.get_status()
    engine.unregister_callback(cid)
    
    print(f"Callback called {len(called)} times.")
    print("Engine Status:", status)
    if lb_buffer is None:
        print("Loopback buffer is None")
        return
        
    print(f"Loopback buffer shape: {lb_buffer.shape}")
    print(f"Loopback buffer max value: {np.max(np.abs(lb_buffer)):.6f}")

test_dither_in_loopback()
