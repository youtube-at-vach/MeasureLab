"""Saved original input -> acquisition -> non-consuming trigger capture evidence.

Expectations stay in this NumPy-only runner. The native process receives configuration
and original fixture bytes; it never receives expected arrays or regenerated fixtures.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import time
import tomllib

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import migration_audio_graph as audio  # noqa: E402
from scripts import migration_fft_candidate as candidate  # noqa: E402
from scripts import migration_fft_oracle as oracle  # noqa: E402
from scripts import migration_fft_reference as fft  # noqa: E402
from scripts import migration_graph_candidate as graph  # noqa: E402

core = audio.core
NAMES = ("aligned", "delayed", "shifted", "repeated")


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
            "trigger-candidate",
        ],
        env=env,
    )
    return native / "target/debug" / ("trigger-candidate.exe" if os.name == "nt" else "trigger-candidate"), record


def exact(actual, expected, context):
    if core.json_bytes(actual) != core.json_bytes(expected):
        raise fft.ReferenceError(f"Trigger {context} mismatch")


def event_for(request, name):
    fmt, n = request["format"], request["n"]
    shifted = name in ("shifted", "repeated", "expired_shifted")
    return {
        "id": "virtual.repeated" if name == "repeated" else "virtual.shifted" if shifted else "virtual.aligned",
        "stream_id": fmt["stream_id"],
        "generation": fmt["generation"],
        "timebase_id": fmt["timebase_id"],
        "sample": {"numerator": 2 * (n // 2 + int(shifted)) + 1, "denominator": 2},
        "source": "fixture.virtual",
        "kind": "edge",
        "polarity": "rising",
        "condition_revision": "fixture.trigger.v1",
        "validity": [],
        "received_host_seconds": None
        if name == "repeated"
        else {"numerator": 111111 if name == "delayed" else 99999, "denominator": 1},
    }


def valid_id(value):
    return (
        isinstance(value, dict)
        and set(value) == {"graph", "serial"}
        and all(type(v) is int and v > 0 for v in value.values())
    )


def valid_result_id(value, raw_id, request_id):
    prefix = f"trigger:{raw_id['graph']}:{raw_id['serial']}:{request_id}:"
    if not isinstance(value, str) or not value.startswith(prefix):
        return False
    serial = value[len(prefix) :]
    return (
        serial.isascii()
        and serial.isdecimal()
        and 0 < len(serial) <= 20
        and int(serial) > 0
        and str(int(serial)) == serial
    )


def validate_manifest(header, request):
    n, fmt = request["n"], request["format"]
    source = audio.expected_source(request)
    expected = {
        "schema_version": 1,
        "format": fmt,
        "source": source,
        "shared_continuous": True,
        "shared_trigger": True,
        "latest_interval": [n, 2 * n],
        "latest_map_interval": [n, 2 * n],
        "latest_average_count": 2,
        "trigger_evaluations": 1,
        "stale_error": "stale_generation",
        "stopped_error": "capture_not_running",
        "history_released": True,
    }
    extras = {"reads", "continuous_before", "continuous_after", "after_stop"}
    if not isinstance(header, dict) or set(header) != set(expected) | extras:
        raise fft.ReferenceError("Trigger manifest inventory mismatch")
    for key, value in expected.items():
        exact(header[key], value, key)
    before = header["continuous_before"]
    if (
        not isinstance(before, dict)
        or type(before.get("cache_numeric_bytes")) is not int
        or not 0 < before["cache_numeric_bytes"] <= 64 * 1024**2
    ):
        raise fft.ReferenceError("Trigger cache bound mismatch")
    stats = {
        "nodes": 1,
        "subscriptions": 2,
        "cache_results": 2,
        "cache_numeric_bytes": before["cache_numeric_bytes"],
        "in_flight": 0,
        "fft_evaluations": 2,
        "display_replacements": 0,
    }
    exact(before, stats, "continuous stats")
    exact(header["continuous_after"], stats, "non-consuming read")
    exact(
        header["after_stop"],
        {**stats, "nodes": 0, "subscriptions": 0, "cache_results": 0, "cache_numeric_bytes": 0, "fft_evaluations": 3},
        "resource recovery",
    )
    reads = header["reads"]
    if not isinstance(reads, dict) or set(reads) != {*NAMES, "pending", "expired", "expired_shifted"}:
        raise fft.ReferenceError("Trigger read inventory mismatch")
    for name, read in reads.items():
        start = int(name in ("shifted", "repeated", "expired_shifted"))
        status = "pending" if name == "pending" else "gap" if name.startswith("expired") else "snapshot"
        observed_id = read.get("raw_result_id") if isinstance(read, dict) else None
        if status == "snapshot" and not valid_id(observed_id):
            raise fft.ReferenceError("Trigger raw identity mismatch")
        request_id = "aligned" if name in ("pending", "expired") else "shifted" if name == "expired_shifted" else name
        result_id = read.get("result_id") if isinstance(read, dict) else None
        if status == "snapshot" and not valid_result_id(result_id, observed_id, request_id):
            raise fft.ReferenceError("Trigger immutable result identity mismatch")
        expected_read = {
            "request_id": request_id,
            "event": event_for(request, name),
            "residual": {"numerator": 1, "denominator": 2},
            "history": {
                "stream_id": fmt["stream_id"],
                "generation": fmt["generation"],
                "timebase_id": fmt["timebase_id"],
                "interval": [start, start + n],
                "status": status,
                "missing": [[start, n]] if status == "gap" else [],
                "pending": [[0, n]] if status == "pending" else [],
                "reason": "missing" if status == "gap" else None,
            },
            "has_result": status == "snapshot",
            "result_id": result_id if status == "snapshot" else None,
            "has_snapshot": status == "snapshot",
            "raw_result_id": observed_id if status == "snapshot" else None,
            "fft_origin": "computed"
            if name == "shifted"
            else "trigger-cache"
            if name == "repeated"
            else "continuous-cache"
            if status == "snapshot"
            else "none",
        }
        exact(read, expected_read, name)
    exact(reads["aligned"]["raw_result_id"], reads["delayed"]["raw_result_id"], "delayed raw sharing")
    exact(reads["shifted"]["raw_result_id"], reads["repeated"]["raw_result_id"], "trigger raw sharing")
    if reads["aligned"]["raw_result_id"] == reads["shifted"]["raw_result_id"]:
        raise fft.ReferenceError("Distinct trigger windows shared a raw identity")
    return reads


def validate_document(document, read, request, case, samples, *, alignment=None):
    n, channels = request["n"], len(request["format"]["input_ids"])
    start = read["history"]["interval"][0]
    raw_id = read["raw_result_id"]
    result_id = read["result_id"]
    source = audio.expected_source(request)
    expected = {
        "schema_version": 1,
        "source": source,
        "operation_revision": graph.TRANSFORM_REVISION,
        "interval": [start, start + n],
        "raw_result_id": [raw_id["graph"], raw_id["serial"]],
        "validity": [],
        "error": None,
        "capture": {
            "result_id": result_id,
            "trigger_id": read["event"]["id"] if read["event"] else None,
            "trigger": read["event"],
            "acquired_host_seconds": None,
            "result_host_seconds": None,
            "clock_mapping": None,
        },
        "conditions": {
            "source": source,
            "n": n,
            "hop": n,
            "alignment": start if alignment is None else alignment,
            "window": request["window"],
            "remove_dc": False,
            "input_gains": [],
        },
        "calibration": [
            {"channel_id": c, "profile": None, "application": "after_analysis"} for c in source["channel_ids"]
        ],
    }
    if not isinstance(document, dict) or set(document) != set(expected) | {"axis", "columns"}:
        raise fft.ReferenceError("Trigger result inventory mismatch")
    for key, value in expected.items():
        exact(document[key], value, f"result {key}")
    frequencies = (np.arange(n // 2 + 1) * (case["spec"]["rate_hz"] / n)).tolist()
    exact(
        document["axis"],
        {"dimension": "frequency", "unit": "Hz", "nominal": frequencies, "corrected": frequencies, "correction": 1.0},
        "axis",
    )
    window = oracle.window_values(n, case["spec"]["window"])
    transformed = np.fft.rfft(samples.astype(float) * window[:, None], axis=0) / n
    expected_arrays = oracle.quantities(transformed, window, samples, case["spec"]["rate_hz"])
    expected_arrays.pop("frequency_hz")
    expected_arrays.update(
        window=window,
        inverse_windowed=samples * window[:, None],
        fft_over_n=np.stack((transformed.real, transformed.imag), axis=-1),
        tone_rms_fs=expected_arrays["peak_fs"] / np.sqrt(2),
        asd_fs_sqrt_hz=np.sqrt(expected_arrays["psd_fs2_hz"]),
    )
    units = {
        "window": "1",
        "inverse_windowed": "FS",
        "fft_over_n": "FS",
        "peak_fs": "FS_peak",
        "tone_rms_fs": "FS_RMS",
        "rms_fs": "FS_RMS",
        "psd_fs2_hz": "FS2/Hz",
        "asd_fs_sqrt_hz": "FS/sqrt(Hz)",
        "integrated_power_fs2": "FS2",
        "time_window_power_fs2": "FS2",
    }
    absolute = {
        "rms_v": ([channels], "V_RMS"),
        "dbv": ([channels], "dBV_RMS"),
        "spl": ([channels], "dBSPL"),
        "psd_v2_hz": ([n // 2 + 1, channels], "V2/Hz"),
    }
    columns = document["columns"]
    if not isinstance(columns, dict) or set(columns) != set(expected_arrays) | set(absolute):
        raise fft.ReferenceError("Trigger column inventory mismatch")
    comparisons = {}
    tolerance = fft.TOLERANCES["f32" if request["precision"] == "F32" else "f64"]
    for name, array in expected_arrays.items():
        column = columns[name]
        metadata = {
            "unit": units[name],
            "precision": request["precision"] if name == "inverse_windowed" else "F64",
            "shape": list(array.shape),
            "reasons": [None] * array.size,
        }
        if not isinstance(column, dict) or set(column) != set(metadata) | {"values"}:
            raise fft.ReferenceError("Trigger column fields mismatch")
        exact({k: column[k] for k in metadata}, metadata, f"column {name}")
        values = column["values"]
        if (
            not isinstance(values, list)
            or len(values) != array.size
            or any(type(v) not in (int, float) or not np.isfinite(v) for v in values)
        ):
            raise fft.ReferenceError("Trigger invalid numeric payload")
        comparisons[name] = fft.compare(np.asarray(values).reshape(array.shape), array, tolerance, f"trigger {name}")
    for name, (shape, unit) in absolute.items():
        count = int(np.prod(shape))
        exact(
            columns[name],
            {
                "unit": unit,
                "precision": "F64",
                "shape": shape,
                "values": [None] * count,
                "reasons": ["uncalibrated"] * count,
            },
            f"uncalibrated {name}",
        )
    # The unshifted FFT also retains both original fixture comparisons.
    if start == 0 and "arrays" in case:
        directory = core.DEFAULT_FIXTURES / case["spec"]["id"]
        observed = np.asarray(columns["fft_over_n"]["values"]).reshape(n // 2 + 1, channels, 2)
        observed = observed[..., 0] + 1j * observed[..., 1]
        ports = request["format"]["input_ports"]
        for origin in ("theory", "current"):
            comparisons[origin] = fft.compare(
                observed,
                fft.read_array(directory, case["arrays"][f"{origin}.fft_over_n"])[:, ports],
                tolerance,
                f"trigger {origin} fixture",
            )
    return comparisons


def read_result(directory, case, *, reverse=False):
    try:
        request = audio.request_for(case, reverse=reverse)
        header = core.read_json((directory / "manifest.json").read_bytes())
        reads = validate_manifest(header, request)
        source = core.DEFAULT_FIXTURES / case["spec"]["id"]
        raw = core.checked_file(source, case["arrays"]["input"])
        samples = np.frombuffer(raw, dtype=case["spec"]["dtype"]).reshape(request["n"], -1)[
            :, request["format"]["input_ports"]
        ]
        comparisons = {}
        for name in NAMES:
            observed_bytes = (directory / f"{name}.bin").read_bytes()
            expected_samples = np.roll(samples, -1, axis=0) if name in ("shifted", "repeated") else samples
            if observed_bytes != expected_samples.tobytes():
                raise fft.ReferenceError("Trigger retained sample bits or position mismatch")
            comparisons[name] = validate_document(
                core.read_json((directory / f"{name}.json").read_bytes()), reads[name], request, case, expected_samples
            )
        return {
            "manifest": header,
            "comparisons": comparisons,
            "files_sha256": {p.name: fft.digest(p.read_bytes()) for p in sorted(directory.iterdir()) if p.is_file()},
        }
    except (KeyError, TypeError, ValueError, IndexError) as error:
        raise fft.ReferenceError(f"Malformed trigger evidence: {error}") from error


def verify(output, *, portable=False):
    started = time.perf_counter()
    manifest, manifest_hash = candidate.load_manifest(core.DEFAULT_FIXTURES, portable=portable, is_core=True)
    binary, build_record = build()
    output.mkdir(parents=True, exist_ok=False)
    records = []
    for case in manifest["tones"]:
        core.load_tone(core.DEFAULT_FIXTURES, case)
        source = core.DEFAULT_FIXTURES / case["spec"]["id"] / case["arrays"]["input"]["file"]
        for reverse in (False, True):
            name = case["spec"]["id"] + ("-reversed" if reverse else "-identity")
            directory = output / name
            directory.mkdir()
            request_path = directory / "request.json"
            fft.write_json(request_path, audio.request_for(case, reverse=reverse))
            record = candidate.run_command([str(binary), str(request_path), str(source), str(directory / "evidence")])
            records.append(
                {
                    "id": name,
                    "command": record,
                    "request_sha256": fft.digest(request_path.read_bytes()),
                    "input_sha256": case["arrays"]["input"]["sha256"],
                    **read_result(directory / "evidence", case, reverse=reverse),
                }
            )
    fft.assert_headless()
    native = ROOT / "native"
    paths = [native / name for name in ("Cargo.toml", "Cargo.lock", "rust-toolchain.toml")]
    for crate in ("audio-core", "dsp-core", "graph-core"):
        paths += [native / crate / "Cargo.toml", *sorted((native / crate).rglob("*.rs"))]
    result = {
        "schema_version": 1,
        "task": "MIG-007-trigger-worker",
        "status": "pass",
        "mode": "portable" if portable else "pinned-reference",
        "environment": fft.environment(),
        "fixture_manifest_sha256": manifest_hash,
        "build": build_record,
        "binary_sha256": fft.digest(binary.read_bytes()),
        "source_sha256": {str(p.relative_to(native)): fft.digest(p.read_bytes()) for p in paths},
        "runner_sha256": {
            str(p.relative_to(ROOT)): fft.digest(p.read_bytes())
            for p in [
                Path(__file__),
                ROOT / "scripts/migration_audio_graph.py",
                ROOT / "scripts/migration_fft_oracle.py",
                ROOT / "scripts/migration_fft_candidate.py",
                ROOT / "scripts/migration_fft_reference.py",
                ROOT / "scripts/migration_core_reference.py",
                ROOT / "scripts/migration_graph_candidate.py",
            ]
        },
        "corpus": records,
        "elapsed_seconds": time.perf_counter() - started,
        "limitations": [
            "Analysis owner API only; Qt trigger controls and live scheduling remain pending",
            "Virtual event with explicit sample, no detector or inferred physical clock mapping",
            "One extra raw FFT slot; external snapshots and process RSS have separate lifetimes",
            "No realtime, long-duration, other-OS or adoption acceptance",
        ],
    }
    fft.write_json(output / "report.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--portable", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or any(
        output.is_relative_to(p.resolve()) for p in (core.DEFAULT_FIXTURES, fft.DEFAULT_FIXTURES)
    ):
        parser.error("Output must be new and outside fixtures")
    try:
        result = verify(output, portable=args.portable)
        print(f"Trigger capture OK: {len(result['corpus'])} original-byte/binding cases, 32 immutable results")
        return 0
    except (fft.ReferenceError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"Trigger capture failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
