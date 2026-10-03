"""MIG-006-C: saved history/time contracts and original 4/8ch bytes through Rust history.

No Qt, audio devices or fixture regeneration. Candidate requests contain inputs only.
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

OPERATIONS = {"history", "time"}


def build():
    native = ROOT / "native"
    env = candidate.cargo_environment()
    version = tomllib.loads((native / "rust-toolchain.toml").read_text())["toolchain"]["channel"]
    command = [
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
        "history-candidate",
    ]
    record = candidate.run_command(command, env=env)
    return native / "target/debug" / ("history-candidate.exe" if os.name == "nt" else "history-candidate"), record


def reviewed_cases(*, portable=False):
    directory = core.DEFAULT_FIXTURES
    manifest = json.loads((directory / "manifest.json").read_bytes())
    core.validate_manifest(manifest, portable)
    cases = core.read_json(core.checked_file(directory, manifest["scenarios"]))
    if core.json_bytes(cases) != core.json_bytes(core.cases.scenarios()):
        raise fft.ReferenceError("Reviewed history/time scenarios changed")
    return [case for case in cases if case["operation"] in OPERATIONS]


def validate_results(cases, observed):
    if not isinstance(observed, list) or len(observed) != len(cases):
        raise fft.ReferenceError("History result count mismatch")
    for case, result in zip(cases, observed, strict=True):
        if not isinstance(result, dict) or set(result) != {"id", "observed"} or result["id"] != case["id"]:
            raise fft.ReferenceError("History result identity mismatch")
        # These contracts contain rational integers, positions and reason strings only.
        # Canonical JSON also distinguishes a bool or float from an exact integer.
        if core.json_bytes(result["observed"]) != core.json_bytes(case["expected"]):
            raise fft.ReferenceError(f"History/time contract mismatch: {case['id']}")


def request_for(case):
    request = graph.request_for(case)
    return {
        "schema_version": 1,
        "source": request["key"]["source"],
        "start": request["start"],
        "n": request["key"]["n"],
        "window": request["key"]["window"],
    }


def read_corpus(directory, case):
    request = request_for(case)
    header = json.loads((directory / "manifest.json").read_bytes())
    n, channels = request["n"], len(request["source"]["channel_ids"])
    start, end = request["start"], request["start"] + n
    dtype = case["spec"]["dtype"]
    expected = {
        "schema_version": 1,
        "source": request["source"],
        "interval": [start, end],
        "dtype": dtype,
        "frames": n,
        "reader_positions": [end, end],
        "shared_allocation": True,
        "validity": [],
        "expired": {
            "stream_id": request["source"]["stream_id"],
            "generation": request["source"]["generation"],
            "timebase_id": request["source"]["timebase"]["id"],
            "interval": [start, end],
            "status": "gap",
            "missing": [[start, end]],
            "pending": [],
            "reason": "missing",
        },
        "retained_frames": 2 * n,
        "retained_numeric_bytes": 2 * n * channels * np.dtype(dtype).itemsize,
    }
    extras = {"result_id", "second_result_id", "before_release", "after_shutdown"}
    if not isinstance(header, dict) or set(header) != set(expected) | extras:
        raise fft.ReferenceError("History manifest fields mismatch")
    if any(core.json_bytes(header[k]) != core.json_bytes(v) for k, v in expected.items()):
        raise fft.ReferenceError("History identity, cursor, interval or retention mismatch")
    result_id = header["result_id"]
    if (
        not isinstance(result_id, dict)
        or set(result_id) != {"graph", "serial"}
        or any(type(v) is not int or v <= 0 for v in result_id.values())
        or core.json_bytes(header["second_result_id"]) != core.json_bytes(result_id)
    ):
        raise fft.ReferenceError("History FFT result identity mismatch")
    before = header["before_release"]
    if not isinstance(before, dict):
        raise fft.ReferenceError("History graph stats missing")
    numeric_bytes = before.get("cache_numeric_bytes")
    expected_stats = {
        "nodes": 1,
        "subscriptions": 2,
        "in_flight": 0,
        "cache_results": 1,
        "cache_numeric_bytes": numeric_bytes,
        "fft_evaluations": 1,
        "display_replacements": 0,
    }
    if (
        type(numeric_bytes) is not int
        or not 0 < numeric_bytes <= 64 * 1024**2
        or core.json_bytes(before) != core.json_bytes(expected_stats)
    ):
        raise fft.ReferenceError("History shared graph evaluation/count mismatch")
    after = {**expected_stats, "nodes": 0, "subscriptions": 0, "cache_results": 0, "cache_numeric_bytes": 0}
    if core.json_bytes(header["after_shutdown"]) != core.json_bytes(after):
        raise fft.ReferenceError("History graph resources retained")
    hashes = {}
    for name in ("snapshot", "delayed"):
        raw = (directory / f"{name}.bin").read_bytes()
        if len(raw) != n * channels * np.dtype(dtype).itemsize or fft.digest(raw) != case["arrays"]["input"]["sha256"]:
            raise fft.ReferenceError("History changed original input bytes")
        hashes[name] = fft.digest(raw)
    raw = (directory / "fft_over_n.bin").read_bytes()
    if len(raw) != (n // 2 + 1) * channels * 2 * 8:
        raise fft.ReferenceError("History FFT shape mismatch")
    array = np.frombuffer(raw, dtype="<f8").reshape(n // 2 + 1, channels, 2)
    if not np.all(np.isfinite(array)):
        raise fft.ReferenceError("History FFT nonfinite")
    hashes["fft_over_n"] = fft.digest(raw)
    return array[..., 0] + 1j * array[..., 1], hashes, header


def verify_case(binary, case):
    core.load_tone(core.DEFAULT_FIXTURES, case)
    case_dir = core.DEFAULT_FIXTURES / case["spec"]["id"]
    input_path = case_dir / case["arrays"]["input"]["file"]
    with tempfile.TemporaryDirectory(prefix="migration-history-corpus-") as temp:
        temp = Path(temp)
        request = temp / "request.json"
        fft.write_json(request, request_for(case))
        record = candidate.run_command([str(binary), "--corpus", str(request), str(input_path), str(temp / "output")])
        if fft.digest(input_path.read_bytes()) != case["arrays"]["input"]["sha256"]:
            raise fft.ReferenceError("History candidate changed fixture input")
        observed, hashes, header = read_corpus(temp / "output", case)
        precision = "f32" if case["spec"]["dtype"] == "<f4" else "f64"
        comparisons = {
            origin: fft.compare(
                observed,
                fft.read_array(case_dir, case["arrays"][f"{origin}.fft_over_n"]),
                fft.TOLERANCES[precision],
                f"history {origin} complex FFT",
            )
            for origin in ("theory", "current")
        }
    return {
        "id": case["spec"]["id"],
        "input_sha256": case["arrays"]["input"]["sha256"],
        "output_sha256": hashes,
        "comparisons": comparisons,
        "history_graph": header,
        "command": record,
    }


def verify(*, portable=False):
    started = time.perf_counter()
    binary, build_record = build()
    cases = reviewed_cases(portable=portable)
    with tempfile.TemporaryDirectory(prefix="migration-history-contracts-") as temp:
        temp = Path(temp)
        request, output = temp / "request.json", temp / "observed.json"
        fft.write_json(
            request, {"schema_version": 1, "cases": [{k: c[k] for k in ("id", "operation", "input")} for c in cases]}
        )
        record = candidate.run_command([str(binary), "--cases", str(request), str(output)])
        observed = json.loads(output.read_bytes())
        validate_results(cases, observed)
    manifest, manifest_hash = candidate.load_manifest(core.DEFAULT_FIXTURES, portable=portable, is_core=True)
    corpus = [verify_case(binary, case) for case in manifest["tones"]]
    fft.assert_headless()
    native = ROOT / "native"
    paths = [native / p for p in ("Cargo.toml", "Cargo.lock", "rust-toolchain.toml")]
    for crate in ("dsp-core", "graph-core"):
        paths += [native / crate / "Cargo.toml", *sorted((native / crate).rglob("*.rs"))]
    return {
        "schema_version": 1,
        "task": "MIG-006-C",
        "status": "pass",
        "mode": "portable" if portable else "pinned-reference",
        "environment": fft.environment(),
        "fixture_manifest_sha256": manifest_hash,
        "source_sha256": {str(p.relative_to(native)): fft.digest(p.read_bytes()) for p in paths},
        "runner_sha256": {
            name: fft.digest((ROOT / "scripts" / name).read_bytes())
            for name in (
                "migration_history_candidate.py",
                "migration_graph_candidate.py",
                "migration_fft_candidate.py",
                "migration_core_reference.py",
            )
        },
        "binary_sha256": fft.digest(binary.read_bytes()),
        "build": build_record,
        "contract_command": record,
        "contracts": observed,
        "corpus": corpus,
        "elapsed_seconds": time.perf_counter() - started,
        "limitations": [
            "Worker-owned synthetic acquisition only; no persistent acquisition scheduler, backend or Qt integration",
            "Clock mappings validated on exact fixtures, no physical clock fit or absolute delay accuracy claim",
            "History numeric payload and span counts bounded; external owned snapshots and process RSS separate",
            "Route/filter/calibration boundaries preserved and mixed-condition windows rejected",
            "Not a steady-state performance, other-OS or technology adoption result",
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
            report.is_relative_to(p.resolve()) for p in [core.DEFAULT_FIXTURES, fft.DEFAULT_FIXTURES]
        ):
            parser.error("Report must be new and outside fixtures")
        report.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = verify(portable=args.portable)
        if args.report:
            fft.write_json(args.report, result)
        print(
            f"History candidate OK: {len(result['contracts'])} contracts, {len(result['corpus'])} original-byte/shared-FFT cases"
        )
        return 0
    except (fft.ReferenceError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"History candidate failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
