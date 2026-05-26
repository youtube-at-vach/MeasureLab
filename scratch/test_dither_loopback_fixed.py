import sys

sys.path.append("/Users/vach/MeasureLab")
import numpy as np
import time
from src.core.audio_engine import AudioEngine


def test_dither_in_loopback_fixed():
    engine = AudioEngine()
    engine.set_offline_mode(True)
    engine.dithering_enabled = True
    engine.dithering_bit_depth = "8"

    # Let's monkeypatch _master_callback to swap loopback update and dithering

    def patched_master_callback(indata, outdata, frames, time_info, status):
        # We manually implement the callback steps to swap the order
        if status:
            with engine._status_lock:
                engine.accumulated_status |= status

        outdata.fill(0)

        # 1. Prepare Inputs
        use_loopback = engine.loopback or engine.offline_mode
        logical_in = engine._prepare_logical_input(indata, frames, use_loopback)

        # 2. Prepare Output Configuration
        out_mode = engine._current_out_mode
        logical_out_ch = 2 if out_mode == engine.MODE_STEREO else 1
        active_callbacks = engine._cached_callbacks

        # 3. Mix Clients
        if not active_callbacks:
            if use_loopback:
                engine._update_loopback_buffer(None, frames, logical_out_ch)
            return

        mix_buffer = engine._mix_clients(logical_in, frames, time_info, status, active_callbacks, logical_out_ch)

        # 5. Apply Effects (Dithering) FIRST
        if engine.dithering_enabled:
            engine._apply_dithering(mix_buffer)

        # 4. Update Loopback SECOND (using dithered/quantized mix_buffer)
        if use_loopback:
            engine._update_loopback_buffer(mix_buffer, frames, logical_out_ch)

        # 6. Map to Hardware Output
        engine._map_logical_to_hardware_output(mix_buffer, outdata, out_mode)

    engine._master_callback = patched_master_callback

    freq = 1000.0
    sr = 48000
    amp = 0.5

    # Store the captured loopback buffer inside the callback before it gets cleared
    captured_buffers = []

    def cb(indata, outdata, frames, time_info, status):
        t = np.arange(frames) / sr
        outdata[:, 0] = amp * np.sin(2 * np.pi * freq * t)
        if outdata.shape[1] > 1:
            outdata[:, 1] = outdata[:, 0]

        # Capture the input (which is the loopback from the previous block)
        if np.max(np.abs(indata)) > 0:
            captured_buffers.append(indata.copy())

    cid = engine.register_callback(cb)

    time.sleep(0.2)
    engine.unregister_callback(cid)

    if not captured_buffers:
        print("Error: No loopback input captured")
        return

    last_input = captured_buffers[-1]

    # Analyze if the loopback input is quantized to 8-bit
    diffs = last_input[:, 0] * 128 - np.round(last_input[:, 0] * 128)
    max_quantization_error = np.max(np.abs(diffs))

    print(f"Max difference from 8-bit grid in loopback input: {max_quantization_error:.6e}")
    if max_quantization_error < 1e-5:
        print("SUCCESS: Swapping order correctly applies dithering/quantization to the loopback path!")
    else:
        print("FAIL: Swapping order did not apply dithering/quantization.")


test_dither_in_loopback_fixed()
