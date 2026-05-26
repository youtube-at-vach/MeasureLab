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
    engine.dithering_bit_depth = "8" # Use 8-bit to make dither noise clearly visible
    
    # Register a simple sine generator callback
    # It will write a sine wave to outdata, and we will inspect last_output_buffer
    freq = 1000.0
    sr = 48000
    amp = 0.5
    
    def cb(indata, outdata, frames, time_info, status):
        t = np.arange(frames) / sr
        outdata[:, 0] = amp * np.sin(2 * np.pi * freq * t)
        if outdata.shape[1] > 1:
            outdata[:, 1] = outdata[:, 0]
            
    cid = engine.register_callback(cb)
    
    # Let the stream run for a few blocks
    time.sleep(0.2)
    
    # Get the last output buffer (loopback buffer)
    lb_buffer = engine.last_output_buffer
    
    # Stop engine
    engine.unregister_callback(cid)
    
    if lb_buffer is None:
        print("Error: Loopback buffer is None")
        return
        
    # Analyze if there's dither noise (quantization to 8-bit)
    # 8-bit quantization scale is 128. lsb is 1/128 = 0.0078125.
    # If dither and quantization is applied, the values should be multiples of 1/128.
    # If not applied, they will be smooth float values.
    
    unique_vals = np.unique(np.round(lb_buffer[:, 0] * 128) / 128)
    # Check if values are exactly multiples of 1/128
    diffs = lb_buffer[:, 0] * 128 - np.round(lb_buffer[:, 0] * 128)
    max_quantization_error = np.max(np.abs(diffs))
    
    print(f"Max difference from 8-bit grid: {max_quantization_error:.6e}")
    if max_quantization_error < 1e-10:
        print("SUCCESS: Loopback buffer is quantized (dither was applied)")
    else:
        print("FAIL: Loopback buffer is high-precision float (dither was NOT applied)")

test_dither_in_loopback()
