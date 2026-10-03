"""Opt-in BlackHole native callbacks -> explicit f32 widening -> shared f64 FIR/FFT."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import tomllib

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import migration_core_reference as core  # noqa: E402
from scripts import migration_fft_candidate as candidate  # noqa: E402
from scripts import migration_fft_reference as fft  # noqa: E402
from scripts import migration_filter_candidate as filters  # noqa: E402
from scripts import migration_filter_input as widening  # noqa: E402
from scripts import migration_filter_oracle as oracle  # noqa: E402

FRAMES = 8192
BINS = [13, 23, 41, 53, 67, 83, 101, 127]
CASES = [
    {"id": "2ch", "device": "BlackHole 2ch", "channels": 2, "ports": [1, 0]},
    {"id": "4ch", "device": "BlackHole 16ch", "channels": 16, "ports": [15, 13, 11, 9]},
    {"id": "8ch", "device": "BlackHole 16ch", "channels": 16, "ports": [15, 13, 11, 9, 7, 5, 3, 1]},
]
RUNNERS = (*widening.RUNNERS, "scripts/migration_filter_live.py")


def build():
    env = candidate.cargo_environment()
    version = tomllib.loads((ROOT / "native/rust-toolchain.toml").read_text())["toolchain"]["channel"]
    record = candidate.run_command(
        [
            candidate.rust_tool("cargo", env),
            f"+{version}",
            "build",
            "--offline",
            "--locked",
            "--manifest-path",
            str(ROOT / "native/Cargo.toml"),
            "-p",
            "audio-probe",
            "--bin",
            "filter-input-live",
        ],
        env=env,
    )
    return ROOT / "native/target/debug/filter-input-live", record


def source_hashes():
    source = filters.source_hashes()
    for crate in ("audio-probe", "portaudio-input"):
        paths = [ROOT / "native" / crate / "Cargo.toml", *sorted((ROOT / "native" / crate).rglob("*.rs"))]
        source.update({str(p.relative_to(ROOT / "native")): fft.digest(p.read_bytes()) for p in paths})
    return source


def request_for(case, backend, library):
    name = f"filter-live.{backend}.{case['id']}"
    return {
        "schema_version": 1,
        "input_conversion": "F32ToF64Exact",
        "frames": FRAMES,
        "library": str(library) if backend == "PortAudio" else None,
        "binding": {
            "backend": backend,
            "device": case["device"],
            "device_channels": case["channels"],
            "sample_format": "F32",
            "format": {
                "stream_id": name,
                "generation": 1,
                "timebase_id": f"{name}.clock",
                "clock_domain": f"{'cpal' if backend == 'Cpal' else 'portaudio'}.device:{case['device']}",
                "rate": [48000, 1],
                "input_ids": [f"input.{c}" for c in range(len(case["ports"]))],
                "input_ports": case["ports"],
                "output_ids": [],
                "output_ports": [],
            },
        },
    }


def validation_request(request, case):
    result = filters.request_for(case, acquisition=True)
    fmt = request["binding"]["format"]
    result["source"].update(
        stream_id=fmt["stream_id"], generation=fmt["generation"], channel_ids=fmt["input_ids"], precision="F32"
    )
    result["source"]["timebase"].update(
        id=fmt["timebase_id"], clock_domain=fmt["clock_domain"], generation=fmt["generation"]
    )
    result.update(
        input_conversion="F32ToF64Exact",
        output_stream=f"{fmt['stream_id']}.fir",
        output_timebase=f"{fmt['timebase_id']}.fir",
        frames=request["frames"],
        gaps=[],
        chunks={"live": [256]},
    )
    return result


def validate_metrics(metrics, request):
    if not isinstance(metrics, dict) or set(metrics) != {
        "schema_version",
        "binding",
        "input",
        "queue",
        "stop_ms",
        "error",
        "failed",
    }:
        raise fft.ReferenceError("Live filter metric fields mismatch")
    if core.json_bytes({k: metrics[k] for k in ("schema_version", "binding", "error", "failed")}) != core.json_bytes(
        {"schema_version": 1, "binding": request["binding"], "error": None, "failed": False}
    ):
        raise fft.ReferenceError("Live filter failed or binding changed")
    counter = metrics["input"]
    if (
        not isinstance(counter, dict)
        or any(type(counter.get(k)) is not int or counter[k] != 0 for k in ("errors", "xruns", "rejected"))
        or counter.get("closed") is not True
    ):
        raise fft.ReferenceError("Live filter callback failure or stream not closed")
    if (
        any(type(counter.get(k)) is not int or counter[k] <= 0 for k in ("callbacks", "frames"))
        or counter["frames"] < request["frames"]
    ):
        raise fft.ReferenceError("Live filter callback frame count missing")
    if request["binding"]["backend"] == "PortAudio" and (
        counter.get("terminated") is not True or counter.get("reported_rate") != 48000.0
    ):
        raise fft.ReferenceError("Live PortAudio rate/termination unverified")
    if type(metrics["stop_ms"]) not in (int, float) or not np.isfinite(metrics["stop_ms"]) or metrics["stop_ms"] < 0:
        raise fft.ReferenceError("Live filter stop time unknown")
    queue = metrics["queue"]
    if (
        not isinstance(queue, dict)
        or queue.get("capacity_frames") != 8192
        or queue.get("channels") != request["binding"]["device_channels"]
    ):
        raise fft.ReferenceError("Live filter queue binding mismatch")


def validate(directory, request, reference_case, tolerances):
    checked_request = validation_request(request, reference_case)
    arrays, hashes, header = filters.read_result(directory, checked_request, acquisition=True)
    count = len(request["binding"]["format"]["input_ids"])
    data = (directory / "input.f32.bin").read_bytes()
    if len(data) != request["frames"] * count * 4:
        raise fft.ReferenceError("Live filter raw byte count mismatch")
    raw = np.frombuffer(data, dtype="<f4").reshape(request["frames"], count)
    if arrays["live.raw_f32_as_f64"].tobytes() != raw.astype("<f8").tobytes():
        raise fft.ReferenceError("Live filter changed raw precision")
    expected = oracle.fir_sum(raw.astype("<f8"))
    comparisons = {"filter": fft.compare(arrays["live.output"], expected, tolerances["fir"], "live FIR finite sum")}
    start, end = next(w["interval"] for w in header["runs"]["live"]["windows"] if w["numeric"])
    actual = arrays["live.fft_over_n"]
    comparisons["fft"] = fft.compare(
        actual[..., 0] + 1j * actual[..., 1],
        np.fft.rfft(expected[start:end], axis=0) / 64,
        fft.TOLERANCES["f64"],
        "live shared FFT",
    )
    spectrum = np.abs(np.fft.rfft(raw.astype("<f8"), axis=0)) * 2 / len(raw)
    peaks = np.argmax(spectrum[1:], axis=0) + 1
    if peaks.tolist() != [b * FRAMES // 1024 for b in BINS[:count]]:
        raise fft.ReferenceError("Live filter selected wrong physical ports/tones")
    fft.compare(
        spectrum[peaks, np.arange(count)],
        np.arange(1, count + 1) / 512,
        {"atol": 2e-6, "rtol": 0.0},
        "live port amplitude",
    )
    metrics = json.loads((directory / "live.json").read_bytes())
    validate_metrics(metrics, request)
    return {
        "input_f32_sha256": fft.digest(data),
        "output_sha256": hashes,
        "comparisons": comparisons,
        "graph": header,
        "live": metrics,
    }


def run_case(binary, case, request, directory, reference_case, tolerances):
    import sounddevice as sd

    directory.mkdir()
    fft.write_json(directory / "request.json", request)
    matches = [
        i
        for i, d in enumerate(sd.query_devices())
        if d["name"] == case["device"] and d["max_input_channels"] == d["max_output_channels"] == case["channels"]
    ]
    if len(matches) != 1:
        raise fft.ReferenceError("Exact BlackHole device not unique")
    phase = np.arange(1024) * 2 * np.pi / 1024
    period = np.repeat((0.002 * np.cos(7 * phase))[:, None], case["channels"], axis=1).astype("<f4")
    for i, port in enumerate(case["ports"]):
        period[:, port] = (i + 1) / 512 * np.cos(BINS[i] * phase)
    position, statuses = 0, []

    def callback(outdata, frames, _times, status):
        nonlocal position
        if status:
            statuses.append(str(status))
        if frames != 256:
            raise sd.CallbackAbort
        outdata[:] = period[position % 1024 : position % 1024 + frames]
        position += frames

    command = [str(binary), str(directory / "request.json"), str(directory / "output")]
    settings = sd.CoreAudioSettings(change_device_parameters=True, fail_if_conversion_required=True)
    with sd.OutputStream(
        device=matches[0],
        samplerate=48000,
        blocksize=256,
        channels=case["channels"],
        dtype="float32",
        callback=callback,
        extra_settings=settings,
    ) as output:
        time.sleep(0.25)
        completed = subprocess.run(command, capture_output=True, timeout=15, check=False)  # noqa: S603 - local locked native runner
        (directory / "native.log").write_bytes(completed.stdout + completed.stderr)
        if not output.active or statuses:
            raise fft.ReferenceError(f"BlackHole stimulus failure: {statuses}")
    if completed.returncode != 0 or not output.closed:
        raise fft.ReferenceError(f"Live filter native failure: {completed.stderr.decode(errors='replace')}")
    return {
        "id": directory.name,
        "command": command,
        "output_closed": output.closed,
        **validate(directory / "output", request, reference_case, tolerances),
    }


def verify(output, library):
    manifest = filters.load_manifest()
    reference_case = next(c for c in manifest["cases"] if c["spec"]["id"] == "fir-tone")
    source, runners = source_hashes(), core.hashes(RUNNERS)
    library_hash = fft.digest(library.read_bytes())
    binary, build_record = build()
    binary_hash = fft.digest(binary.read_bytes())
    output.mkdir(parents=True)
    try:
        corpus = [
            run_case(
                binary,
                case,
                request_for(case, backend, library),
                output / f"{backend}-{case['id']}",
                reference_case,
                manifest["tolerances"],
            )
            for backend in ("Cpal", "PortAudio")
            for case in CASES
        ]
        if (
            source != source_hashes()
            or runners != core.hashes(RUNNERS)
            or binary_hash != fft.digest(binary.read_bytes())
            or library_hash != fft.digest(library.read_bytes())
        ):
            raise fft.ReferenceError("Source/binary/library changed during live filter comparison")
        snapshot = output / "source-snapshot"
        for name, expected in {**{f"native/{p}": h for p, h in source.items()}, **runners}.items():
            target = snapshot / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
            if fft.digest(target.read_bytes()) != expected:
                raise fft.ReferenceError("Live evidence source changed")
        (output / "binaries").mkdir()
        for src in (binary, library):
            shutil.copyfile(src, output / "binaries" / src.name)
        result = {
            "schema_version": 1,
            "task": "MIG-006-D-native-f32-filter",
            "status": "pass",
            "environment": fft.environment(),
            "source_sha256": source,
            "runner_sha256": runners,
            "binary_sha256": binary_hash,
            "library_sha256": library_hash,
            "build": build_record,
            "corpus": corpus,
            "limitations": [
                "Short BlackHole native callback diagnostic; Qt filter/Trigger/save integration pending",
                "Exact f32 widening, f64 causal 3-tap 48 -> 24 kHz only",
                "No physical clock/latency, long runs, performance or other OS acceptance",
            ],
        }
        fft.write_json(output / "report.json", result)
        fft.write_json(
            output / "evidence-audit.json",
            {
                "schema_version": 1,
                "artifacts_sha256": {
                    str(p.relative_to(output)): fft.digest(p.read_bytes())
                    for p in sorted(output.rglob("*"))
                    if p.is_file()
                },
            },
        )
        return result
    except (fft.ReferenceError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        fft.write_json(
            output / "failure.json",
            {"status": "fail", "error": str(error), "source_sha256": source, "binary_sha256": binary_hash},
        )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--virtual-device", action="store_true")
    parser.add_argument("--portaudio-library", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.virtual_device or sys.platform != "darwin":
        parser.error("Explicit --virtual-device on macOS is required")
    output, library = args.output.resolve(), args.portaudio_library
    if (
        output.exists()
        or output.is_relative_to((ROOT / "migration/fixtures").resolve())
        or not library.is_absolute()
        or not library.is_file()
    ):
        parser.error("Output must be new/outside fixtures; PortAudio library must be an existing absolute path")
    try:
        result = verify(output, library)
    except (fft.ReferenceError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"Live filter failed: {error}", file=sys.stderr)
        return 1
    print(f"Live filter OK: {len(result['corpus'])} BlackHole/native backend runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
