import time
import sounddevice as sd
from src.core.audio_engine import AudioEngine

def mock_sd_query_devices():
    # Return mock devices
    return [{"name": f"Device {i}", "hostapi": i % 3} for i in range(50)]

def mock_sd_query_hostapis(hostapi_idx=None):
    # Simulate some delay
    time.sleep(0.001)
    mock_hostapis = [{"name": "API 0"}, {"name": "API 1"}, {"name": "API 2"}]
    if hostapi_idx is not None:
        return mock_hostapis[hostapi_idx]
    return mock_hostapis

# The description in the prompt says:
# "Repeated sd.query_hostapis() inside device list loop"
# "Current Code: "
# "        enriched = []
# "        for dev in devices:
# "            d = dict(dev)
# "            hostapi_name = None
# "            if hostapis is not None:
# "                try:
# "                    hostapi_idx = d.get("hostapi")
# "                    if hostapi_idx is not None and 0 <= int(hostapi_idx) < len(hostapis):
# "                        hostapi_name = hostapis[int(hostapi_idx)].get("name")"
# "Rationale: Extracting hostapis = sd.query_hostapis() once outside the 'for dev in devices:' loop eliminates N redundant queries with negligible code changes."

# Ah, I see! Wait, in my `cat src/core/audio_engine.py` result, I see:
# 272:            hostapis = sd.query_hostapis()
#
# Wait, let me check the CURRENT file contents of src/core/audio_engine.py exactly around line 284:
