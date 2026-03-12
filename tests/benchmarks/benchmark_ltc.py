import time
import numpy as np
from src.core.ltc import LTCDecoder, LTCEncoder

def benchmark_ltc_decoder():
    sr = 48000
    fps = 30.0
    enc = LTCEncoder(sr, fps)
    dec = LTCDecoder(sr, fps)

    # Generate 1000 frames of LTC
    frames = [enc.generate_frame(0, 0, 0, ff % 30) for ff in range(1000)]
    stream = np.concatenate(frames)
    # duplicate to stress test
    stream = np.tile(stream, 100) # 100k frames

    # chunked processing to mimic real audio
    chunk_size = 1024

    chunks = []
    for i in range(0, len(stream), chunk_size):
        chunks.append(stream[i:i+chunk_size])

    start_time = time.perf_counter()
    for chunk in chunks:
        dec.process_samples(chunk)
    end_time = time.perf_counter()

    print(f"Time taken: {end_time - start_time:.4f} seconds")

if __name__ == "__main__":
    benchmark_ltc_decoder()
