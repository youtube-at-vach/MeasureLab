import time
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.event_detector import DetectorConfig, EventDetectorCore  # noqa: E402


def benchmark_event_detector(iterations: int = 10_000) -> None:
    """Measure the common event-free callback path at 192 kHz."""
    sample_rate = 192_000
    block_size = 1024
    detector = EventDetectorCore(
        DetectorConfig(
            sample_rate=sample_rate,
            threshold=0.01,
            hysteresis=0.001,
            holdoff_seconds=0.01,
        )
    )
    detector.start()
    block = np.zeros(block_size, dtype=np.float32)

    for _ in range(100):
        detector.process(block)

    started = time.perf_counter()
    for _ in range(iterations):
        detector.process(block)
    elapsed = time.perf_counter() - started

    average_us = elapsed * 1e6 / iterations
    block_budget_us = block_size * 1e6 / sample_rate
    print(f"Average detector time: {average_us:.2f} us/block")
    print(f"Audio block budget: {block_budget_us:.2f} us/block")
    print(f"Budget usage: {average_us * 100.0 / block_budget_us:.2f}%")


if __name__ == "__main__":
    benchmark_event_detector()
