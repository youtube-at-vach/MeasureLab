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
    
    # Monkey patch _mix_clients to debug
    original_mix = engine._mix_clients
    def patched_mix(logical_in, frames, time_info, status, active_callbacks, logical_out_ch):
        res = original_mix(logical_in, frames, time_info, status, active_callbacks, logical_out_ch)
        print(f"[_mix_clients] mix_buffer max: {np.max(np.abs(res)):.6e}")
        return res
    engine._mix_clients = patched_mix

    # Monkey patch _update_loopback_buffer to debug
    original_update = engine._update_loopback_buffer
    def patched_update(source_buffer, frames, channels):
        if source_buffer is not None:
            print(f"[_update_loopback_buffer] source_buffer max: {np.max(np.abs(source_buffer)):.6e}")
        original_update(source_buffer, frames, channels)
    engine._update_loopback_buffer = patched_update
    
    def cb(indata, outdata, frames, time_info, status):
        t = np.arange(frames) / sr
        val = amp * np.sin(2 * np.pi * freq * t)
        outdata[:, 0] = val
        if outdata.shape[1] > 1:
            outdata[:, 1] = val
        print(f"[cb] outdata max: {np.max(np.abs(outdata)):.6e}")
            
    cid = engine.register_callback(cb)
    
    time.sleep(0.1)
    engine.unregister_callback(cid)

test_dither_in_loopback()
