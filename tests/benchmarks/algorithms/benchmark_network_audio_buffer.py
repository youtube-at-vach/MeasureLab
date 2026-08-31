"""Manual benchmark for network-audio packet decode and jitter buffering.

Run from the repository root:

    ./.venv/bin/python tests/benchmarks/algorithms/benchmark_network_audio_buffer.py

Set ``MEASURELAB_BENCHMARK_ROOT`` to benchmark another checkout with the same
script. This supports repeatable before/after comparisons without changing
branches.
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

import numpy as np


PROJECT_ROOT = Path(os.environ.get("MEASURELAB_BENCHMARK_ROOT", Path(__file__).resolve().parents[3])).resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.network_audio.indexed_buffer import IndexedAudioBuffer  # noqa: E402
from src.core.network_audio.protocol import DIRECTION_CAPTURE, decode_audio_packet, encode_audio_packet  # noqa: E402


SAMPLE_RATE = 48_000
BLOCK_SIZE = 1024
PACKET_FRAMES = 128
CHANNELS = 2


def _timed_buffer_run(jitter_ms: int, iterations: int) -> float:
    jitter_frames = max(
        BLOCK_SIZE * 2,
        round(SAMPLE_RATE * jitter_ms / 1000 / BLOCK_SIZE) * BLOCK_SIZE,
    )
    buffer = IndexedAudioBuffer(SAMPLE_RATE * 4, CHANNELS)
    packet = np.zeros((PACKET_FRAMES, CHANNELS), dtype=np.float32)
    packet_position = 0
    while packet_position < jitter_frames + BLOCK_SIZE:
        buffer.put(packet_position, packet)
        packet_position += PACKET_FRAMES

    read_position = 0
    gc.collect()
    gc.disable()
    started = time.perf_counter_ns()
    try:
        for _ in range(iterations):
            buffer.read(read_position, BLOCK_SIZE)
            read_position += BLOCK_SIZE
            for _packet_index in range(BLOCK_SIZE // PACKET_FRAMES):
                buffer.put(packet_position, packet)
                packet_position += PACKET_FRAMES
    finally:
        elapsed = time.perf_counter_ns() - started
        gc.enable()
    return elapsed / iterations / 1000.0


def benchmark_buffer(jitter_ms: int, iterations: int, repeats: int) -> float:
    return statistics.median(_timed_buffer_run(jitter_ms, iterations) for _ in range(repeats))


def benchmark_decode(iterations: int, repeats: int) -> float:
    audio = np.zeros((PACKET_FRAMES, CHANNELS), dtype=np.float32)
    packet = encode_audio_packet(
        audio,
        direction=DIRECTION_CAPTURE,
        flags=0,
        session_id=1,
        sequence=1,
        sample_index=0,
    )
    measurements = []
    for _ in range(repeats):
        gc.collect()
        gc.disable()
        started = time.perf_counter_ns()
        try:
            for _iteration in range(iterations):
                decode_audio_packet(packet)
        finally:
            elapsed = time.perf_counter_ns() - started
            gc.enable()
        measurements.append(elapsed / iterations / 1000.0)
    return statistics.median(measurements)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=2000)
    parser.add_argument("--decode-iterations", type=int, default=100_000)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()

    block_rate = SAMPLE_RATE / BLOCK_SIZE
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Python: {platform.python_version()} ({platform.platform()})")
    print(f"NumPy: {np.__version__}")
    print(f"Decode median: {benchmark_decode(args.decode_iterations, args.repeats):.2f} us/packet")
    print()
    print("| Fixed buffer | Median us/block | One-core real-time load |")
    print("|---:|---:|---:|")
    for jitter_ms in (20, 100, 500, 1000, 2000):
        average_us = benchmark_buffer(jitter_ms, args.iterations, args.repeats)
        print(f"| {jitter_ms} ms | {average_us:.2f} | {average_us * block_rate / 10_000:.3f}% |")


if __name__ == "__main__":
    main()
