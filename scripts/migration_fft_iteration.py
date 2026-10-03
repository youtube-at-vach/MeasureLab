"""Measure five identical core edits through Rust tests and all FFT comparisons.

Uses a fresh source copy and its own target; never edits the working checkout.
Fixture bytes, reference environment and lock stay fixed. This is a development
iteration measurement, not an FFT throughput or Python/Rust speed comparison.
"""

from __future__ import annotations

import argparse
import difflib
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import migration_fft_candidate as candidate  # noqa: E402
from scripts import migration_fft_reference as fft  # noqa: E402

# Equivalent branch refactor in a numerical primitive; not a timestamp/comment edit.
BASE = """    if bin == 0 || (n.is_multiple_of(2) && bin == n / 2) {
        1.0
    } else {
        2.0
    }"""
EDIT = """    match (bin == 0, n.is_multiple_of(2) && bin == n / 2) {
        (true, _) | (_, true) => 1.0,
        _ => 2.0,
    }"""


def edited_source(source):
    if source.count(BASE) != 1:
        raise fft.ReferenceError("Iteration patch no longer matches the core source")
    return source.replace(BASE, EDIT)


def measure(extended):
    suites = [
        (fft.DEFAULT_FIXTURES, None, False),
        (candidate.core.DEFAULT_FIXTURES, None, True),
        (extended.resolve(), ROOT / "migration/fixtures/fft-extended-v1.manifest.json", False),
    ]
    env = candidate.cargo_environment()
    baseline = (ROOT / "native/dsp-core/src/lib.rs").read_text()
    edited = edited_source(baseline)
    patch = "".join(
        difflib.unified_diff(baseline.splitlines(True), edited.splitlines(True), "base/lib.rs", "edit/lib.rs")
    )
    with tempfile.TemporaryDirectory(prefix="measurelab-core-iteration-") as temporary:
        native = Path(temporary) / "native"
        shutil.copytree(ROOT / "native", native, ignore=shutil.ignore_patterns("target"))
        source = native / "dsp-core/src/lib.rs"
        version = tomllib.loads((native / "rust-toolchain.toml").read_text())["toolchain"]["channel"]
        cargo = candidate.rust_tool("cargo", env)
        tests = [
            cargo,
            f"+{version}",
            "test",
            "--offline",
            "--locked",
            "--manifest-path",
            str(native / "Cargo.toml"),
            "--target-dir",
            str(native / "target"),
            "-p",
            "dsp-core",
        ]
        setup_tests = candidate.run_command(tests, env=env)
        warmup = candidate.verify(suites, native_root=native)
        samples = []
        restoration = []
        for index in range(5):
            source.write_text(edited)
            started = time.perf_counter()
            test_record = candidate.run_command(tests, env=env)
            verification = candidate.verify(suites, native_root=native)
            elapsed = time.perf_counter() - started
            if source.read_text() != edited:
                raise fft.ReferenceError("Iteration source changed during verification")
            samples.append(
                {
                    "index": index + 1,
                    "elapsed_seconds": elapsed,
                    "tests": test_record,
                    "verification": verification,
                }
            )
            print(f"Core edit {index + 1}/5: {elapsed:.3f}s; tests and 24 cases passed", flush=True)
            # Restore AND rebuild the base before the next identical edit. Outside measurement.
            source.write_text(baseline)
            restoration.append(candidate.run_command(tests, env=env))
        if source.read_text() != baseline or (ROOT / "native/dsp-core/src/lib.rs").read_text() != baseline:
            raise fft.ReferenceError("Core source restoration mismatch")
        times = [sample["elapsed_seconds"] for sample in samples]
        median = statistics.median(times)
        return {
            "schema_version": 1,
            "status": "pass",
            "scope": "debug core edit through tests and 24 fixed-fixture comparisons",
            "patch": patch,
            "patch_sha256": fft.digest(patch.encode()),
            "baseline_source_sha256": fft.digest(baseline.encode()),
            "edited_source_sha256": fft.digest(edited.encode()),
            "cache": "dedicated source copy/target; dependency downloads disabled; base rebuilt between edits",
            "setup_tests": setup_tests,
            "warmup": warmup,
            "samples": samples,
            "restoration_tests": restoration,
            "summary_seconds": {
                "median": median,
                "min": min(times),
                "max": max(times),
                "population_stddev": statistics.pstdev(times),
            },
            "budget": {
                "absolute_30_seconds": "pass" if median <= 30 else "exceeded",
                "full_protocol_max_30_or_twice_python": "unverified; no equivalent Python edit measurement",
            },
            "limitations": [
                "No Python/Rust relative speed claim, release/steady-state, other-OS or GUI propagation measurement",
                "Qt adapters have no DSP dependency yet; tests exercise the pure core only",
                "Patch creation time and development repair counts are recorded separately in the decision",
            ],
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extended", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists() or args.report.resolve().is_relative_to(args.extended.resolve()):
        parser.error("Report must be new and outside fixture directories")
    # Also protect the versioned small/core fixtures from accidental report placement.
    if any(args.report.resolve().is_relative_to(p) for p in (fft.DEFAULT_FIXTURES, candidate.core.DEFAULT_FIXTURES)):
        parser.error("Report must be outside fixture directories")
    try:
        result = measure(args.extended)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        fft.write_json(args.report, result)
        print(f"Core iteration OK: median {result['summary_seconds']['median']:.3f}s")
        return 0
    except (fft.ReferenceError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"Core iteration failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
