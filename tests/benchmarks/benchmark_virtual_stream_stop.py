import sys
import os
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from src.core.audio_engine import VirtualStream


def dummy_callback(*args, **kwargs):
    pass


def run_benchmark():
    # Use a large block size to create a long sleep interval
    stream = VirtualStream(samplerate=48000, blocksize=48000, channels=2, callback=dummy_callback)

    stream.start()

    # Wait a tiny bit to ensure the loop enters the sleep phase
    time.sleep(0.1)

    t0 = time.perf_counter()
    stream.stop()
    t1 = time.perf_counter()

    print(f"stop() duration: {t1 - t0:.6f} seconds")


if __name__ == "__main__":
    run_benchmark()
