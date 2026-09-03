"""Manual benchmark for network-audio protocol and jitter-buffer hot paths.

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
from src.core.network_audio.protocol import (  # noqa: E402
    DIRECTION_CAPTURE,
    decode_audio_packet,
    encode_audio_packet,
    packetize_audio,
)
from src.core.network_audio.retransmission import (  # noqa: E402
    RetransmitHistory,
    history_packet_capacity,
)


SAMPLE_RATE = 48_000
BLOCK_SIZE = 1024
PACKET_FRAMES = 128
CHANNELS = 2


def _timed_buffer_run(jitter_ms: int, iterations: int, *, decode: bool) -> float:
    jitter_frames = max(
        BLOCK_SIZE * 2,
        round(SAMPLE_RATE * jitter_ms / 1000 / BLOCK_SIZE) * BLOCK_SIZE,
    )
    buffer = IndexedAudioBuffer(SAMPLE_RATE * 4, CHANNELS)
    packet = np.zeros((PACKET_FRAMES, CHANNELS), dtype=np.float32)
    encoded_packet = encode_audio_packet(
        packet,
        direction=DIRECTION_CAPTURE,
        flags=0,
        session_id=1,
        sequence=1,
        sample_index=0,
    )
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
                if decode:
                    _header, decoded = decode_audio_packet(encoded_packet)
                    buffer.put(packet_position, decoded)
                else:
                    buffer.put(packet_position, packet)
                packet_position += PACKET_FRAMES
    finally:
        elapsed = time.perf_counter_ns() - started
        gc.enable()
    return elapsed / iterations / 1000.0


def benchmark_buffer(jitter_ms: int, iterations: int, repeats: int, *, decode: bool = False) -> float:
    return statistics.median(_timed_buffer_run(jitter_ms, iterations, decode=decode) for _ in range(repeats))


def _median_timing(operation, iterations: int, repeats: int) -> float:
    measurements = []
    for _ in range(repeats):
        gc.collect()
        gc.disable()
        started = time.perf_counter_ns()
        try:
            for _iteration in range(iterations):
                operation()
        finally:
            elapsed = time.perf_counter_ns() - started
            gc.enable()
        measurements.append(elapsed / iterations / 1000.0)
    return statistics.median(measurements)


def benchmark_encode(iterations: int, repeats: int) -> float:
    audio = np.zeros((PACKET_FRAMES, CHANNELS), dtype=np.float32)
    return _median_timing(
        lambda: encode_audio_packet(
            audio,
            direction=DIRECTION_CAPTURE,
            flags=0,
            session_id=1,
            sequence=1,
            sample_index=0,
        ),
        iterations,
        repeats,
    )


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
    return _median_timing(lambda: decode_audio_packet(packet), iterations, repeats)


def _timed_send_preparation(iterations: int, *, retransmission: bool) -> float:
    audio = np.zeros((BLOCK_SIZE, CHANNELS), dtype=np.float32)
    history = None
    if retransmission:
        retention_seconds = 0.1
        history = RetransmitHistory(
            retention_seconds,
            max_packets=history_packet_capacity(SAMPLE_RATE, BLOCK_SIZE, retention_seconds),
        )
    add_many = getattr(history, "add_many", None)
    sequence = 0
    sample_index = 0
    gc.collect()
    gc.disable()
    started = time.perf_counter_ns()
    try:
        for _iteration in range(iterations):
            packets = packetize_audio(
                audio,
                direction=DIRECTION_CAPTURE,
                flags=0,
                session_id=1,
                first_sequence=sequence,
                sample_index=sample_index,
            )
            if history is not None:
                timestamp = sample_index / SAMPLE_RATE
                if add_many is not None:
                    add_many(sequence, packets, now=timestamp)
                else:
                    for offset, packet in enumerate(packets):
                        history.add(sequence + offset, packet, now=timestamp)
            sequence += len(packets)
            sample_index += BLOCK_SIZE
    finally:
        elapsed = time.perf_counter_ns() - started
        gc.enable()
    return elapsed / iterations / 1000.0


def benchmark_send_preparation(iterations: int, repeats: int, *, retransmission: bool) -> float:
    return statistics.median(_timed_send_preparation(iterations, retransmission=retransmission) for _ in range(repeats))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=2000)
    parser.add_argument("--decode-iterations", type=int, default=100_000)
    parser.add_argument("--send-iterations", type=int, default=20_000)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()

    block_rate = SAMPLE_RATE / BLOCK_SIZE
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Python: {platform.python_version()} ({platform.platform()})")
    print(f"NumPy: {np.__version__}")
    packet_rate = SAMPLE_RATE / PACKET_FRAMES
    encode_us = benchmark_encode(args.decode_iterations, args.repeats)
    decode_us = benchmark_decode(args.decode_iterations, args.repeats)
    send_us = benchmark_send_preparation(args.send_iterations, args.repeats, retransmission=False)
    send_history_us = benchmark_send_preparation(args.send_iterations, args.repeats, retransmission=True)
    print()
    print("| Protocol hot path | Median | One-core real-time load |")
    print("|---|---:|---:|")
    print(f"| Encode | {encode_us:.2f} us/packet | {encode_us * packet_rate / 10_000:.3f}% |")
    print(f"| Decode | {decode_us:.2f} us/packet | {decode_us * packet_rate / 10_000:.3f}% |")
    print(f"| Packetize block | {send_us:.2f} us/block | {send_us * block_rate / 10_000:.3f}% |")
    print(
        f"| Packetize + retransmit history | {send_history_us:.2f} us/block | "
        f"{send_history_us * block_rate / 10_000:.3f}% |"
    )
    print()
    print("| Fixed buffer | Buffer us/block | Decode + buffer us/block | Receive load |")
    print("|---:|---:|---:|---:|")
    for jitter_ms in (20, 100, 500, 1000, 2000):
        buffer_us = benchmark_buffer(jitter_ms, args.iterations, args.repeats)
        receive_us = benchmark_buffer(jitter_ms, args.iterations, args.repeats, decode=True)
        print(f"| {jitter_ms} ms | {buffer_us:.2f} | {receive_us:.2f} | {receive_us * block_rate / 10_000:.3f}% |")


if __name__ == "__main__":
    main()
