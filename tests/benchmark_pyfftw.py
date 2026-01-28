
import timeit
import numpy as np
import pyfftw
import multiprocessing

# Configure pyfftw to use multi-threading
# Autodetect number of cores
n_threads = multiprocessing.cpu_count()

SIZES = [1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072, 1048576]
ITERATIONS = 100

def benchmark():
    print(f"Benchmarking FFT implementations (Threads: {n_threads})")
    print(f"{'Size':<10} | {'NumPy (ms)':<12} | {'pyfftw (iface) (ms)':<20} | {'pyfftw (builder) (ms)':<20} | {'pyfftw (obj) (ms)':<20}")
    print("-" * 90)

    for N in SIZES:
        # Generate random real data
        # float64 is standard for numpy, but audio often uses float32. Let's test float32 as well if we have time, 
        # but usually we want to see if we can beat the default which is float64 in the current code (zeros((N, 2))).
        input_data = np.random.rand(N).astype(np.float64)

        # 1. NumPy
        t_numpy = timeit.timeit(lambda input_data=input_data: np.fft.rfft(input_data), number=ITERATIONS)
        avg_numpy = (t_numpy / ITERATIONS) * 1000

        # 2. pyfftw interfaces (drop-in)
        # Enable cache to avoid re-planning every call if possible, though interface might re-plan?
        # pyfftw.interfaces.cache.enable()
        pyfftw.interfaces.cache.enable()
        # We need to turn it on

        t_pyfftw_iface = timeit.timeit(lambda input_data=input_data: pyfftw.interfaces.numpy_fft.rfft(input_data, threads=n_threads), number=ITERATIONS)
        avg_pyfftw_iface = (t_pyfftw_iface / ITERATIONS) * 1000

        # 3. pyfftw builder (easier than object, optimized)
        # This creates an FFTW object
        # We pay the planning cost once, then execute
        fft_object_builder = pyfftw.builders.rfft(input_data, threads=n_threads)
        t_pyfftw_builder = timeit.timeit(lambda fft_object_builder=fft_object_builder: fft_object_builder(), number=ITERATIONS)
        avg_pyfftw_builder = (t_pyfftw_builder / ITERATIONS) * 1000

        # 4. pyfftw object manual (most control)
        # Requires aligned arrays
        aligned_in = pyfftw.empty_aligned(N, dtype='float64')
        aligned_out = pyfftw.empty_aligned(N//2 + 1, dtype='complex128')

        # Plan
        fft_object = pyfftw.FFTW(aligned_in, aligned_out, direction='FFTW_FORWARD', flags=('FFTW_MEASURE',), threads=n_threads)

        # Copy data in (simulating the update loop)
        def run_manual(aligned_in=aligned_in, input_data=input_data, fft_object=fft_object, aligned_out=aligned_out):
            aligned_in[:] = input_data # Copy takes time too, include it? 
            # In real app we might write directly to aligned buffer or copy.
            # Usually we have `input_data` coming from audio stream (numpy array).
            # So copy is necessary.
            fft_object()

            return aligned_out

        t_pyfftw_obj = timeit.timeit(run_manual, number=ITERATIONS)
        avg_pyfftw_obj = (t_pyfftw_obj / ITERATIONS) * 1000

        print(f"{N:<10} | {avg_numpy:<12.4f} | {avg_pyfftw_iface:<20.4f} | {avg_pyfftw_builder:<20.4f} | {avg_pyfftw_obj:<20.4f}")

if __name__ == "__main__":
    benchmark()
