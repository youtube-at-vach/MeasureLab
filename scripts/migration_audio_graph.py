"""MIG-005: original acquisition bytes through bounded queue, history and shared FFT.

Candidate requests contain configuration and original input only. No devices/Qt
or fixture regeneration; exact bindings and unknown clock origin are preserved.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import tomllib

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import migration_core_reference as core  # noqa: E402
from scripts import migration_fft_candidate as candidate  # noqa: E402
from scripts import migration_fft_reference as fft  # noqa: E402
from scripts import migration_graph_candidate as graph  # noqa: E402


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
            "acquisition-candidate",
        ],
        env=env,
    )
    return native / "target/debug" / (
        "acquisition-candidate.exe" if os.name == "nt" else "acquisition-candidate"
    ), record


def request_for(case, *, reverse=False):
    key = graph.request_for(case)["key"]
    source = key["source"]
    count = len(source["channel_ids"])
    ports = list(range(count))[::-1] if reverse else list(range(count))
    return {
        "schema_version": 1,
        "format": {
            "stream_id": source["stream_id"],
            "generation": source["generation"],
            "timebase_id": source["timebase"]["id"],
            "clock_domain": source["timebase"]["clock_domain"],
            "rate": [source["timebase"]["rate"]["numerator"], source["timebase"]["rate"]["denominator"]],
            "input_ids": [source["channel_ids"][p] for p in ports],
            "input_ports": ports,
            "output_ids": [],
            "output_ports": [],
        },
        "precision": source["precision"],
        "n": key["n"],
        "window": key["window"],
    }


def expected_source(request):
    fmt = request["format"]
    rate = {"numerator": fmt["rate"][0], "denominator": fmt["rate"][1]}
    return {
        "stream_id": fmt["stream_id"],
        "generation": fmt["generation"],
        "channel_ids": fmt["input_ids"],
        "precision": request["precision"],
        "timebase": {
            "id": fmt["timebase_id"],
            "revision": 0,
            "clock_domain": fmt["clock_domain"],
            "generation": fmt["generation"],
            "rate": rate,
            "nominal_rate": rate,
            "origin_sample": 0,
            "origin_seconds": None,
            "origin_kind": "backend-unverified",
            "uncertainty_seconds": None,
        },
        "route_revision": "input-physical-binding",
        "tap": "InputRaw",
        "filter_state_revision": "none",
        "calibration_revision": "none",
    }


def read_result(directory, case, *, reverse=False):
    request = request_for(case, reverse=reverse)
    header = json.loads((directory / "manifest.json").read_bytes())
    n, fmt = request["n"], request["format"]
    count = len(fmt["input_ids"])
    expected = {
        "schema_version": 1,
        "format": fmt,
        "source": expected_source(request),
        "interval": [0, n],
        "shared_allocation": True,
        "session_interval": [n, 2 * n],
        "expired": {
            "stream_id": fmt["stream_id"],
            "generation": fmt["generation"],
            "timebase_id": fmt["timebase_id"],
            "interval": [0, n],
            "status": "gap",
            "missing": [[0, n]],
            "pending": [],
            "reason": "missing",
        },
        "state": "Stopped",
        "history_released": True,
    }
    extras = {
        "result_id",
        "second_result_id",
        "save_result_id",
        "before_release",
        "save_only",
        "after_release",
        "after_stop",
        "queue",
    }
    if not isinstance(header, dict) or set(header) != set(expected) | extras:
        raise fft.ReferenceError("Acquisition manifest fields mismatch")
    if any(core.json_bytes(header[k]) != core.json_bytes(v) for k, v in expected.items()):
        raise fft.ReferenceError("Acquisition source, binding, unknown clock or lifecycle mismatch")
    result_id = header["result_id"]
    if (
        not isinstance(result_id, dict)
        or set(result_id) != {"graph", "serial"}
        or any(type(v) is not int or v <= 0 for v in result_id.values())
        or any(core.json_bytes(header[k]) != core.json_bytes(result_id) for k in ("second_result_id", "save_result_id"))
    ):
        raise fft.ReferenceError("Acquisition result identity mismatch")
    if not isinstance(header["before_release"], dict):
        raise fft.ReferenceError("Acquisition graph stats missing")
    numeric_bytes = header["before_release"].get("cache_numeric_bytes")
    before = {
        "nodes": 1,
        "subscriptions": 3,
        "in_flight": 0,
        "cache_results": 1,
        "cache_numeric_bytes": numeric_bytes,
        "fft_evaluations": 1,
        "display_replacements": 0,
    }
    save_only = {
        **before,
        "subscriptions": 1,
        "cache_results": 2,
        "cache_numeric_bytes": 2 * numeric_bytes if type(numeric_bytes) is int else None,
        "fft_evaluations": 2,
    }
    released = {
        **before,
        "nodes": 0,
        "subscriptions": 0,
        "cache_results": 0,
        "cache_numeric_bytes": 0,
        "fft_evaluations": 2,
    }
    if (
        type(numeric_bytes) is not int
        or not 0 < numeric_bytes <= 32 * 1024**2
        or any(
            core.json_bytes(header[k]) != core.json_bytes(v)
            for k, v in {
                "before_release": before,
                "save_only": save_only,
                "after_release": released,
                "after_stop": released,
            }.items()
        )
    ):
        raise fft.ReferenceError("Acquisition sharing, demand or resource recovery mismatch")
    queue = header["queue"]
    if (
        not isinstance(queue, dict)
        or set(queue) != {"capacity_frames", "channels", "max_depth_frames", "numeric_bytes"}
        or type(queue["max_depth_frames"]) is not int
        or not 0 < queue["max_depth_frames"] <= 256
        or any(
            type(queue[k]) is not int or queue[k] != v
            for k, v in {"capacity_frames": 1024, "channels": count, "numeric_bytes": 1024 * count * 8}.items()
        )
    ):
        raise fft.ReferenceError("Acquisition queue bounds mismatch")
    source = core.DEFAULT_FIXTURES / case["spec"]["id"]
    raw = core.checked_file(source, case["arrays"]["input"])
    dtype = case["spec"]["dtype"]
    expected_bytes = np.frombuffer(raw, dtype=dtype).reshape(n, count)[:, fmt["input_ports"]].tobytes()
    hashes = {}
    for name in ("poll_raw", "snapshot", "held_after_stop"):
        observed = (directory / f"{name}.bin").read_bytes()
        if observed != expected_bytes:
            raise fft.ReferenceError(f"Acquisition original bits or binding changed: {name}")
        hashes[name] = fft.digest(observed)
    complex_bytes = (directory / "fft_over_n.bin").read_bytes()
    if len(complex_bytes) != (n // 2 + 1) * count * 16:
        raise fft.ReferenceError("Acquisition FFT shape mismatch")
    array = np.frombuffer(complex_bytes, dtype="<f8").reshape(n // 2 + 1, count, 2)
    if not np.all(np.isfinite(array)):
        raise fft.ReferenceError("Acquisition FFT nonfinite")
    hashes["fft_over_n"] = fft.digest(complex_bytes)
    return array[..., 0] + 1j * array[..., 1], hashes, header


def validate_device_graph(raw):
    """Validate the short CPAL diagnostic's real acquisition path, including cancel."""
    try:
        fmt = raw["format"]
        observed = raw["analysis_graph"]
        request = {"format": fmt, "precision": "F32"}
        samples = raw["input"]["samples"]
        end = samples[-1] + 1 if samples else 0
        windows = max(0, (end - 1024) // 512 + 1)
        shared = observed["shared_notifications"]
        before = observed["before_stop"]
        after = observed["after_stop"]
        if (
            not isinstance(observed, dict)
            or set(observed)
            != {
                "source",
                "windows",
                "numeric_windows",
                "gap_windows",
                "shared_notifications",
                "before_stop",
                "after_stop",
                "retained_history_frames",
            }
            or core.json_bytes(observed["source"]) != core.json_bytes(expected_source(request))
            or raw["input"]["gaps"]
            or any(
                type(observed[k]) is not int or observed[k] != v
                for k, v in {
                    "windows": windows,
                    "numeric_windows": windows,
                    "gap_windows": 0,
                    "retained_history_frames": min(8192, end),
                }.items()
            )
            or type(shared) is not int
            or not (1 <= shared <= windows if windows else shared == 0)
            or not isinstance(before, dict)
            or set(before)
            != {
                "nodes",
                "subscriptions",
                "in_flight",
                "cache_results",
                "cache_numeric_bytes",
                "fft_evaluations",
                "display_replacements",
            }
            or any(
                type(before[k]) is not int or before[k] != v
                for k, v in {
                    "nodes": 1,
                    "subscriptions": 2,
                    "in_flight": 0,
                    "cache_results": min(8, windows),
                    "fft_evaluations": windows,
                    "display_replacements": 2 * (windows - shared),
                }.items()
            )
            or type(before["cache_numeric_bytes"]) is not int
            or not (
                0 < before["cache_numeric_bytes"] <= 64 * 1024**2 if windows else before["cache_numeric_bytes"] == 0
            )
            or core.json_bytes(after)
            != core.json_bytes({**before, "nodes": 0, "subscriptions": 0, "cache_results": 0, "cache_numeric_bytes": 0})
        ):
            raise fft.ReferenceError("CPAL acquisition graph source, windows, sharing or shutdown mismatch")
        return observed
    except (KeyError, TypeError, IndexError) as error:
        raise fft.ReferenceError("CPAL acquisition graph report missing or malformed") from error


def verify_case(binary, case, *, reverse=False):
    core.load_tone(core.DEFAULT_FIXTURES, case)
    source = core.DEFAULT_FIXTURES / case["spec"]["id"]
    core.checked_file(source, case["arrays"]["input"])
    input_path = source / case["arrays"]["input"]["file"]
    with tempfile.TemporaryDirectory(prefix="migration-acquisition-") as temp:
        temp = Path(temp)
        request = temp / "request.json"
        fft.write_json(request, request_for(case, reverse=reverse))
        record = candidate.run_command([str(binary), str(request), str(input_path), str(temp / "output")])
        observed, hashes, header = read_result(temp / "output", case, reverse=reverse)
        precision = "f32" if case["spec"]["dtype"] == "<f4" else "f64"
        ports = request_for(case, reverse=reverse)["format"]["input_ports"]
        comparisons = {
            origin: fft.compare(
                observed,
                fft.read_array(source, case["arrays"][f"{origin}.fft_over_n"])[:, ports],
                fft.TOLERANCES[precision],
                f"acquisition {origin} FFT",
            )
            for origin in ("theory", "current")
        }
    return {
        "id": case["spec"]["id"],
        "binding": "reversed" if reverse else "identity",
        "input_sha256": case["arrays"]["input"]["sha256"],
        "output_sha256": hashes,
        "comparisons": comparisons,
        "acquisition_graph": header,
        "command": record,
    }


def verify(*, portable=False):
    started = time.perf_counter()
    binary, build_record = build()
    manifest, manifest_hash = candidate.load_manifest(core.DEFAULT_FIXTURES, portable=portable, is_core=True)
    corpus = [verify_case(binary, case, reverse=reverse) for case in manifest["tones"] for reverse in (False, True)]
    fft.assert_headless()
    native = ROOT / "native"
    paths = [native / name for name in ("Cargo.toml", "Cargo.lock", "rust-toolchain.toml")]
    for crate in ("audio-core", "dsp-core", "graph-core"):
        paths += [native / crate / "Cargo.toml", *sorted((native / crate).rglob("*.rs"))]
    return {
        "schema_version": 1,
        "task": "MIG-005-graph",
        "status": "pass",
        "mode": "portable" if portable else "pinned-reference",
        "environment": fft.environment(),
        "fixture_manifest_sha256": manifest_hash,
        "source_sha256": {str(p.relative_to(native)): fft.digest(p.read_bytes()) for p in paths},
        "runner_sha256": {
            name: fft.digest((ROOT / "scripts" / name).read_bytes())
            for name in (
                "migration_audio_graph.py",
                "migration_core_reference.py",
                "migration_fft_candidate.py",
                "migration_graph_candidate.py",
            )
        },
        "binary_sha256": fft.digest(binary.read_bytes()),
        "build": build_record,
        "corpus": corpus,
        "elapsed_seconds": time.perf_counter() - started,
        "limitations": [
            "Input.raw single-owner polling worker; output route delivery and Qt remain separate",
            "Backend seconds diagnostic only; origin and clock uncertainty unknown",
            "Bounded internal payload/work; retained external snapshots and process RSS separate",
            "No physical device, long-duration or steady-state performance acceptance",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--portable", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.report:
        report = args.report.resolve()
        if report.exists() or any(
            report.is_relative_to(p.resolve()) for p in (core.DEFAULT_FIXTURES, fft.DEFAULT_FIXTURES)
        ):
            parser.error("Report must be new and outside fixtures")
        report.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = verify(portable=args.portable)
        if args.report:
            fft.write_json(args.report, result)
        print(f"Acquisition graph OK: {len(result['corpus'])} original-byte/binding/shared-FFT cases")
        return 0
    except (fft.ReferenceError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"Acquisition graph failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
