"""Compare shared Rust graph results with immutable MIG-003-A/B FFT bytes.

The native harness runs one FFT on an analysis thread, gives the same allocation
and result ID to two consumers, and releases graph ownership before exit.
"""

from __future__ import annotations

import argparse
from fractions import Fraction
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
from scripts import migration_fft_candidate as candidate  # noqa: E402
from scripts import migration_fft_reference as fft  # noqa: E402
from scripts import migration_core_reference as core  # noqa: E402

TRANSFORM_REVISION = "realfft-3.5.0-x-over-n-v1"


def rational(value):
    return None if value is None else {"numerator": value[0], "denominator": value[1]}


def request_for(case):
    spec, metadata = case["spec"], case["metadata"]
    timebase = metadata["timebase"]
    # MIG-003-A predates Stream/Timebase IDs: use an explicitly synthetic namespace,
    # retain unknown origin/uncertainty, and keep the entire original metadata in the report.
    rate = Fraction(str(spec["rate_hz"]))
    source = {
        "stream_id": metadata.get("stream_id", f"graph-fixture.{spec['id']}.input"),
        "generation": metadata.get("generation", timebase["generation"]),
        "channel_ids": metadata["channel_ids"],
        "precision": "F32" if spec["dtype"] == "<f4" else "F64",
        "timebase": {
            "id": timebase.get("id", f"graph-fixture.{spec['id']}.timebase"),
            "revision": 0,
            "clock_domain": timebase.get("clock_domain", timebase.get("clock")),
            "generation": timebase["generation"],
            "rate": rational(timebase.get("rate", [rate.numerator, rate.denominator])),
            "nominal_rate": rational(timebase.get("nominal_rate", [rate.numerator, rate.denominator])),
            "origin_sample": timebase.get("origin_sample", timebase.get("origin_frame")),
            "origin_seconds": rational(timebase.get("origin_seconds")),
            "origin_kind": timebase.get("origin_kind", "virtual"),
            "uncertainty_seconds": rational(timebase.get("uncertainty_seconds")),
        },
        "route_revision": metadata.get("route_revision", metadata.get("route", {}).get("revision")),
        "tap": "InputRaw",  # fixture.input / input.raw: synthetic saved input, no device binding
        "filter_state_revision": "none",
        "calibration_revision": "uncalibrated-FS",
    }
    return {
        "schema_version": 1,
        "key": {
            "source": source,
            "n": spec["n"],
            "hop": spec["n"],
            "alignment": metadata["interval"][0],
            "window": "Boxcar" if spec["window"] == "boxcar" else "SymmetricHann",
            "remove_dc": False,
        },
        "start": metadata["interval"][0],
    }


def build(native_root):
    version = tomllib.loads((native_root / "rust-toolchain.toml").read_text())["toolchain"]["channel"]
    env = candidate.cargo_environment()
    target = native_root / "target"
    command = [
        candidate.rust_tool("cargo", env),
        f"+{version}",
        "build",
        "--offline",
        "--locked",
        "--manifest-path",
        str(native_root / "Cargo.toml"),
        "--target-dir",
        str(target),
        "-p",
        "graph-core",
        "--bin",
        "graph-core",
    ]
    record = candidate.run_command(command, env=env)
    return target / "debug" / ("graph-core.exe" if os.name == "nt" else "graph-core"), record


def read_result(directory, case):
    request = request_for(case)
    header = json.loads((directory / "manifest.json").read_bytes())
    if not isinstance(header, dict):
        raise fft.ReferenceError("Graph manifest must be an object")
    result_id = header.get("result_id")
    expected = {
        "schema_version": 1,
        "request": request,
        "key": {**request["key"], "input_gains": []},
        "transform_revision": TRANSFORM_REVISION,
        "interval": case["metadata"]["interval"],
        "validity": [],
        "error": None,
        "shared_allocation": True,
        "average_count": 1,
    }
    if (
        set(header)
        != set(expected)
        | {"result_id", "spectrum_result_id", "spectrogram_result_id", "before_release", "after_shutdown", "arrays"}
        or any(
            json.dumps(header[key], sort_keys=True) != json.dumps(value, sort_keys=True)
            for key, value in expected.items()
        )
        or not isinstance(result_id, dict)
        or set(result_id) != {"graph", "serial"}
        or any(type(v) is not int or v <= 0 for v in result_id.values())
        or header["spectrum_result_id"] != result_id
        or header["spectrogram_result_id"] != result_id
        or any(not isinstance(header[field], dict) for field in ("before_release", "after_shutdown", "arrays"))
    ):
        raise fft.ReferenceError("Graph identity, sharing or metadata mismatch")
    stats = {
        "nodes": 1,
        "subscriptions": 2,
        "in_flight": 0,
        "cache_results": 1,
        "cache_numeric_bytes": header["before_release"].get("cache_numeric_bytes"),
        "fft_evaluations": 1,
        "display_replacements": 0,
    }
    if (
        json.dumps(header["before_release"], sort_keys=True) != json.dumps(stats, sort_keys=True)
        or type(stats["cache_numeric_bytes"]) is not int
        or not 0 < stats["cache_numeric_bytes"] <= 64 * 1024**2
    ):
        raise fft.ReferenceError("Graph evaluation/demand/cache count mismatch")
    after = {**stats, "nodes": 0, "subscriptions": 0, "cache_results": 0, "cache_numeric_bytes": 0}
    if json.dumps(header["after_shutdown"], sort_keys=True) != json.dumps(after, sort_keys=True):
        raise fft.ReferenceError("Graph ownership retained after shutdown")
    basic_request = candidate.request_for(case)
    shapes = candidate.shapes_for(basic_request)
    if set(header["arrays"]) != set(shapes):
        raise fft.ReferenceError("Graph array inventory mismatch")
    observed, hashes = {}, {}
    for name, shape in shapes.items():
        dtype = case["spec"]["dtype"] if name == "inverse_windowed" else "<f8"
        if header["arrays"][name] != {"file": f"{name}.bin", "shape": shape, "dtype": dtype}:
            raise fft.ReferenceError(f"Graph {name} dtype/shape mismatch")
        raw = (directory / f"{name}.bin").read_bytes()
        hashes[name] = fft.digest(raw)
        if len(raw) != np.prod(shape) * np.dtype(dtype).itemsize:
            raise fft.ReferenceError(f"Graph {name} byte count mismatch")
        array = np.frombuffer(raw, dtype=dtype).reshape(shape)
        if not np.all(np.isfinite(array)):
            raise fft.ReferenceError(f"Graph {name} is nonfinite")
        if name == "fft_over_n":
            array = array[..., 0] + 1j * array[..., 1]
        observed[name] = array
    return observed, hashes, header


def verify_case(binary, directory, case, *, is_core=False):
    case_dir = directory / case["spec"]["id"]
    if is_core:
        core.load_tone(directory, case)
    else:
        for entry in case["arrays"].values():
            fft.read_array(case_dir, entry)
    input_path = case_dir / case["arrays"]["input"]["file"]
    with tempfile.TemporaryDirectory(prefix="measurelab-shared-graph-") as temporary:
        temporary = Path(temporary)
        request_path = temporary / "request.json"
        fft.write_json(request_path, request_for(case))
        output = temporary / "output"
        record = candidate.run_command([str(binary), str(request_path), str(input_path), str(output)])
        if fft.digest(input_path.read_bytes()) != case["arrays"]["input"]["sha256"]:
            raise fft.ReferenceError("Graph candidate changed fixture input")
        observed, hashes, header = read_result(output, case)
        comparison_keys = set(observed) - {"tone_rms_fs", "asd_fs_sqrt_hz"}
        summaries = {}
        precision = "f32" if case["spec"]["dtype"] == "<f4" else "f64"
        for origin in ("theory", "current"):
            expected = {key: fft.read_array(case_dir, case["arrays"][f"{origin}.{key}"]) for key in comparison_keys}
            summaries[origin] = fft.evaluate(case["spec"], observed, expected)
            factor = np.full(case["spec"]["n"] // 2 + 1, np.sqrt(2.0))
            factor[0] = 1.0
            if case["spec"]["n"] % 2 == 0:
                factor[-1] = 1.0
            fft.compare(
                observed["tone_rms_fs"],
                expected["peak_fs"] / factor[:, None],
                fft.TOLERANCES[precision],
                "graph bin RMS",
            )
            fft.compare(
                observed["asd_fs_sqrt_hz"] ** 2, observed["psd_fs2_hz"], fft.TOLERANCES[precision], "graph ASD squared"
            )
        return {
            "id": case["spec"]["id"],
            "input_sha256": case["arrays"]["input"]["sha256"],
            "input_metadata": case["metadata"],
            "candidate_output_sha256": hashes,
            "comparisons": summaries,
            "graph": {k: v for k, v in header.items() if k != "arrays"},
            "command": record,
        }


def verify(*, native_root=None, portable=False):
    native_root = (native_root or ROOT / "native").resolve()
    started = time.perf_counter()
    binary, build_record = build(native_root)
    records = []
    for directory, is_core in [(fft.DEFAULT_FIXTURES, False), (core.DEFAULT_FIXTURES, True)]:
        manifest, manifest_hash = candidate.load_manifest(directory, portable=portable, is_core=is_core)
        cases = manifest["tones"] if is_core else manifest["cases"]
        records.append(
            {
                "fixture_directory": str(directory),
                "fixture_manifest_sha256": manifest_hash,
                "cases": [verify_case(binary, directory, case, is_core=is_core) for case in cases],
            }
        )
    fft.assert_headless()
    paths = [native_root / p for p in ("Cargo.toml", "Cargo.lock", "rust-toolchain.toml")]
    for crate in ("dsp-core", "graph-core"):
        paths += [native_root / crate / "Cargo.toml", *sorted((native_root / crate).rglob("*.rs"))]
    env = candidate.cargo_environment()
    version = tomllib.loads((native_root / "rust-toolchain.toml").read_text())["toolchain"]["channel"]
    return {
        "schema_version": 1,
        "status": "pass",
        "task": "MIG-006-B",
        "mode": "portable" if portable else "pinned-reference",
        "source_sha256": {str(p.relative_to(native_root)): fft.digest(p.read_bytes()) for p in paths},
        "runner_sha256": {
            name: fft.digest((ROOT / "scripts" / name).read_bytes())
            for name in (
                "migration_graph_candidate.py",
                "migration_fft_candidate.py",
                "migration_fft_reference.py",
                "migration_core_reference.py",
            )
        },
        "binary_sha256": fft.digest(binary.read_bytes()),
        "build": build_record,
        "environment": fft.environment(),
        "rustc": subprocess.check_output(  # noqa: S603 - resolved tool, explicit argv
            [candidate.rust_tool("rustc", env), f"+{version}", "-Vv"], env=env, text=True
        ),
        "profile": "debug",
        "build_jobs": 4,
        "fft_threads_per_job": 1,
        "tolerances": fft.TOLERANCES,
        "suites": records,
        "elapsed_seconds": time.perf_counter() - started,
        "limitations": [
            "Synthetic complete windows; no acquisition queue, real backend, trigger/history or GUI adapter",
            "One caller-owned analysis thread per corpus case; production scheduler and callback integration deferred",
            "Cache bounds graph-owned numeric arrays, not externally retained snapshots or total process RSS",
            "Small FFT corpus 14 + 4/8-channel corpus 4; extended corpus and steady-state performance not evaluated",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--portable", action="store_true")
    parser.add_argument("--native-root", type=Path, default=ROOT / "native")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.report:
        report = args.report.resolve()
        if report.exists() or any(
            report.is_relative_to(p.resolve()) for p in [fft.DEFAULT_FIXTURES, core.DEFAULT_FIXTURES]
        ):
            parser.error("Report must be new and outside fixture directories")
        report.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = verify(native_root=args.native_root, portable=args.portable)
        if args.report:
            fft.write_json(args.report, result)
        print(
            f"Shared graph candidate OK: {sum(len(s['cases']) for s in result['suites'])} cases, one FFT/two consumers"
        )
        return 0
    except (fft.ReferenceError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"Shared graph candidate failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
