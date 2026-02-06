import time
import numpy as np
import unittest.mock as mock
import sys

# Mock sounddevice
mock_sd = mock.MagicMock()
mock_sd.CallbackFlags = lambda: 0
sys.modules["sounddevice"] = mock_sd

from src.core.audio_engine import AudioEngine  # noqa: E402

def benchmark_audio_allocation():
    engine = AudioEngine()
    engine.input_channel_mode = "right"
    # Ensure loopback is false to hit the else block
    engine.loopback = False

    # We need to trigger _start_master_stream to get the internal master_callback
    # Since we mocked sd.Stream, this is safe
    engine._start_master_stream()

    # Retrieve the callback passed to sd.Stream
    # engine.stream should be the mock return value
    # But wait, sd.Stream is a class.
    # mock_sd.Stream(...) returns the stream instance.

    # The call arguments to sd.Stream constructor:
    call_args = mock_sd.Stream.call_args
    if not call_args:
        print("Error: sd.Stream was not called.")
        return

    kwargs = call_args[1]
    master_callback = kwargs.get("callback")

    if not master_callback:
        print("Error: Could not find master_callback in sd.Stream arguments.")
        return

    # Prepare data for benchmark
    frames = 1024
    # indata with 1 channel to trigger the allocation path
    indata_1ch = np.zeros((frames, 1), dtype="float32")
    outdata = np.zeros((frames, 2), dtype="float32")
    status = 0

    iterations = 100000

    print("Benchmarking 'right' channel mode with 1-channel input (allocating path)...")

    start_time = time.perf_counter()
    for _ in range(iterations):
        master_callback(indata_1ch, outdata, frames, 0.0, status)
    end_time = time.perf_counter()

    duration = end_time - start_time
    print(f"Duration for {iterations} iterations: {duration:.4f} s")
    print(f"Average time per callback: {duration/iterations*1e6:.2f} us")

    # Verify that the allocation path is actually being hit?
    # We can inspect if _logical_in_buffer is being used or not (it shouldn't be in the current code)
    # The current code doesn't use _logical_in_buffer for this path, so it allocates.

    # Let's also benchmark the "good" path (e.g. stereo input) for comparison
    engine.input_channel_mode = "stereo"
    # Need to get a new callback or restart stream?
    # Changing input_channel_mode in engine changes `in_mode` used in `master_callback`?
    # NO. `in_mode` is a local variable captured at definition time in `_start_master_stream`.
    #   in_mode = self.input_channel_mode
    # So we need to restart the stream to test another mode.

    engine.stop_stream()
    engine.input_channel_mode = "stereo"
    engine._start_master_stream()

    call_args = mock_sd.Stream.call_args
    master_callback_stereo = call_args[1].get("callback")

    indata_2ch = np.zeros((frames, 2), dtype="float32")

    print("Benchmarking 'stereo' channel mode (no allocation path)...")
    start_time = time.perf_counter()
    for _ in range(iterations):
        master_callback_stereo(indata_2ch, outdata, frames, 0.0, status)
    end_time = time.perf_counter()

    duration_stereo = end_time - start_time
    print(f"Duration for {iterations} iterations: {duration_stereo:.4f} s")
    print(f"Average time per callback: {duration_stereo/iterations*1e6:.2f} us")


if __name__ == "__main__":
    benchmark_audio_allocation()
