"""MIG-005-A/B repeatable BlackHole loopback with explicit per-port routing.

Device I/O is opt-in and exact-name restricted to the installed BlackHole 2ch/16ch.
The unchanged AudioEngine is the 2ch baseline; direct PortAudio is the N-channel
baseline. This is a short diagnostic, not physical latency or performance acceptance.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import sys
import time
from uuid import uuid4

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import migration_audio_candidate as audio  # noqa: E402
from scripts import migration_audio_graph as acquisition  # noqa: E402
from scripts import migration_audio_hardware as hardware  # noqa: E402
from scripts import migration_fft_candidate as candidate  # noqa: E402
from scripts import migration_fft_reference as fft  # noqa: E402

RATE = hardware.RATE
DURATION = hardware.DURATION
MUTE = hardware.MUTE
DEVICES = {"BlackHole 2ch": 2, "BlackHole 16ch": 16}
# Fixed before any device measurement. Compare FS values, not calibrated voltage.
TOLERANCES = {"sample_abs": 2e-6, "interchannel_offset_frames": 1, "backend_amplitude_db": 0.1}


def cases():
    result = []
    for count in (2, 16):
        result.append(
            {
                "id": f"identity-{count}ch",
                "device": f"BlackHole {count}ch",
                "sources": count,
                "gains": np.eye(count).tolist(),
            }
        )
    for sources in (4, 8):
        gains = np.zeros((16, sources))
        # Explicit reverse permutation, duplicate, mixed output and silent ports.
        for port in range(sources):
            gains[port, sources - 1 - port] = 1
        gains[sources, 0] = 1
        gains[sources + 1, :2] = [0.5, 0.25]
        result.append(
            {"id": f"route-{sources}-to-16", "device": "BlackHole 16ch", "sources": sources, "gains": gains.tolist()}
        )
    return result


def stimulus(channels):
    n = np.arange(RATE * DURATION)
    ramp = np.minimum(n / 4800, 1) * np.minimum((len(n) - 1 - n) / 4800, 1)
    signal = np.empty((len(n), channels), dtype="<f4")
    for ch in range(channels):
        signal[:, ch] = 0.015 * np.sin(2 * np.pi * (600 + 150 * ch) * n / RATE) * ramp
        rng = np.random.default_rng(500016 + ch)
        marker = 0.015 * np.convolve(rng.choice([-1.0, 1.0], 4800), np.ones(5) / 5, mode="same")
        signal[24000:28800, ch] = marker
    return signal


def routed(signal, gains):
    output = (signal.astype(np.float64) @ np.asarray(gains, dtype=float).T).astype("<f4")
    output[slice(*MUTE)] = 0
    return output


def request_for(case, generation):
    count = DEVICES[case["device"]]
    ids = [f"generator.{ch}" for ch in range(case["sources"])]
    return {
        "schema_version": 1,
        "device": case["device"],
        "duration_seconds": DURATION,
        "generation": generation,
        "session_id": f"blackhole.{uuid4().hex}",
        "input_channels": count,
        "output_channels": count,
        "source_ids": ids,
        "route": {
            "inputs": ids,
            "outputs": [f"output.port.{ch}" for ch in range(count)],
            "gains": case["gains"],
            "revision": case["id"],
        },
        "mute_interval": list(MUTE),
    }


def exact_device(name):
    import sounddevice as sd

    if name not in DEVICES:
        raise ValueError("Only exact BlackHole 2ch/16ch names are allowed")
    matches = [
        i
        for i, d in enumerate(sd.query_devices())
        if d["name"] == name and d["max_input_channels"] == DEVICES[name] and d["max_output_channels"] == DEVICES[name]
    ]
    if len(matches) != 1:
        raise ValueError("BlackHole device must resolve uniquely with the expected port count")
    return matches[0]


def portaudio_capture(name, values, directory):
    import sounddevice as sd

    count = DEVICES[name]
    if count == 2:
        return hardware.legacy_capture(name, values[:, 0], directory, output_values=values, exact_coreaudio_rate=True)
    directory.mkdir()
    capacity = RATE * (DURATION + 2)
    captured = np.empty((capacity, count), dtype="<f4")
    submitted = np.empty_like(captured)
    input_seconds = np.empty(capacity)
    output_seconds = np.empty(capacity)
    cursor = 0
    statuses, durations, blocks = [], [], []

    def callback(indata, outdata, frames, times, status):
        nonlocal cursor
        started = time.perf_counter()
        if cursor + frames > capacity:
            raise sd.CallbackAbort
        outdata.fill(0)
        available = min(frames, max(0, len(values) - cursor))
        outdata[:available] = values[cursor : cursor + available]
        captured[cursor : cursor + frames] = indata
        submitted[cursor : cursor + frames] = outdata
        offsets = np.arange(frames) / RATE
        input_seconds[cursor : cursor + frames] = times.inputBufferAdcTime + offsets
        output_seconds[cursor : cursor + frames] = times.outputBufferDacTime + offsets
        if status:
            statuses.append({"callback_sample": cursor, "flags": str(status), "affected_interval": None})
        cursor += frames
        blocks.append(frames)
        durations.append((time.perf_counter() - started) * 1000)

    index = exact_device(name)
    settings = sd.CoreAudioSettings(change_device_parameters=True, fail_if_conversion_required=True)
    stream = sd.Stream(
        device=(index, index),
        samplerate=RATE,
        blocksize=256,
        channels=(count, count),
        dtype="float32",
        callback=callback,
        extra_settings=(settings, settings),
    )
    try:
        stream.start()
        deadline = time.perf_counter() + DURATION + 0.2
        while time.perf_counter() < deadline:
            if not stream.active:
                raise RuntimeError("PortAudio stream ended early")
            time.sleep(0.02)
        started = time.perf_counter()
        stream.stop()
        stream.stop()
        stream.close()
        stop_ms = (time.perf_counter() - started) * 1000
    finally:
        stream.close()
    captured[:cursor].tofile(directory / "input.bin")
    submitted[:cursor].tofile(directory / "output.bin")
    metadata = {"frames": cursor, "channels": count, "dtype": "<f4", "samples": list(range(cursor)), "gaps": []}
    report = {
        "schema_version": 1,
        "backend": "direct PortAudio / sounddevice (N-channel baseline)",
        "device": name,
        "input": {**metadata, "seconds": input_seconds[:cursor].tolist()},
        "output": {**metadata, "seconds": output_seconds[:cursor].tolist()},
        "state": "stopped",
        "stop_ms": stop_ms,
        "statuses": statuses,
        "block_frames": sorted(set(blocks)),
        "callback_ms": {key: float(np.percentile(durations, pct)) for key, pct in [("p50", 50), ("p99", 99)]},
        "timestamp_kind": "PortAudio ADC/DAC timestamps; uncertainty unknown",
    }
    fft.write_json(directory / "manifest.json", report)
    return report


def load_capture(directory, direction, channels):
    raw = json.loads((directory / "manifest.json").read_bytes())
    metadata = raw[direction]
    frames = metadata["frames"]
    values = np.frombuffer((directory / f"{direction}.bin").read_bytes(), dtype="<f4")
    samples = np.asarray(metadata["samples"], dtype=np.int64)
    seconds = np.array([np.nan if value is None else value for value in metadata["seconds"]])
    if (
        metadata["channels"] != channels
        or metadata["dtype"] != "<f4"
        or frames <= 0
        or values.size != frames * channels
        or not np.all(np.isfinite(values))
        or samples.shape != (frames,)
        or seconds.shape != (frames,)
        or not np.array_equal(samples, np.arange(frames))
        or metadata["gaps"]
        or np.any(np.isinf(seconds))
    ):
        raise ValueError("Invalid capture bytes, port count, sample positions, timestamp or queue gap")
    return values.reshape(frames, channels), raw


def analyze(directory, expected, source):
    from scipy.signal import fftconvolve

    channels = expected.shape[1]
    values, raw = load_capture(directory, "input", channels)
    output, _ = load_capture(directory, "output", channels)
    reference = np.zeros_like(output)
    length = min(len(output), len(expected))
    reference[:length] = expected[:length]
    submitted_error = float(np.max(np.abs(output.astype(float) - reference)))
    active = np.flatnonzero(np.any(expected != 0, axis=0))
    offsets = []
    for port in active:
        marker = expected[24000:28800, port].astype(float)
        correlation = fftconvolve(values[:72000, port], marker[::-1], mode="valid")
        offsets.append(int(np.argmax(np.abs(correlation))) - 24000)
    anchor = offsets[0]
    first = max(10000, -anchor)
    last = min(len(expected) - 512, len(values) - anchor)
    if first >= last or last - first < 3 * RATE or abs(anchor) > RATE:
        raise ValueError("Missing/insufficient aligned loopback signal")
    observed = values[first + anchor : last + anchor].astype(float)
    reference_input = expected[first:last].astype(float)
    errors = np.max(np.abs(observed - reference_input), axis=0)
    stable = values[RATE + anchor : 2 * RATE + anchor].astype(float)
    peaks = np.sqrt(np.mean(stable**2, axis=0))
    quiet = values[116000 + anchor : 124000 + anchor]
    muted_output = output[slice(*MUTE)]
    checks = {
        "submitted_signal": submitted_error <= TOLERANCES["sample_abs"],
        "all_input_ports": bool(np.all(errors <= TOLERANCES["sample_abs"])),
        "interchannel_offset": max(offsets) - min(offsets) <= TOLERANCES["interchannel_offset_frames"],
        "input_mute": bool(len(quiet) == 8000 and np.max(np.abs(quiet)) <= TOLERANCES["sample_abs"]),
        "tap_mute": bool(
            len(muted_output) == MUTE[1] - MUTE[0]
            and np.all(muted_output == 0)
            and np.max(np.abs(source[slice(*MUTE)])) > 0
        ),
        "stopped": raw.get("state") == "stopped",
        "no_errors": not any(raw.get(key, 0) for key in ("errors", "xruns", "callback_rejections", "callback_errors"))
        and not raw.get("statuses"),
    }
    return {
        "checks": checks,
        "status": "pass" if all(checks.values()) else "fail",
        "submitted_max_abs_error": submitted_error,
        "input_max_abs_error_by_port": errors.tolist(),
        "active_ports": active.tolist(),
        "rms_fs_by_port": peaks.tolist(),
        "marker_offset_frames_by_active_port": offsets,
        "compared_interval": [first, last],
        "physical_delay_ms": None,
        "delay_accuracy_verdict": "virtual_loopback_unverified_clock_mapping",
        "hashes": {
            name: fft.digest((directory / name).read_bytes()) for name in ("input.bin", "output.bin", "manifest.json")
        },
    }


def compare_pair(left, right):
    ports = left["active_ports"]
    if ports != right["active_ports"]:
        raise ValueError("Backend active port mismatch")
    amplitudes = [float(20 * np.log10(right["rms_fs_by_port"][p] / left["rms_fs_by_port"][p])) for p in ports]
    success = all(np.isfinite(db) and abs(db) <= TOLERANCES["backend_amplitude_db"] for db in amplitudes)
    return {"amplitude_difference_db_by_active_port": amplitudes, "status": "pass" if success else "fail"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--virtual-device", action="store_true")
    parser.add_argument("--runs", type=int, choices=range(1, 4), default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.virtual_device:
        parser.error("BlackHole I/O requires explicit --virtual-device")
    if args.output.exists():
        parser.error("Output directory exists; choose a new run path")
    # Resolve every device before creating output or building/opening a stream.
    import sounddevice as sd

    inventory = {name: dict(sd.query_devices(exact_device(name))) for name in DEVICES}
    args.output.mkdir(parents=True)
    report = {
        "schema_version": 1,
        "task": "MIG-005-virtual-diagnostic",
        "devices": inventory,
        "host": {"platform": platform.platform(), "machine": platform.machine()},
        "sounddevice": sd.__version__,
        "portaudio": list(sd.get_portaudio_version()),
        "workload": {
            "rate": RATE,
            "block_frames": 256,
            "dtype": "<f4",
            "duration_seconds": DURATION,
            "mute_interval": list(MUTE),
            "coreaudio_change_device_parameters": True,
            "coreaudio_fail_if_conversion_required": True,
        },
        "tolerances": TOLERANCES,
        "runs": [],
        "pairs": [],
        "cancels": [],
        "commands": [],
        "limitations": [
            "Short headless diagnostic, not 3 x 10 minute performance or P2 acceptance",
            "2ch uses unchanged AudioEngine; N-channel uses direct PortAudio, not the legacy engine",
            "Virtual loopback cannot establish physical delay, USB recovery, hardware gain or voltage",
            "Input.raw acquisition/history/shared FFT tested; dynamic output route, device exclusivity and Qt remain untested",
            "Timestamp uncertainty and XRUN affected intervals remain unknown",
        ],
    }
    success = False
    try:
        binary, build = audio.build("audio-probe", release=True)
        report["commands"].append(build)
        report["binary_sha256"] = fft.digest(binary.read_bytes())
        report["source_sha256"] = {
            str(p.relative_to(ROOT)): fft.digest(p.read_bytes())
            for p in [
                Path(__file__),
                ROOT / "scripts/migration_audio_hardware.py",
                ROOT / "src/core/audio_engine.py",
                ROOT / "native/audio-probe/src/main.rs",
                ROOT / "native/audio-probe/src/lib.rs",
                ROOT / "native/audio-core/src/lib.rs",
                ROOT / "native/Cargo.lock",
                ROOT / "native/graph-core/Cargo.toml",
                ROOT / "scripts/migration_audio_graph.py",
                *sorted((ROOT / "native/graph-core/src").rglob("*.rs")),
                *sorted((ROOT / "native/dsp-core/src").rglob("*.rs")),
            ]
        }
        generation = 0
        for case in cases():
            source = stimulus(case["sources"])
            expected = routed(source, case["gains"])
            signal_path = args.output / f"{case['id']}-mixed.f32"
            source.tofile(signal_path)
            for run in range(1, args.runs + 1):
                metrics = []
                for backend in ("portaudio", "cpal"):
                    generation += 1
                    directory = args.output / f"{case['id']}-{run}-{backend}"
                    if backend == "portaudio":
                        raw = portaudio_capture(case["device"], expected, directory)
                    else:
                        request = request_for(case, generation)
                        request_path = args.output / f"{directory.name}-request.json"
                        fft.write_json(request_path, request)
                        report["commands"].append(
                            candidate.run_command(
                                [str(binary), str(request_path), str(signal_path), str(directory)], timeout=30
                            )
                        )
                        raw = json.loads((directory / "manifest.json").read_bytes())
                        if (
                            raw["format"]["generation"] != generation
                            or raw["format"]["output_ids"] != request["route"]["outputs"]
                        ):
                            raise ValueError("CPAL generation or output identity mismatch")
                        acquisition.validate_device_graph(raw)
                    result = analyze(directory, expected, source)
                    metrics.append(result)
                    report["runs"].append(
                        {
                            "case": case,
                            "run": run,
                            "backend": backend,
                            "directory": str(directory),
                            "metrics": result,
                            "stimulus_sha256": fft.digest(signal_path.read_bytes()),
                            "lifecycle": {
                                k: raw.get(k)
                                for k in (
                                    "backend",
                                    "state",
                                    "stop_ms",
                                    "statuses",
                                    "errors",
                                    "xruns",
                                    "input_callback",
                                    "output_callback",
                                    "callback_ms",
                                    "queues",
                                    "analysis_graph",
                                )
                            },
                        }
                    )
                    fft.write_json(args.output / "report.json", report)
                    print(
                        f"{directory.name}: {result['status']}, input max error {max(result['input_max_abs_error_by_port']):.3g}",
                        flush=True,
                    )
                report["pairs"].append({"case": case["id"], "run": run, **compare_pair(*metrics)})
            generation += 1
            request = {**request_for(case, generation), "cancel_preparing": True}
            path = args.output / f"{case['id']}-cancel-request.json"
            fft.write_json(path, request)
            directory = args.output / f"{case['id']}-cancel"
            report["commands"].append(
                candidate.run_command([str(binary), str(path), str(signal_path), str(directory)], timeout=30)
            )
            raw = json.loads((directory / "manifest.json").read_bytes())
            acquisition.validate_device_graph(raw)
            passed = (
                raw["state"] == "cancelled"
                and raw["input"]["frames"] == raw["output"]["frames"] == 0
                and raw["errors"] == raw["xruns"] == raw["callback_rejections"] == 0
            )
            report["cancels"].append(
                {
                    "case": case["id"],
                    "status": "pass" if passed else "fail",
                    "manifest_sha256": fft.digest((directory / "manifest.json").read_bytes()),
                }
            )
        success = all(r["metrics"]["status"] == "pass" for r in report["runs"]) and all(
            r["status"] == "pass" for r in [*report["pairs"], *report["cancels"]]
        )
        report["status"] = "pass" if success else "fail"
    except Exception as exc:
        report["status"] = "fail"
        report["failure"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        fft.write_json(args.output / "report.json", report)
    print(f"Virtual diagnostic: {report['status']}; {args.output / 'report.json'}")
    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
