"""Compare the pure Rust FFT with immutable MIG-003-A/B fixture bytes.

Builds only dsp-core, with the locked offline toolchain. No reference recomputation
or expected-value writes; each candidate process receives the original input.bin.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import migration_core_reference as core  # noqa: E402
from scripts import migration_fft_reference as fft  # noqa: E402

UNITS = {
    "fft_over_n": "FS",
    "inverse_windowed": "FS",
    "frequency_hz": "Hz",
    "peak_fs": "FS peak",
    "tone_rms_fs": "FS RMS",
    "rms_fs": "FS RMS",
    "psd_fs2_hz": "FS^2/Hz",
    "asd_fs_sqrt_hz": "FS/sqrt(Hz)",
    "integrated_power_fs2": "FS^2",
    "time_window_power_fs2": "FS^2",
    "window": "1",
}


def cargo_environment():
    env = os.environ.copy()
    local = ROOT / ".tools"
    if (local / "cargo/bin/cargo").exists():
        env["CARGO_HOME"] = str(local / "cargo")
        env["RUSTUP_HOME"] = str(local / "rustup")
        env["PATH"] = str(local / "cargo/bin") + os.pathsep + env.get("PATH", "")
    env["CARGO_BUILD_JOBS"] = "4"
    return env


def run_command(command, *, env=None, timeout=600):
    started = time.perf_counter()
    completed = subprocess.run(  # noqa: S603 - explicit argv, no shell; evaluation executables only
        command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, check=False
    )
    log = completed.stdout
    record = {
        "command": [str(arg) for arg in command],
        "exit_code": completed.returncode,
        "elapsed_seconds": time.perf_counter() - started,
        "log_sha256": fft.digest(log),
        "log_gzip_base64": base64.b64encode(gzip.compress(log, mtime=0)).decode("ascii"),
    }
    if completed.returncode != 0:
        raise fft.ReferenceError(f"Command failed ({completed.returncode}): {command}\n{log.decode(errors='replace')}")
    return record


def rust_tool(name, env):
    executable = shutil.which(name, path=env["PATH"])
    if executable is None:
        raise OSError(f"Rust tool is unavailable: {name}")
    return executable


def build(native_root):
    version = tomllib.loads((native_root / "rust-toolchain.toml").read_text())["toolchain"]["channel"]
    env = cargo_environment()
    # Resolve target placement explicitly so a caller's CARGO_TARGET_DIR cannot select a stale binary.
    target = native_root / "target"
    command = [
        rust_tool("cargo", env),
        f"+{version}",
        "build",
        "--offline",
        "--locked",
        "--manifest-path",
        str(native_root / "Cargo.toml"),
        "--target-dir",
        str(target),
        "-p",
        "dsp-core",
        "--bin",
        "fft-candidate",
    ]
    record = run_command(command, env=env)
    binary = target / "debug" / ("fft-candidate.exe" if os.name == "nt" else "fft-candidate")
    return binary, record


def load_manifest(directory, *, portable=False, baseline=None, is_core=False):
    data = (directory / "manifest.json").read_bytes()
    manifest = json.loads(data)
    if is_core:
        core.validate_manifest(manifest, portable=portable)
    else:
        fft.validate_manifest(manifest, strict_environment=not portable)
    if baseline is not None and manifest != json.loads(baseline.read_bytes()):
        raise fft.ReferenceError("Materialized manifest differs from versioned baseline")
    return manifest, fft.digest(data)


def request_for(case):
    spec = case["spec"]
    return {
        "schema_version": 1,
        "n": spec["n"],
        "dtype": spec["dtype"],
        "window": spec["window"],
        "rate_hz": spec["rate_hz"],
        "channel_ids": case["metadata"]["channel_ids"],
    }


def shapes_for(request):
    n, channels = request["n"], len(request["channel_ids"])
    bins = n // 2 + 1
    return {
        "fft_over_n": [bins, channels, 2],
        "inverse_windowed": [n, channels],
        "window": [n],
        "frequency_hz": [bins],
        **{name: [bins, channels] for name in ("peak_fs", "tone_rms_fs", "psd_fs2_hz", "asd_fs_sqrt_hz")},
        **{name: [channels] for name in ("rms_fs", "integrated_power_fs2", "time_window_power_fs2")},
    }


def read_candidate(directory, request):
    manifest = json.loads((directory / "manifest.json").read_bytes())
    expected_header = {
        "schema_version": 1,
        "request": request,
        "channel_ids": request["channel_ids"],
        "backend": "realfft-3.5.0",
        "fft_precision": request["dtype"],
        "reduction_precision": "<f8",
        "units": UNITS,
    }
    if set(manifest) != set(expected_header) | {"arrays"} or any(
        manifest[key] != value for key, value in expected_header.items()
    ):
        raise fft.ReferenceError("Candidate metadata/units/channel order mismatch")
    shapes = shapes_for(request)
    if set(manifest["arrays"]) != set(shapes):
        raise fft.ReferenceError("Candidate array inventory mismatch")
    arrays = {}
    hashes = {}
    for name, shape in shapes.items():
        entry = manifest["arrays"][name]
        expected = {
            "file": f"{name}.bin",
            "shape": shape,
            "dtype": request["dtype"] if name == "inverse_windowed" else "<f8",
            "byte_order": "little",
            "layout": "C/frame-major",
            "complex": "real-imag-last-axis" if name == "fft_over_n" else None,
            "origin": "candidate",
        }
        if entry != expected:
            raise fft.ReferenceError(f"Candidate {name} schema/dtype/shape mismatch")
        hashes[name] = fft.digest((directory / entry["file"]).read_bytes())
        arrays[name] = fft.read_array(directory, {**entry, "sha256": hashes[name]})
    return arrays, hashes


def verify_case(binary, directory, case, *, is_core=False):
    request = request_for(case)
    case_dir = directory / case["spec"]["id"]
    # Validate all input/expected bytes before using the file boundary. Do not regenerate them.
    # Core's loader also checks its array inventory, exact shape/dtype and origin.
    if is_core:
        checked = core.load_tone(directory, case)
        del checked
    else:
        for entry in case["arrays"].values():
            fft.read_array(case_dir, entry)
    input_path = case_dir / case["arrays"]["input"]["file"]
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="measurelab-rust-fft-") as temporary:
        temporary = Path(temporary)
        request_path = temporary / "request.json"
        fft.write_json(request_path, request)
        output = temporary / "output"
        command = run_command([str(binary), str(request_path), str(input_path), str(output)])
        # Require that the input stayed byte-identical across the candidate invocation.
        if fft.digest(input_path.read_bytes()) != case["arrays"]["input"]["sha256"]:
            raise fft.ReferenceError("Candidate changed the fixture input")
        observed, output_hashes = read_candidate(output, request)
        comparison_keys = set(observed) - {"tone_rms_fs", "asd_fs_sqrt_hz"}
        summaries = {}
        precision = "f32" if request["dtype"] == "<f4" else "f64"
        for origin in ("theory", "current"):
            expected = {key: fft.read_array(case_dir, case["arrays"][f"{origin}.{key}"]) for key in comparison_keys}
            summaries[origin] = fft.evaluate(case["spec"], observed, expected)
            factor = np.full(request["n"] // 2 + 1, np.sqrt(2.0))
            factor[0] = 1.0
            if request["n"] % 2 == 0:
                factor[-1] = 1.0
            summaries[origin]["max_absolute_errors"]["tone_rms_fs"] = fft.compare(
                observed["tone_rms_fs"],
                expected["peak_fs"] / factor[:, None],
                fft.TOLERANCES[precision],
                "coherent bin RMS",
            )
            # ASD magnifies insignificant FFT noise after sqrt, so check its exact relation
            # to candidate PSD, while PSD itself is compared with both saved references.
            summaries[origin]["max_absolute_errors"]["asd_relation"] = fft.compare(
                observed["asd_fs_sqrt_hz"] ** 2, observed["psd_fs2_hz"], fft.TOLERANCES[precision], "ASD squared"
            )
            del expected
        if case["spec"]["signal"] == "cosine":
            actual_bins = np.argmax(observed["peak_fs"], axis=0).tolist()
            if actual_bins != [tone[0] for tone in case["spec"]["tones"]]:
                raise fft.ReferenceError("Peak bins/channel order mismatch")
        return {
            "id": case["spec"]["id"],
            "spec": case["spec"],
            "input_metadata": case["metadata"],
            "input_sha256": case["arrays"]["input"]["sha256"],
            "candidate_output_sha256": output_hashes,
            "comparisons": summaries,
            "known_legacy_differences": case.get("known_differences", []),
            "command": command,
            "elapsed_seconds": time.perf_counter() - started,
        }


def verify(suites, *, native_root=None, portable=False):
    started = time.perf_counter()
    native_root = (native_root or ROOT / "native").resolve()
    binary, build_record = build(native_root)
    records = []
    for directory, baseline, is_core in suites:
        directory = directory.resolve()
        manifest, manifest_hash = load_manifest(directory, portable=portable, baseline=baseline, is_core=is_core)
        cases = manifest["tones"] if is_core else manifest["cases"]
        records.append(
            {
                "fixture_directory": str(directory),
                "fixture_manifest_sha256": manifest_hash,
                "cases": [verify_case(binary, directory, case, is_core=is_core) for case in cases],
            }
        )
    fft.assert_headless()
    env = cargo_environment()
    version = tomllib.loads((native_root / "rust-toolchain.toml").read_text())["toolchain"]["channel"]
    paths = [native_root / name for name in ("Cargo.toml", "Cargo.lock", "rust-toolchain.toml")]
    paths += sorted((native_root / "dsp-core").rglob("*.rs")) + [native_root / "dsp-core/Cargo.toml"]
    return {
        "schema_version": 1,
        "status": "pass",
        "mode": "portable-candidate-comparison" if portable else "pinned-fixture-candidate-comparison",
        "contract": fft.CONTRACT,
        "tolerances": fft.TOLERANCES,
        "source_sha256": {str(path.relative_to(native_root)): fft.digest(path.read_bytes()) for path in paths},
        "runner_sha256": fft.digest(Path(__file__).read_bytes()),
        "binary_sha256": fft.digest(binary.read_bytes()),
        "build": build_record,
        "environment": {
            "reference": fft.environment(),
            "rustc": subprocess.check_output(  # noqa: S603 - resolved tool, no shell
                [rust_tool("rustc", env), f"+{version}", "-Vv"], env=env, text=True
            ),
            "cargo": subprocess.check_output(  # noqa: S603 - resolved tool, no shell
                [rust_tool("cargo", env), f"+{version}", "-V"], env=env, text=True
            ).strip(),
            "profile": "debug",
            "build_jobs": 4,
            "fft_threads": 1,
            "fft_backend": "realfft-3.5.0; RustFFT version in Cargo.lock",
            "fft_precision": ["f32", "f64"],
            "reduction_precision": "f64",
            "os": platform.platform(),
            "build_environment": {
                name: env.get(name)
                for name in ("CARGO_BUILD_JOBS", "RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "MACOSX_DEPLOYMENT_TARGET")
            },
        },
        "suites": records,
        "elapsed_seconds": time.perf_counter() - started,
        "python_process_peak_rss_bytes": fft.peak_rss_bytes(),
        "limitations": [
            "Numerical file comparison; not a steady-state performance measurement",
            "No audio backend, routing, graph/result sharing, GUI, physical I/O or other-OS validation",
            "f32 transforms/inverse with f64 window construction, normalization and reductions",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extended", type=Path, help="Include materialized extended fixture directory")
    parser.add_argument("--portable", action="store_true")
    parser.add_argument("--native-root", type=Path, default=ROOT / "native")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    suites = [(fft.DEFAULT_FIXTURES, None, False), (core.DEFAULT_FIXTURES, None, True)]
    if args.extended:
        suites.append((args.extended, ROOT / "migration/fixtures/fft-extended-v1.manifest.json", False))
    if args.report:
        report = args.report.resolve()
        if report.exists() or any(report.is_relative_to(directory.resolve()) for directory, _, _ in suites):
            parser.error("Report must be new and outside fixture directories")
        report.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = verify(suites, native_root=args.native_root, portable=args.portable)
        if args.report:
            fft.write_json(args.report, result)
        print(f"Rust FFT candidate OK: {sum(len(s['cases']) for s in result['suites'])} cases ({result['mode']})")
        return 0
    except (fft.ReferenceError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"Rust FFT candidate failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
