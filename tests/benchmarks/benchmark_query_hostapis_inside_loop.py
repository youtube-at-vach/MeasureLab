import time
import sounddevice as sd

def setup_mock_devices():
    class MockDeviceList(list):
        pass

    devices = MockDeviceList()
    for i in range(50):
        devices.append({
            "name": f"Device {i}",
            "hostapi": i % 3,
            "max_input_channels": 2,
            "max_output_channels": 2,
            "default_samplerate": 48000.0,
        })
    return devices

def mock_query_hostapis(idx=None):
    hostapis = [
        {"name": "ALSA"},
        {"name": "PulseAudio"},
        {"name": "JACK"},
    ]
    if idx is not None:
        return hostapis[idx]
    return hostapis

devices = setup_mock_devices()

def original():
    enriched = []
    for dev in devices:
        d = dict(dev)
        hostapi_name = None

        try:
            hostapi_idx = d.get("hostapi")
            if hostapi_idx is not None:
                hostapi_info = mock_query_hostapis(hostapi_idx)
                hostapi_name = hostapi_info.get("name")
        except Exception:
            hostapi_name = None

        if hostapi_name:
            d["hostapi_name"] = str(hostapi_name)
        enriched.append(d)
    return enriched

def optimized():
    # Fetch hostapis ONCE
    try:
        hostapis = mock_query_hostapis()
    except Exception:
        hostapis = None

    enriched = []
    for dev in devices:
        d = dict(dev)
        hostapi_name = None

        if hostapis is not None:
            try:
                hostapi_idx = d.get("hostapi")
                if hostapi_idx is not None and 0 <= int(hostapi_idx) < len(hostapis):
                    hostapi_name = hostapis[int(hostapi_idx)].get("name")
            except Exception:
                hostapi_name = None

        if hostapi_name:
            d["hostapi_name"] = str(hostapi_name)
        enriched.append(d)
    return enriched

def run_benchmark():
    ITERATIONS = 1000

    start = time.time()
    for _ in range(ITERATIONS):
        original()
    orig_time = time.time() - start
    print(f"Original Time: {orig_time:.4f}s")

    start = time.time()
    for _ in range(ITERATIONS):
        optimized()
    opt_time = time.time() - start
    print(f"Optimized Time: {opt_time:.4f}s")

    if opt_time > 0:
        print(f"Speedup: {orig_time/opt_time:.2f}x")

if __name__ == "__main__":
    run_benchmark()
