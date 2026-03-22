import time
import threading


def benchmark_sleep():
    start = time.time()

    is_active = True

    def mock_stream_runner():
        nonlocal is_active
        time.sleep(0.05)  # Simulate some stream processing
        is_active = False

    threading.Thread(target=mock_stream_runner).start()

    while is_active:
        time.sleep(0.1)

    return time.time() - start


def benchmark_event():
    start = time.time()

    stream_finished = threading.Event()

    def mock_stream_runner():
        time.sleep(0.05)  # Simulate some stream processing
        stream_finished.set()

    threading.Thread(target=mock_stream_runner).start()

    while not stream_finished.is_set():
        if stream_finished.wait(0.1):
            break

    return time.time() - start


if __name__ == "__main__":
    # Warmup
    benchmark_sleep()
    benchmark_event()

    iters = 20

    t1 = sum(benchmark_sleep() for _ in range(iters)) / iters
    t2 = sum(benchmark_event() for _ in range(iters)) / iters

    print(f"Baseline (time.sleep): {t1:.4f}s")
    print(f"Optimized (Event.wait): {t2:.4f}s")
    if t1 > 0:
        print(f"Improvement: {(t1 - t2) / t1 * 100:.2f}%")
