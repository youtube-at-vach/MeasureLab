import time
import sounddevice as sd
from unittest.mock import patch

# Import the AudioEngine we want to benchmark
from src.core.audio_engine import AudioEngine

def run_benchmark():
    engine = AudioEngine()

    # We will mock sd.query_devices and sd.query_hostapis so we can simulate real OS overhead
    # while controlling execution in CI. Alternatively, we can let it query real OS if available.
    try:
        sd.query_devices()
        has_real_devices = True
    except Exception:
        has_real_devices = False

    ITERATIONS = 50

    if not has_real_devices:
        print("No real devices found. We will mock the sd.query_devices and sd.query_hostapis calls.")
        mock_devices = []
        for i in range(50):
            mock_devices.append({"name": f"Device {i}", "hostapi": i % 3})

        mock_hostapis = [{"name": "ALSA"}, {"name": "PulseAudio"}, {"name": "JACK"}]

        def fake_query_devices():
            time.sleep(0.005) # simulate OS delay
            return mock_devices

        def fake_query_hostapis(idx=None):
            time.sleep(0.002) # simulate OS delay
            if idx is not None:
                return mock_hostapis[idx]
            return mock_hostapis

        with patch('sounddevice.query_devices', side_effect=fake_query_devices):
            with patch('sounddevice.query_hostapis', side_effect=fake_query_hostapis):
                print("Running without cache (simulated)...")
                # clear cache
                engine._device_list_cache = None
                engine._host_apis_cache = None
                engine._last_cache_time = 0

                start_time = time.time()
                for _ in range(ITERATIONS):
                    # forcefully invalidate cache
                    engine._last_cache_time = 0
                    engine.list_devices()
                uncached_time = time.time() - start_time

                print("Running with cache (simulated)...")
                # clear cache before start
                engine._device_list_cache = None
                engine._host_apis_cache = None
                engine._last_cache_time = 0

                start_time = time.time()
                for _ in range(ITERATIONS):
                    engine.list_devices()
                cached_time = time.time() - start_time
    else:
        print("Real devices found. Benchmarking real sd calls...")
        print("Running without cache...")
        engine._device_list_cache = None
        engine._host_apis_cache = None
        engine._last_cache_time = 0

        start_time = time.time()
        for _ in range(ITERATIONS):
            # forcefully invalidate cache
            engine._last_cache_time = 0
            engine.list_devices()
        uncached_time = time.time() - start_time

        print("Running with cache...")
        # clear cache before start
        engine._device_list_cache = None
        engine._host_apis_cache = None
        engine._last_cache_time = 0

        start_time = time.time()
        for _ in range(ITERATIONS):
            engine.list_devices()
        cached_time = time.time() - start_time

    print(f"Uncached average time: {uncached_time / ITERATIONS:.4f}s")
    print(f"Cached average time: {cached_time / ITERATIONS:.4f}s")

    if cached_time > 0:
        improvement = (uncached_time - cached_time) / uncached_time * 100
        speedup = uncached_time / cached_time
        print(f"Improvement: {improvement:.2f}% (Speedup: {speedup:.2f}x)")

if __name__ == "__main__":
    run_benchmark()
