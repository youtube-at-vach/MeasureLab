"""Manual benchmark for Signal Generator real-time and buffer-preparation paths.

Run from the repository root:

    ./.venv/bin/python tests/benchmarks/algorithms/benchmark_signal_generator.py

Set ``MEASURELAB_BENCHMARK_ROOT`` to benchmark another checkout with the same
script. This is useful for before/after comparisons without changing branches.
"""

from __future__ import annotations

import argparse
import gc
import os
from pathlib import Path
import platform
import statistics
import sys
import time
from types import SimpleNamespace
from typing import Callable

import numpy as np


PROJECT_ROOT = Path(os.environ.get("MEASURELAB_BENCHMARK_ROOT", Path(__file__).resolve().parents[3])).resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from src.gui.widgets.signal_generator import SignalGenerator  # noqa: E402


SAMPLE_RATE = 48_000
BLOCK_SIZE = 1024


class BenchmarkAudioEngine:
    def __init__(self):
        self.sample_rate = SAMPLE_RATE
        self.block_size = BLOCK_SIZE
        self.calibration = SimpleNamespace(output_gain=1.0)
        self.callback = None

    def register_callback(self, callback):
        self.callback = callback
        return 1

    def unregister_callback(self, _callback_id):
        self.callback = None


Configure = Callable[[SignalGenerator], None]


def _configure_filters(generator: SignalGenerator) -> None:
    for params in (generator.params_L, generator.params_R):
        params.lpf_enabled = True
        params.lpf_freq = 18_000.0
        params.hpf_enabled = True
        params.hpf_freq = 20.0
        params.notch_enabled = True
        params.notch_freq = 1000.0


def _configure_modulation(generator: SignalGenerator) -> None:
    for params in (generator.params_L, generator.params_R):
        params.fm_enabled = True
        params.pm_enabled = True
        params.am_enabled = True


def _configure_golay(order: int) -> Configure:
    def configure(generator: SignalGenerator) -> None:
        for params in (generator.params_L, generator.params_R):
            params.waveform = "golay"
            params.golay_order = order

    return configure


CALLBACK_CASES: tuple[tuple[str, Configure], ...] = (
    ("Sine stereo", lambda _generator: None),
    ("FM + PM + AM", _configure_modulation),
    ("LPF + HPF + Notch", _configure_filters),
    ("Golay order 4", _configure_golay(4)),
    ("Golay order 12", _configure_golay(12)),
)


def benchmark_callback(configure: Configure, iterations: int, warmup: int, repeats: int) -> float:
    measurements = []
    for _ in range(repeats):
        engine = BenchmarkAudioEngine()
        generator = SignalGenerator(engine)
        configure(generator)
        generator.start_generation()
        output = np.empty((BLOCK_SIZE, 2), dtype=np.float32)

        for _ in range(warmup):
            engine.callback(None, output, BLOCK_SIZE, None, None)

        gc.collect()
        gc.disable()
        started = time.perf_counter_ns()
        try:
            for _ in range(iterations):
                engine.callback(None, output, BLOCK_SIZE, None, None)
        finally:
            elapsed = time.perf_counter_ns() - started
            gc.enable()
        measurements.append(elapsed / iterations / 1000.0)

    return statistics.median(measurements)


def benchmark_cached_start(repeats: int) -> float:
    measurements = []
    for repeat in range(repeats):
        np.random.seed(10_000 + repeat)
        engine = BenchmarkAudioEngine()
        generator = SignalGenerator(engine)
        generator.output_mode = "L"
        generator.params_L.noise_color = "grey"
        generator.update_waveform(generator.params_L, "noise", SAMPLE_RATE)

        gc.collect()
        started = time.perf_counter_ns()
        generator.start_generation()
        measurements.append((time.perf_counter_ns() - started) / 1_000_000.0)

    return statistics.median(measurements)


def main() -> None:
    global SAMPLE_RATE, BLOCK_SIZE

    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=3000)
    parser.add_argument("--warmup", type=int, default=100)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--sample-rate", type=int, default=SAMPLE_RATE)
    parser.add_argument("--block-size", type=int, default=BLOCK_SIZE)
    args = parser.parse_args()

    SAMPLE_RATE = args.sample_rate
    BLOCK_SIZE = args.block_size

    block_budget_us = BLOCK_SIZE * 1_000_000.0 / SAMPLE_RATE
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Python: {platform.python_version()} ({platform.platform()})")
    print(f"NumPy: {np.__version__}")
    print(f"Audio block: {SAMPLE_RATE} Hz / {BLOCK_SIZE} samples ({block_budget_us:.2f} us)")
    print()
    print("| Case | Median us/block | Block budget |")
    print("|---|---:|---:|")
    for name, configure in CALLBACK_CASES:
        average_us = benchmark_callback(configure, args.iterations, args.warmup, args.repeats)
        print(f"| {name} | {average_us:.2f} | {average_us * 100.0 / block_budget_us:.3f}% |")

    cached_start_ms = benchmark_cached_start(args.repeats)
    print()
    print(f"Grey-noise start after selection: {cached_start_ms:.2f} ms")


if __name__ == "__main__":
    main()
