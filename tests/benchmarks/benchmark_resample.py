import time
import numpy as np
from src.core.analysis import AudioCalc

def benchmark():
    source_sr = 44100
    target_sr = 48000
    duration = 1.0  # 1 second
    N = int(source_sr * duration)
    t = np.arange(N) / source_sr
    freq = 1000.0
    signal = np.sin(2 * np.pi * freq * t) + 0.1 * np.random.randn(N)

    # Warm up
    AudioCalc.resample(signal, source_sr, target_sr)

    iterations = 50
    start_time = time.time()
    for _ in range(iterations):
        AudioCalc.resample(signal, source_sr, target_sr)
    end_time = time.time()

    avg_time = (end_time - start_time) / iterations
    print(f"Resample {source_sr}->{target_sr} ({duration}s): {avg_time*1000:.4f} ms per call")

if __name__ == "__main__":
    benchmark()
