"""MIG-005-A-common input binding and worker transport, with optional BlackHole PortAudio.

Saved f32/f64 values go through the same native queue/history/FFT used by CPAL.
Real PortAudio uses a blocking read on this adapter worker, never callback pipe I/O.
This diagnostic does not implement the production backend, output taps or Qt selection.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import time
import tomllib

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import migration_audio_graph as acquisition  # noqa: E402
from scripts import migration_core_reference as core  # noqa: E402
from scripts import migration_fft_candidate as candidate  # noqa: E402
from scripts import migration_fft_oracle as oracle  # noqa: E402
from scripts import migration_fft_reference as fft  # noqa: E402
from scripts import migration_result_candidate as result  # noqa: E402

HEADER = struct.Struct("<IIQQd")
RATE = 48000
LIVE_FRAMES = 96 * 1024
LIVE_CASES = [
    {"id": "2-from-2", "device": "BlackHole 2ch", "channels": 2, "ports": [1, 0]},
    {"id": "4-from-16", "device": "BlackHole 16ch", "channels": 16, "ports": [15, 13, 11, 9]},
    {"id": "8-from-16", "device": "BlackHole 16ch", "channels": 16, "ports": [15, 13, 11, 9, 7, 5, 3, 1]},
]


def build():
    native = ROOT / "native"
    env = candidate.cargo_environment()
    version = tomllib.loads((native / "rust-toolchain.toml").read_text())["toolchain"]["channel"]
    record = candidate.run_command(
        [
            candidate.rust_tool("cargo", env),
            f"+{version}",
            "build",
            "--offline",
            "--locked",
            "--manifest-path",
            str(native / "Cargo.toml"),
            "--target-dir",
            str(native / "target"),
            "-p",
            "graph-core",
            "--bin",
            "backend-input-candidate",
        ],
        env=env,
    )
    return native / "target/debug" / (
        "backend-input-candidate.exe" if os.name == "nt" else "backend-input-candidate"
    ), record


def source_hashes():
    paths = [ROOT / "native" / name for name in ("Cargo.toml", "Cargo.lock", "rust-toolchain.toml")]
    for crate in ("audio-core", "dsp-core", "graph-core", "audio-probe"):
        directory = ROOT / "native" / crate
        paths += [directory / "Cargo.toml", *sorted((directory / "src").rglob("*.rs"))]
    paths += [
        ROOT / "scripts" / name
        for name in (
            "migration_backend_input.py",
            "migration_audio_graph.py",
            "migration_core_reference.py",
            "migration_core_cases.py",
            "migration_fft_candidate.py",
            "migration_fft_reference.py",
            "migration_fft_oracle.py",
            "migration_graph_candidate.py",
            "migration_result_candidate.py",
        )
    ]
    return {str(p.relative_to(ROOT)): fft.digest(p.read_bytes()) for p in paths}


def request_for(case, backend, *, reverse=False, window="Boxcar"):
    base = acquisition.request_for(case, reverse=reverse)
    count = len(base["format"]["input_ids"])
    device = "saved-fixture"
    base["format"]["clock_domain"] = f"{backend.lower()}.device:{device}"
    return {
        "schema_version": 1,
        "binding": {
            "backend": backend,
            "device": device,
            "device_channels": count,
            "sample_format": base["precision"],
            "format": base["format"],
        },
        "n": base["n"],
        "window": window,
        "queue_frames": 1024,
        "max_frames": base["n"],
    }


def packet(request, start, values=None, *, flags=0, seconds=None):
    count = request["binding"]["device_channels"]
    width = 4 if request["binding"]["sample_format"] == "F32" else 8
    raw = b"" if values is None else values
    if len(raw) % (count * width):
        raise ValueError("packet shape")
    frames = len(raw) // (count * width)
    if frames > 8192 or start + frames > request["max_frames"]:
        raise ValueError("packet capacity")
    return (
        HEADER.pack(
            frames,
            flags,
            start,
            request["binding"]["format"]["generation"],
            float("nan") if seconds is None else seconds,
        )
        + raw
    )


def wire_bytes(request, raw, pattern=(1, 127, 256, 17)):
    stride = request["binding"]["device_channels"] * (4 if request["binding"]["sample_format"] == "F32" else 8)
    if len(raw) % stride:
        raise ValueError("input shape")
    chunks = []
    start, index = 0, 0
    total = len(raw) // stride
    while start < total:
        frames = min(pattern[index % len(pattern)], total - start)
        chunks.append(packet(request, start, raw[start * stride : (start + frames) * stride]))
        start += frames
        index += 1
    chunks.append(packet(request, start))
    return b"".join(chunks)


def expected_source(request):
    return acquisition.expected_source(
        {"format": request["binding"]["format"], "precision": request["binding"]["sample_format"]}
    )


def validate(directory, request, raw, *, blocks=None):
    """Independent original-byte/NumPy oracle; exact metadata, sharing and cleanup."""
    try:
        header = json.loads((directory / "manifest.json").read_bytes())
        binding = request["binding"]
        source = expected_source(request)
        n, count = request["n"], len(source["channel_ids"])
        dtype = "<f4" if binding["sample_format"] == "F32" else "<f8"
        values = np.frombuffer(raw, dtype=dtype).reshape(-1, binding["device_channels"])
        selected = np.ascontiguousarray(values[:, binding["format"]["input_ports"]])
        frames = len(values)
        windows = frames // n
        exact = {
            "schema_version": 1,
            "binding": binding,
            "source": source,
            "frames": frames,
            "stamps": frames,
            "gaps": [],
            "state": "Stopped",
            "history_released": True,
            "queue_released": True,
            "input_finished": True,
            "raw_bytes": selected.nbytes,
            "complex_bytes": windows * (n // 2 + 1) * count * 16,
        }
        extras = {"blocks", "polls", "queue", "windows", "before_release", "after_stop", "held_after_stop"}
        if set(header) != set(exact) | extras or any(
            core.json_bytes(header[k]) != core.json_bytes(v) for k, v in exact.items()
        ):
            raise fft.ReferenceError("Backend binding, precision, positions, unknown clock or cleanup mismatch")
        if (
            type(header["blocks"]) is not int
            or not 0 < header["blocks"] <= frames
            or (blocks is not None and header["blocks"] != blocks)
            or type(header["polls"]) is not int
            or not header["blocks"] <= header["polls"] <= frames * 3 + 2
        ):
            raise fft.ReferenceError("Backend block/poll bounds mismatch")
        queue = header["queue"]
        if (
            set(queue) != {"capacity_frames", "channels", "max_depth_frames", "numeric_bytes"}
            or any(
                type(queue[k]) is not int or queue[k] != v
                for k, v in {
                    "capacity_frames": request["queue_frames"],
                    "channels": binding["device_channels"],
                    "numeric_bytes": request["queue_frames"] * binding["device_channels"] * 8,
                }.items()
            )
            or type(queue["max_depth_frames"]) is not int
            or not 0 < queue["max_depth_frames"] <= request["queue_frames"]
        ):
            raise fft.ReferenceError("Backend queue bounds mismatch")
        if (directory / "input.bin").read_bytes() != selected.tobytes():
            raise fft.ReferenceError("Backend changed original precision/binding bytes")
        before, after = header["before_release"], header["after_stop"]
        keys = {
            "nodes",
            "subscriptions",
            "in_flight",
            "cache_results",
            "cache_numeric_bytes",
            "fft_evaluations",
            "display_replacements",
        }
        if any(
            set(stats) != keys or any(type(v) is not int or v < 0 for v in stats.values()) for stats in (before, after)
        ):
            raise fft.ReferenceError("Backend graph stats schema mismatch")
        if (
            before["nodes"] != 1
            or before["subscriptions"] != 2
            or before["in_flight"] != 0
            or before["fft_evaluations"] != windows
            or not 0 < before["cache_results"] <= windows
            or before["cache_numeric_bytes"] <= 0
            or before["display_replacements"] != 0
            or any(after[k] != (windows if k == "fft_evaluations" else 0) for k in keys)
        ):
            raise fft.ReferenceError("Backend graph sharing/reclamation mismatch")
        encoded = (directory / "complex.bin").read_bytes()
        if len(encoded) != exact["complex_bytes"] or len(header["windows"]) != windows:
            raise fft.ReferenceError("Backend complex/window inventory mismatch")
        observed = np.frombuffer(encoded, dtype="<f8").reshape(windows, n // 2 + 1, count, 2)
        window = oracle.window_values(n, "boxcar" if request["window"] == "Boxcar" else "hann")
        comparisons, ids = [], set()
        for index, event in enumerate(header["windows"]):
            interval = [index * n, (index + 1) * n]
            history = {
                "stream_id": source["stream_id"],
                "generation": source["generation"],
                "timebase_id": source["timebase"]["id"],
                "interval": interval,
                "status": "snapshot",
                "missing": [],
                "pending": [],
                "reason": None,
            }
            expected = {
                "history": history,
                "numeric": True,
                "shared_allocation": True,
                "complex_offset": index * (n // 2 + 1) * count * 16,
                "complex_bytes": (n // 2 + 1) * count * 16,
            }
            if set(event) != set(expected) | {"result_id"} or any(
                core.json_bytes(event[k]) != core.json_bytes(v) for k, v in expected.items()
            ):
                raise fft.ReferenceError("Backend window interval, validity or allocation mismatch")
            identity = event["result_id"]
            if set(identity) != {"graph", "serial"} or any(type(v) is not int or v <= 0 for v in identity.values()):
                raise fft.ReferenceError("Backend result ID mismatch")
            pair = (identity["graph"], identity["serial"])
            if pair in ids or (ids and (pair[0] != next(iter(ids))[0] or pair[1] <= max(p[1] for p in ids))):
                raise fft.ReferenceError("Backend repeated, reversed or foreign-graph result ID")
            ids.add(pair)
            actual = observed[index, ..., 0] + 1j * observed[index, ..., 1]
            x = selected[slice(*interval)]
            # Match the frozen f32 arithmetic contract; NumPy FFT remains independent.
            expected_fft = np.fft.rfft((x * window.astype(dtype)[:, None]).astype(np.float64), axis=0) / n
            comparisons.append(
                fft.compare(
                    actual, expected_fft, fft.TOLERANCES["f32" if dtype == "<f4" else "f64"], "backend complex FFT"
                )
            )
        snapshot = result.read_result(directory)
        if core.json_bytes(snapshot) != core.json_bytes(header["held_after_stop"]):
            raise fft.ReferenceError("Backend held result changed after stop")
        if (
            snapshot["source"] != source
            or snapshot["interval"] != [(windows - 1) * n, windows * n]
            or snapshot["raw_result_id"] != list(pair)
            or snapshot["validity"]
            or snapshot["error"] is not None
            or snapshot["capture"]
            != {
                "result_id": "backend-input.last",
                "trigger_id": None,
                "acquired_host_seconds": None,
                "result_host_seconds": None,
                "trigger": None,
                "clock_mapping": None,
            }
            or snapshot["conditions"]
            != {
                "source": source,
                "n": n,
                "hop": n,
                "alignment": 0,
                "window": request["window"],
                "remove_dc": False,
                "input_gains": [],
            }
            or snapshot["operation_revision"] != acquisition.graph.TRANSFORM_REVISION
            or snapshot["calibration"]
            != [{"channel_id": ch, "profile": None, "application": "after_analysis"} for ch in source["channel_ids"]]
        ):
            raise fft.ReferenceError("Backend complete snapshot provenance mismatch")
        # Check every relative column against an independent oracle; absolute units stay unknown.
        x = selected[(windows - 1) * n : windows * n]
        z = observed[-1, ..., 0] + 1j * observed[-1, ..., 1]
        expected_arrays = {
            "window": window,
            "fft_over_n": observed[-1],
            "inverse_windowed": x * window.astype(dtype)[:, None],
            **oracle.quantities(z, window, x, RATE),
        }
        # The oracle's PSD uses the observed FFT; the complete FFT was independently checked above.
        expected_arrays.pop("frequency_hz", None)
        expected_arrays["tone_rms_fs"] = (
            expected_arrays["peak_fs"]
            / np.where(
                (np.arange(n // 2 + 1) == 0) | ((n % 2 == 0) & (np.arange(n // 2 + 1) == n // 2)), 1.0, np.sqrt(2.0)
            )[:, None]
        )
        expected_arrays["asd_fs_sqrt_hz"] = np.sqrt(expected_arrays["psd_fs2_hz"])
        units = {
            "window": "1",
            "fft_over_n": "FS",
            "inverse_windowed": "FS",
            "peak_fs": "FS_peak",
            "tone_rms_fs": "FS_RMS",
            "rms_fs": "FS_RMS",
            "psd_fs2_hz": "FS2/Hz",
            "asd_fs_sqrt_hz": "FS/sqrt(Hz)",
            "integrated_power_fs2": "FS2",
            "time_window_power_fs2": "FS2",
            "rms_v": "V_RMS",
            "dbv": "dBV_RMS",
            "spl": "dBSPL",
            "psd_v2_hz": "V2/Hz",
        }
        if set(snapshot["columns"]) != set(units):
            raise fft.ReferenceError("Backend result column inventory mismatch")
        for name, column in snapshot["columns"].items():
            shape = (
                list(expected_arrays[name].shape)
                if name in expected_arrays
                else ([n // 2 + 1, count] if name == "psd_v2_hz" else [count])
            )
            if (
                set(column) != {"shape", "precision", "unit", "values", "reasons"}
                or column["shape"] != shape
                or column["precision"] != (binding["sample_format"] if name == "inverse_windowed" else "F64")
                or column["unit"] != units[name]
                or len(column["values"]) != np.prod(shape)
                or len(column["reasons"]) != np.prod(shape)
            ):
                raise fft.ReferenceError("Backend result column metadata mismatch")
        for name, expected_array in expected_arrays.items():
            column = snapshot["columns"][name]
            actual = np.asarray(column["values"]).reshape(expected_array.shape)
            if column["shape"] != list(expected_array.shape) or any(r is not None for r in column["reasons"]):
                raise fft.ReferenceError("Backend result column shape/validity mismatch")
            fft.compare(actual, expected_array, fft.TOLERANCES["f32" if dtype == "<f4" else "f64"], f"backend {name}")
        for name in ("rms_v", "dbv", "spl", "psd_v2_hz"):
            column = snapshot["columns"][name]
            if any(v is not None for v in column["values"]) or any(r != "uncalibrated" for r in column["reasons"]):
                raise fft.ReferenceError("Backend unknown calibration became absolute values")
        nominal = np.arange(n // 2 + 1) * RATE / n
        if snapshot["axis"] != {
            "dimension": "frequency",
            "unit": "Hz",
            "nominal": nominal.tolist(),
            "corrected": nominal.tolist(),
            "correction": 1.0,
        }:
            raise fft.ReferenceError("Backend result axis mismatch")
        return {
            "frames": frames,
            "windows": windows,
            "max_complex_error": max(comparisons),
            "input_sha256": fft.digest(raw),
            "artifact_sha256": {p.name: fft.digest(p.read_bytes()) for p in sorted(directory.iterdir())},
        }
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as error:
        raise fft.ReferenceError(f"Backend malformed evidence: {error}") from error


def verify_saved(binary, manifest, directory):
    records = []
    directory.mkdir()
    for case in manifest["tones"]:
        core.load_tone(core.DEFAULT_FIXTURES, case)
        raw = core.checked_file(core.DEFAULT_FIXTURES / case["spec"]["id"], case["arrays"]["input"])
        for backend in ("Cpal", "PortAudio"):
            for reverse in (False, True):
                for window in ("Boxcar", "SymmetricHann"):
                    request = request_for(case, backend, reverse=reverse, window=window)
                    run_dir = (
                        directory / f"{case['spec']['id']}-{backend}-{'reverse' if reverse else 'identity'}-{window}"
                    )
                    run_dir.mkdir()
                    fft.write_json(run_dir / "request.json", request)
                    wire = wire_bytes(request, raw)
                    (run_dir / "wire.bin").write_bytes(wire)
                    command = candidate.run_command(
                        [str(binary), str(run_dir / "request.json"), str(run_dir / "wire.bin"), str(run_dir / "output")]
                    )
                    checked = validate(run_dir / "output", request, raw)
                    records.append(
                        {
                            "id": run_dir.name,
                            "command": command,
                            **checked,
                            "request_sha256": fft.digest((run_dir / "request.json").read_bytes()),
                            "wire_sha256": fft.digest(wire),
                        }
                    )
    return records


def live_request(case):
    return {
        "schema_version": 1,
        "binding": {
            "backend": "PortAudio",
            "device": case["device"],
            "device_channels": case["channels"],
            "sample_format": "F32",
            "format": {
                "stream_id": f"common.{case['id']}",
                "generation": 1,
                "timebase_id": f"common.{case['id']}.clock",
                "clock_domain": f"portaudio.device:{case['device']}",
                "rate": [RATE, 1],
                "input_ids": [f"input.logical.{i}" for i in range(len(case["ports"]))],
                "input_ports": case["ports"],
                "output_ids": [],
                "output_ports": [],
            },
        },
        "n": 1024,
        "window": "Boxcar",
        "queue_frames": 8192,
        "max_frames": LIVE_FRAMES,
    }


def verify_portaudio(binary, case, directory):
    import sounddevice as sd

    directory.mkdir()
    request = live_request(case)
    fft.write_json(directory / "request.json", request)
    matches = [
        i
        for i, d in enumerate(sd.query_devices())
        if d["name"] == case["device"]
        and d["max_input_channels"] == case["channels"]
        and d["max_output_channels"] == case["channels"]
    ]
    if len(matches) != 1:
        raise fft.ReferenceError("Exact BlackHole device not unique")
    channels, n = case["channels"], request["n"]
    phase = np.arange(n) * 2 * np.pi / n
    period = np.repeat((0.002 * np.cos(17 * phase))[:, None], channels, axis=1).astype("<f4")
    for i, port in enumerate(case["ports"]):
        period[:, port] = (i + 1) / 512 * np.cos([37, 71, 113, 173, 251, 331, 419, 509][i] * phase)
    position = 0
    output_status = []

    def output_callback(outdata, frames, _times, status):
        nonlocal position
        if status:
            output_status.append(str(status))
        end = position + frames
        # All output buffers in this fixed diagnostic are 256 frames.
        if frames != 256:
            raise sd.CallbackAbort
        outdata[:] = period[position % n : position % n + frames]
        position = end

    settings = (
        sd.CoreAudioSettings(change_device_parameters=True, fail_if_conversion_required=True)
        if sys.platform == "darwin"
        else None
    )
    command = [str(binary), str(directory / "request.json"), "-", str(directory / "output")]
    started = time.perf_counter()
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)  # noqa: S603 - explicit local executable
    chunks, packets = [], []
    input_closed = output_closed = False
    try:
        with sd.OutputStream(
            device=matches[0],
            samplerate=RATE,
            blocksize=256,
            channels=channels,
            dtype="float32",
            callback=output_callback,
            extra_settings=settings,
        ) as output:
            time.sleep(0.25)
            with sd.InputStream(
                device=matches[0],
                samplerate=RATE,
                blocksize=256,
                channels=channels,
                dtype="float32",
                extra_settings=settings,
            ) as input_stream:
                if (
                    input_stream.dtype != "float32"
                    or input_stream.samplerate != RATE
                    or input_stream.channels != channels
                ):
                    raise fft.ReferenceError("PortAudio actual format differs from frozen binding")
                for start in range(0, LIVE_FRAMES, 256):
                    data, overflow = input_stream.read(256)
                    if overflow or not input_stream.active or process.poll() is not None:
                        raise fft.ReferenceError("PortAudio overflow, early stop or native input failure")
                    raw = data.astype("<f4", copy=False).tobytes()
                    chunk = packet(request, start, raw)
                    process.stdin.write(chunk)
                    process.stdin.flush()
                    chunks.append(raw)
                    packets.append(chunk)
            input_closed = input_stream.closed
            if not output.active or output_status:
                raise fft.ReferenceError(f"PortAudio output stopped or reported status: {output_status}")
        output_closed = output.closed
        terminal = packet(request, LIVE_FRAMES)
        process.stdin.write(terminal)
        process.stdin.close()
        process.stdin = None
        stdout, stderr = process.communicate(timeout=30)
        (directory / "native.log").write_bytes(stdout + stderr)
        if process.returncode != 0 or not input_closed or not output_closed:
            raise fft.ReferenceError(f"PortAudio native failure/stream leak: {stderr.decode(errors='replace')}")
        raw = b"".join(chunks)
        (directory / "physical-input.f32").write_bytes(raw)
        (directory / "wire.bin").write_bytes(b"".join(packets) + terminal)
        checked = validate(directory / "output", request, raw, blocks=LIVE_FRAMES // 256)
        # Actual acquired signal must contain the chosen physical ports' distinct tones.
        snapshot = result.read_result(directory / "output")
        peaks = np.asarray(snapshot["columns"]["peak_fs"]["values"]).reshape(n // 2 + 1, len(case["ports"]))
        if np.argmax(peaks, axis=0).tolist() != [37, 71, 113, 173, 251, 331, 419, 509][: len(case["ports"])]:
            raise fft.ReferenceError("PortAudio physical tone/port mapping mismatch")
        return {
            "id": case["id"],
            "command": command,
            "elapsed_seconds": time.perf_counter() - started,
            "frames": LIVE_FRAMES,
            "input_closed": input_closed,
            "output_closed": output_closed,
            "input_overflows": 0,
            "output_status": output_status,
            "native_exit_code": process.returncode,
            "transport": "blocking PortAudio adapter worker -> pipe -> common native input queue",
            "stream_format": {
                "dtype": input_stream.dtype,
                "samplerate": input_stream.samplerate,
                "channels": input_stream.channels,
            },
            **checked,
            "wire_sha256": fft.digest((directory / "wire.bin").read_bytes()),
        }
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        # Preserve any partial original capture on failure; never label it passed.
        if chunks and not (directory / "physical-input.f32").exists():
            (directory / "physical-input.f32").write_bytes(b"".join(chunks))


def verify(output, *, portable=False, virtual_device=False):
    if output.exists() or any(
        output.resolve().is_relative_to(p.resolve()) for p in (core.DEFAULT_FIXTURES, fft.DEFAULT_FIXTURES)
    ):
        raise ValueError("Output must be new and outside immutable fixtures")
    output.mkdir(parents=True)
    started = time.perf_counter()
    sources = source_hashes()
    binary, built = build()
    binary_hash = fft.digest(binary.read_bytes())
    report = {
        "schema_version": 1,
        "task": "MIG-005-A-common-input",
        "status": "fail",
        "mode": "portable" if portable else "pinned-reference",
        "source_sha256": sources,
        "binary_sha256": binary_hash,
        "build": built,
        "saved": [],
        "portaudio": [],
        "limitations": [
            "InputRaw only; production PortAudio callback/Qt selection and all output taps remain separate",
            "Real adapters are F32. Saved F64 is not a claim of device F64 support; no implicit conversion",
            "PortAudio pipe belongs to an adapter worker, not the audio callback; no production/latency or performance claim",
            "Backend loss/discontinuity fails explicitly; clock origin/uncertainty remain unknown",
            "No long-duration/CPU/RSS, USB recovery, physical voltage/delay, other OS or adoption decision",
        ],
    }
    try:
        manifest, manifest_hash = candidate.load_manifest(core.DEFAULT_FIXTURES, portable=portable, is_core=True)
        report["fixture_manifest_sha256"] = manifest_hash
        report["saved"] = verify_saved(binary, manifest, output / "saved")
        fft.assert_headless()
        if virtual_device:
            live = output / "portaudio"
            live.mkdir()
            for case in LIVE_CASES:
                report["portaudio"].append(verify_portaudio(binary, case, live / case["id"]))
        if source_hashes() != sources or fft.digest(binary.read_bytes()) != binary_hash:
            raise fft.ReferenceError("Backend source/binary changed during verification")
        candidate.load_manifest(core.DEFAULT_FIXTURES, portable=portable, is_core=True)
        report["status"] = "pass"
        return report
    except Exception as error:
        report["error"] = str(error)
        raise
    finally:
        report["elapsed_seconds"] = time.perf_counter() - started
        fft.write_json(output / "report.json", report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--portable", action="store_true")
    parser.add_argument(
        "--virtual-device",
        action="store_true",
        help="Open exact BlackHole inputs/outputs for short PortAudio verification",
    )
    args = parser.parse_args()
    try:
        report = verify(args.output.resolve(), portable=args.portable, virtual_device=args.virtual_device)
    except Exception as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS: {len(report['saved'])} saved / {len(report['portaudio'])} PortAudio runs; {args.output}/report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
