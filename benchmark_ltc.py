import time
import numpy as np
from src.core.ltc import LTCDecoder, LTCEncoder

def run_benchmark():
    sample_rate = 48000
    fps = 25
    encoder = LTCEncoder(sample_rate, fps)

    # Generate 100 seconds of LTC audio
    chunks = []
    for _ in range(100 * fps):
        chunks.append(encoder.generate_frame(1, 2, 3, 4))

    audio = np.concatenate(chunks)

    decoder = LTCDecoder(sample_rate, fps)

    # Process in chunks of 1024
    chunk_size = 1024
    num_chunks = len(audio) // chunk_size

    start_time = time.time()
    for i in range(num_chunks):
        chunk = audio[i*chunk_size:(i+1)*chunk_size]
        decoder.process_samples(chunk)

    end_time = time.time()

    print(f"Time taken to decode 100 seconds of LTC: {end_time - start_time:.4f} seconds")

if __name__ == '__main__':
    run_benchmark()
