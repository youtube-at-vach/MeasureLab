"""MIG-005-B short UAC-232 comparison, explicitly enabled with --hardware.

Alternates unchanged AudioEngine/PortAudio and CPAL using one saved f32 signal.
Raw bytes, timestamps, startup XRUNs and failed checks are retained locally.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import platform
import sys
import time
from uuid import uuid4
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import migration_audio_candidate as audio  # noqa: E402
from scripts import migration_fft_candidate as candidate  # noqa: E402
from scripts import migration_fft_reference as fft  # noqa: E402

RATE = 48000
DURATION = 4
MUTE = (108032, 132096)
# Fixed before measurement. Absolute volts and timestamp uncertainty are unknown.
TOLERANCES = {
    "backend_amplitude_db": 0.1,
    "attenuator_nominal_db": -20.0,
    "attenuator_deviation_db": 1.0,
    "interchannel_delay_samples": 1,
    "backend_relative_phase_degrees": 1.0,
    "mute_tone_reduction_db": 60.0,
}


def stimulus():
    n = np.arange(RATE * DURATION)
    amplitude = 10 ** (-30 / 20)
    signal = amplitude * np.sin(2 * np.pi * 1000 * n / RATE)
    ramp = np.minimum(n / 4800, 1) * np.minimum((len(n) - 1 - n) / 4800, 1)
    signal *= ramp
    rng = np.random.default_rng(232005)
    marker = amplitude * np.convolve(rng.choice([-1.0, 1.0], 4800), np.ones(5) / 5, mode="same")
    signal[24000:28800] = marker
    return signal.astype("<f4")


def exact_device(name):
    import sounddevice as sd

    matches = [
        i
        for i, d in enumerate(sd.query_devices())
        if d["name"] == name and d["max_input_channels"] >= 2 and d["max_output_channels"] >= 2
    ]
    if len(matches) != 1:
        raise ValueError("Device must resolve uniquely with at least 2 input and 2 output ports")
    return matches[0]


def legacy_capture(name, signal, directory):
    import sounddevice as sd
    from src.core.audio_engine import AudioEngine
    from src.core.config_manager import ConfigManager

    directory.mkdir()
    state_dir = directory / "state"
    state_dir.mkdir()
    # Process-local storage isolation; AudioEngine itself remains unchanged.
    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, {"XDG_DATA_HOME": str(state_dir / "data")}))
        stack.enter_context(patch.object(ConfigManager, "get_user_data_dir", staticmethod(lambda: str(state_dir))))
        stack.enter_context(
            patch.object(ConfigManager, "_resolve_config_path", lambda self, filename: str(state_dir / filename))
        )
        engine = AudioEngine()
        engine.set_devices(exact_device(name), exact_device(name))
        engine.set_sample_rate(RATE)
        engine.set_block_size(256)
        engine.set_channel_mode("stereo", "stereo")
        engine.set_audio_engine_64bit(False)
        capacity = RATE * (DURATION + 2)
        captured = np.empty((capacity, 2), dtype="<f4")
        submitted = np.empty_like(captured)
        input_seconds = np.empty(capacity)
        output_seconds = np.empty(capacity)
        # Diagnostic instrumentation has preallocated storage but Python/GIL/legacy locks remain.
        durations, blocks, statuses = [], [], []
        cursor, position = 0, 0
        original = engine._master_callback

        def generator(_input, output, frames, _times, _status):
            nonlocal cursor
            output.fill(0)
            count = min(frames, max(0, len(signal) - cursor))
            output[:count, 0] = signal[cursor : cursor + count]
            cursor += frames

        def observed(indata, outdata, frames, times, status):
            nonlocal position
            started = time.perf_counter()
            engine.mute_output = MUTE[0] <= position < MUTE[1]
            original(indata, outdata, frames, times, status)
            if position + frames > capacity:
                raise sd.CallbackAbort
            captured[position : position + frames] = indata
            submitted[position : position + frames] = outdata
            offsets = np.arange(frames) / RATE
            input_seconds[position : position + frames] = times.inputBufferAdcTime + offsets
            output_seconds[position : position + frames] = times.outputBufferDacTime + offsets
            if status:
                statuses.append({"callback_sample": position, "flags": str(status), "affected_interval": None})
            position += frames
            blocks.append(frames)
            durations.append((time.perf_counter() - started) * 1000)

        engine._master_callback = observed
        stop_ms = None
        try:
            engine.register_callback(generator)
            if not engine.is_active():
                raise RuntimeError("Legacy AudioEngine failed to start")
            latency = list(engine.stream.latency)
            deadline = time.perf_counter() + DURATION + 0.2
            while time.perf_counter() < deadline:
                time.sleep(0.02)
            started = time.perf_counter()
            engine.stop_stream()
            engine.stop_stream()
            stop_ms = (time.perf_counter() - started) * 1000
            if engine.last_callback_error is not None:
                raise RuntimeError(f"Legacy callback failed: {engine.last_callback_error}")
        finally:
            engine.stop_stream()
            engine.unregister_callback(generator)
        captured[:position].tofile(directory / "input.bin")
        submitted[:position].tofile(directory / "output.bin")
        header = {"frames": position, "channels": 2, "dtype": "<f4", "samples": list(range(position)), "gaps": []}
        report = {
            "schema_version": 1,
            "backend": "legacy AudioEngine / PortAudio",
            "device": name,
            "input": {**header, "seconds": input_seconds[:position].tolist()},
            "output": {**header, "seconds": output_seconds[:position].tolist()},
            "callback_ms": {
                "p50": float(np.percentile(durations, 50)),
                "p95": float(np.percentile(durations, 95)),
                "p99": float(np.percentile(durations, 99)),
                "max": max(durations),
            },
            "block_frames": sorted(set(blocks)),
            "statuses": statuses,
            "stop_ms": stop_ms,
            "state": "stopped",
            "latency_seconds": latency,
            "callback_errors": engine.callback_error_count,
            "timestamp_kind": "PortAudio ADC/DAC timestamps; calibration/uncertainty unknown",
            "adapter": "preallocated raw input/submitted-output capture; unchanged engine mute at block boundaries",
        }
        fft.write_json(directory / "manifest.json", report)
        return report


def load_capture(directory, direction):
    report = json.loads((directory / "manifest.json").read_bytes())
    metadata = report[direction]
    if metadata["channels"] != 2 or metadata["dtype"] != "<f4" or metadata["frames"] <= 0:
        raise ValueError("Invalid capture shape/format")
    raw = (directory / f"{direction}.bin").read_bytes()
    values = np.frombuffer(raw, dtype="<f4")
    samples = np.array(metadata["samples"], dtype=np.int64)
    seconds = np.array([np.nan if value is None else value for value in metadata["seconds"]])
    if (
        values.size != metadata["frames"] * 2
        or samples.shape != (metadata["frames"],)
        or seconds.shape != samples.shape
        or not np.all(np.isfinite(values))
        or len(samples) > 1
        and np.any(np.diff(samples) <= 0)
    ):
        raise ValueError("Invalid capture bytes/sample positions/timestamps")
    return values.reshape(-1, 2), samples, seconds, metadata["gaps"]


def tone_peak(values):
    n = np.arange(len(values))
    phasor = 2 * (np.exp(-2j * np.pi * 1000 * n / RATE) @ values.astype(float)) / len(values)
    return np.abs(phasor), np.angle(phasor, deg=True)


def analyze(directory, signal):
    from scipy.signal import fftconvolve

    values, samples, seconds, gaps = load_capture(directory, "input")
    out, out_samples, out_seconds, out_gaps = load_capture(directory, "output")
    if gaps or out_gaps or np.any(np.diff(samples) != 1) or np.any(np.diff(out_samples) != 1):
        raise ValueError("Measurement queue gaps: retained raw capture is invalid for this comparison")
    marker = signal[24000:28800].astype(float)
    # Only search the first 1.5 seconds; later steady tone is not a sync marker.
    correlations = [fftconvolve(values[:72000, ch], marker[::-1], mode="valid") for ch in (0, 1)]
    starts = [int(np.argmax(np.abs(c))) for c in correlations]
    # Compare same acquired interval, retaining within-stream relative phase.
    anchor = starts[1] - 24000
    stable = values[anchor + RATE : anchor + 2 * RATE]
    quiet = values[anchor + 116000 : anchor + 124000]
    if anchor < -24000 or len(stable) != RATE or len(quiet) != 8000:
        raise ValueError("Insufficient aligned tone/mute capture")
    peak, phase = tone_peak(stable)
    mute_peak, _ = tone_peak(quiet)
    if np.any(peak <= 1e-7):
        raise ValueError("Loopback signal missing")
    attenuation = float(20 * np.log10(peak[0] / peak[1]))
    relative_phase = float((phase[0] - phase[1] + 180) % 360 - 180)
    muted = (out_samples >= MUTE[0]) & (out_samples < MUTE[1])
    output_mute = bool(np.any(muted) and np.all(out[muted] == 0))
    # Source remains nonzero and R remains explicitly unconnected (zero) in submitted output.
    source_nonzero = bool(np.max(np.abs(signal[slice(*MUTE)])) > 0)
    mute_db = (20 * np.log10(peak / np.maximum(mute_peak, 1e-20))).tolist()
    # Diagnostic delay only; separate CPAL callbacks use host estimates with unknown uncertainty.
    output_marker = int(np.searchsorted(out_samples, 24000))
    latency = [
        (
            float(seconds[s] - out_seconds[output_marker]) * 1000
            if np.isfinite(seconds[s]) and np.isfinite(out_seconds[output_marker])
            else None
        )
        for s in starts
    ]
    expected_output = np.zeros(len(out_samples), dtype="<f4")
    available = out_samples < len(signal)
    expected_output[available] = signal[out_samples[available]]
    expected_output[muted] = 0
    checks = {
        "submitted_signal": bool(np.array_equal(out[:, 0], expected_output)),
        "attenuator": abs(attenuation - TOLERANCES["attenuator_nominal_db"]) <= TOLERANCES["attenuator_deviation_db"],
        "interchannel_delay": abs(starts[0] - starts[1]) <= TOLERANCES["interchannel_delay_samples"],
        "physical_mute": all(v >= TOLERANCES["mute_tone_reduction_db"] for v in mute_db),
        "tap_mute": output_mute and source_nonzero,
        "right_output_zero": bool(np.all(out[:, 1] == 0)),
    }
    return {
        "peak_fs": peak.tolist(),
        "attenuation_db": attenuation,
        "relative_phase_degrees": relative_phase,
        "marker_input_samples": starts,
        "interchannel_delay_samples": starts[0] - starts[1],
        "raw_timestamp_marker_difference_ms": latency,
        "physical_delay_ms": None,
        "buffered_marker_offset_frames": anchor,
        "delay_accuracy_verdict": "unknown_timestamp_uncertainty",
        "mute_tone_reduction_db": mute_db,
        "checks": checks,
        "status": "pass" if all(checks.values()) else "fail",
        "hashes": {
            name: fft.digest((directory / name).read_bytes()) for name in ("input.bin", "output.bin", "manifest.json")
        },
    }


def compare_pair(left, right):
    amplitude = (20 * np.log10(np.array(right["peak_fs"]) / np.array(left["peak_fs"]))).tolist()
    phase = float((right["relative_phase_degrees"] - left["relative_phase_degrees"] + 180) % 360 - 180)
    checks = {
        "amplitude": all(abs(db) <= TOLERANCES["backend_amplitude_db"] for db in amplitude),
        "phase": abs(phase) <= TOLERANCES["backend_relative_phase_degrees"],
    }
    return {
        "amplitude_difference_db": amplitude,
        "relative_phase_difference_degrees": phase,
        "checks": checks,
        "status": "pass" if all(checks.values()) else "fail",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hardware", action="store_true")
    parser.add_argument("--device", default="ZOOM UAC-232")
    parser.add_argument("--runs", type=int, choices=range(1, 4), default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.hardware:
        parser.error("Device I/O requires explicit --hardware")
    if args.output.exists():
        parser.error("Output directory already exists; use a new run path")
    args.output.mkdir(parents=True)
    signal = stimulus()
    signal_path = args.output / "mixed.f32"
    signal.tofile(signal_path)
    binary, build_record = audio.build("audio-probe", release=True)
    import sounddevice as sd

    device = dict(sd.query_devices(exact_device(args.device)))
    report = {
        "schema_version": 1,
        "task": "MIG-005-B-diagnostic",
        "host": {"platform": platform.platform(), "machine": platform.machine()},
        "device": device,
        "sounddevice": sd.__version__,
        "portaudio": list(sd.get_portaudio_version()),
        "wiring": "output.L split: -20 dB attenuator to input.L; direct to input.R; output.R has no cable",
        "workload": {
            "sample_rate": RATE,
            "block_frames": 256,
            "dtype": "<f4",
            "duration_seconds": DURATION,
            "tone_hz": 1000,
            "output_peak_dbfs": -30,
            "mute_interval": list(MUTE),
        },
        "tolerances": TOLERANCES,
        "stimulus_sha256": fft.digest(signal_path.read_bytes()),
        "commands": [build_record],
        "runs": [],
        "pairs": [],
        "source_sha256": {
            str(p.relative_to(ROOT)): fft.digest(p.read_bytes())
            for p in [
                ROOT / "src/core/audio_engine.py",
                ROOT / "native/audio-probe/src/main.rs",
                ROOT / "native/audio-core/src/lib.rs",
                ROOT / "native/Cargo.lock",
                Path(__file__),
            ]
        },
        "binary_sha256": fft.digest(binary.read_bytes()),
        "limitations": [
            "Short headless diagnostic, not the 3 x 10 minute performance protocol or P2 acceptance",
            "No voltage calibration; user-specified nominal attenuator only",
            "Timestamp uncertainty unknown: physical delay is diagnostic, not accuracy acceptance",
            "XRUN intervals unknown; errors retained, not zero-filled or considered loss-free",
            "Physical output.R, unplug/replug, device exclusivity and other OS not tested",
            "Legacy capture instrumentation adds overhead; this is not a GUI workload",
            "Raw marker differences can be negative: ADC/DAC timestamp mapping is unverified",
        ],
    }
    try:
        for run in range(args.runs):
            metrics = []
            for backend in ("portaudio", "cpal"):
                directory = args.output / f"{run + 1}-{backend}"
                if backend == "portaudio":
                    raw = legacy_capture(args.device, signal, directory)
                else:
                    request = {
                        "schema_version": 1,
                        "device": args.device,
                        "duration_seconds": DURATION,
                        "generation": run + 1,
                        "session_id": f"uac232.{uuid4().hex}",
                    }
                    request_path = args.output / f"{run + 1}-request.json"
                    fft.write_json(request_path, request)
                    report["commands"].append(
                        candidate.run_command(
                            [str(binary), str(request_path), str(signal_path), str(directory)], timeout=30
                        )
                    )
                    raw = json.loads((directory / "manifest.json").read_bytes())
                result = analyze(directory, signal)
                metrics.append(result)
                report["runs"].append(
                    {
                        "run": run + 1,
                        "backend": backend,
                        "directory": str(directory),
                        "metrics": result,
                        "lifecycle": {
                            key: raw.get(key)
                            for key in (
                                "state",
                                "stop_ms",
                                "errors",
                                "xruns",
                                "statuses",
                                "callback_ms",
                                "input_callback",
                                "output_callback",
                            )
                        },
                    }
                )
                fft.write_json(args.output / "report.json", report)
                print(f"{run + 1}-{backend}: {result['status']}, L/R {result['attenuation_db']:.5f} dB", flush=True)
            report["pairs"].append(compare_pair(*metrics))
        cancel_request = args.output / "cancel-request.json"
        fft.write_json(
            cancel_request,
            {
                "schema_version": 1,
                "device": args.device,
                "duration_seconds": DURATION,
                "generation": args.runs + 1,
                "cancel_preparing": True,
                "session_id": f"uac232.{uuid4().hex}",
            },
        )
        cancel_output = args.output / "cancel-preparing"
        report["commands"].append(
            candidate.run_command([str(binary), str(cancel_request), str(signal_path), str(cancel_output)], timeout=30)
        )
        cancel = json.loads((cancel_output / "manifest.json").read_bytes())
        report["cancel_preparing"] = {
            "state": cancel["state"],
            "input_frames": cancel["input"]["frames"],
            "output_frames": cancel["output"]["frames"],
        }
        success = (
            all(item["metrics"]["status"] == "pass" for item in report["runs"])
            and all(pair["status"] == "pass" for pair in report["pairs"])
            and report["cancel_preparing"] == {"state": "cancelled", "input_frames": 0, "output_frames": 0}
        )
        report["status"] = "pass" if success else "fail"
    except Exception as exc:
        report["status"] = "fail"
        report["failure"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        fft.write_json(args.output / "report.json", report)
    print(f"Hardware diagnostic: {report['status']}; {args.output / 'report.json'}")
    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
