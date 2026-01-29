
import timeit
import numpy as np
import threading

# Constants
BUFFER_SIZE = 8192
CHUNK_SIZE = 512
CHANNELS = 2
ITERATIONS = 10000

# Setup Data
buffer = np.zeros((BUFFER_SIZE, CHANNELS), dtype=np.float32)
indata_stereo = np.random.rand(CHUNK_SIZE, CHANNELS).astype(np.float32)
indata_mono = np.random.rand(CHUNK_SIZE, 1).astype(np.float32)
lock = threading.Lock()

# --- Old Implementation (Allocating) ---
def old_callback_stereo():
    global buffer
    new_data = indata_stereo
    # np.roll creates a copy
    buffer = np.roll(buffer, -len(new_data), axis=0)
    buffer[-len(new_data):] = new_data

def old_callback_mono():
    global buffer
    # np.column_stack allocates
    new_data = np.column_stack((indata_mono[:, 0], indata_mono[:, 0]))
    buffer = np.roll(buffer, -len(new_data), axis=0)
    buffer[-len(new_data):] = new_data

# --- New Implementation (In-Place) ---
class RingBuffer:
    def __init__(self):
        self.buffer = np.zeros((BUFFER_SIZE, CHANNELS), dtype=np.float32)
        self.head = 0
        self.lock = threading.Lock()

    def callback_stereo(self):
        n_frames = len(indata_stereo)
        with self.lock:
            # Wrapped write logic
            idx = self.head
            end_idx = idx + n_frames
            if end_idx <= BUFFER_SIZE:
                self.buffer[idx:end_idx] = indata_stereo
            else:
                part1 = BUFFER_SIZE - idx
                self.buffer[idx:] = indata_stereo[:part1]
                self.buffer[:n_frames - part1] = indata_stereo[part1:]
            self.head = (idx + n_frames) % BUFFER_SIZE

    def callback_mono(self):
        n_frames = len(indata_mono)
        with self.lock:
            idx = self.head
            end_idx = idx + n_frames
            if end_idx <= BUFFER_SIZE:
                self.buffer[idx:end_idx, 0] = indata_mono[:, 0]
                self.buffer[idx:end_idx, 1] = indata_mono[:, 0]
            else:
                part1 = BUFFER_SIZE - idx
                self.buffer[idx:, 0] = indata_mono[:part1, 0]
                self.buffer[idx:, 1] = indata_mono[:part1, 0]

                self.buffer[:n_frames - part1, 0] = indata_mono[part1:, 0]
                self.buffer[:n_frames - part1, 1] = indata_mono[part1:, 0]
            self.head = (idx + n_frames) % BUFFER_SIZE

rb = RingBuffer()

def run_bench():
    print(f"Benchmark: Buffer={BUFFER_SIZE}, Chunk={CHUNK_SIZE}, Iterations={ITERATIONS}")

    # Test Stereo
    t_old_stereo = timeit.timeit(old_callback_stereo, number=ITERATIONS)
    t_new_stereo = timeit.timeit(rb.callback_stereo, number=ITERATIONS)

    print("\nStereo Input:")
    print(f"Old (Allocating): {t_old_stereo:.4f} sec ({ITERATIONS/t_old_stereo:.0f} ops/sec)")
    print(f"New (In-Place):   {t_new_stereo:.4f} sec ({ITERATIONS/t_new_stereo:.0f} ops/sec)")
    print(f"Speedup:          {t_old_stereo / t_new_stereo:.2f}x")

    # Test Mono
    t_old_mono = timeit.timeit(old_callback_mono, number=ITERATIONS)
    t_new_mono = timeit.timeit(rb.callback_mono, number=ITERATIONS)

    print("\nMono Input:")
    print(f"Old (Allocating): {t_old_mono:.4f} sec ({ITERATIONS/t_old_mono:.0f} ops/sec)")
    print(f"New (In-Place):   {t_new_mono:.4f} sec ({ITERATIONS/t_new_mono:.0f} ops/sec)")
    print(f"Speedup:          {t_old_mono / t_new_mono:.2f}x")

if __name__ == "__main__":
    run_bench()
