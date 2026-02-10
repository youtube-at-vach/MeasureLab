import time
import tracemalloc
import numpy as np
import os
import sys
from unittest.mock import MagicMock

# Mock sounddevice
sys.modules['sounddevice'] = MagicMock()

# Mock PyQt6 to avoid needing a display or QApplication
sys.modules['PyQt6.QtCore'] = MagicMock()
sys.modules['PyQt6.QtWidgets'] = MagicMock()

from src.gui.widgets.recorder_player import RecorderPlayer  # noqa: E402
from src.core.audio_engine import AudioEngine  # noqa: E402

def benchmark_save(duration_sec=10, chunk_size=1024):
    print(f"Benchmarking save_recording with {duration_sec}s of audio...")

    # Setup
    audio_engine = MagicMock(spec=AudioEngine)
    audio_engine.sample_rate = 48000
    player = RecorderPlayer(audio_engine)

    # Generate data
    n_chunks = int(duration_sec * 48000 / chunk_size)
    channels = 2

    print("Generating data...")
    for _ in range(n_chunks):
        chunk = np.random.rand(chunk_size, channels).astype(np.float32)
        player.record_buffer.append(chunk)

    print(f"Created {len(player.record_buffer)} chunks.")

    filepath = "benchmark_output.wav"

    # Measure memory and time
    tracemalloc.start()
    start_time = time.time()

    try:
        player.save_recording(filepath)
    except Exception as e:
        print(f"Error saving: {e}")
    finally:
        current, peak = tracemalloc.get_traced_memory()
        end_time = time.time()
        tracemalloc.stop()

    print(f"Time taken: {end_time - start_time:.4f} seconds")
    print(f"Peak memory usage: {peak / 1024 / 1024:.2f} MB")

    # Cleanup
    if os.path.exists(filepath):
        os.remove(filepath)

if __name__ == "__main__":
    benchmark_save(duration_sec=120)
