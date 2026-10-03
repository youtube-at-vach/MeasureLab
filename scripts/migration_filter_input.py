"""Explicit f32 -> f64 acquisition/filter evaluation; original fixtures stay pinned."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import migration_core_reference as core  # noqa: E402
from scripts import migration_fft_candidate as candidate  # noqa: E402
from scripts import migration_fft_reference as fft  # noqa: E402
from scripts import migration_filter_candidate as filters  # noqa: E402
from scripts import migration_filter_oracle as oracle  # noqa: E402

RUNNERS = (*filters.RUNNERS, "scripts/migration_filter_input.py", "scripts/migration_filter_oracle.py")


def prepare(case, channels, reverse):
    if case["spec"]["kind"] != "fir" or channels not in (2, 4, 8):
        raise ValueError("Only the P2 causal FIR and 2/4/8ch are evaluated")
    request = filters.request_for(case, acquisition=True)
    original = fft.read_array(filters.FIXTURES / case["spec"]["id"], case["arrays"]["input"])
    # Additional virtual channels have distinct binary-rational scales. The f32
    # artifact is new input, never a replacement for the reviewed f64 fixture.
    values = np.column_stack([original[:, c % 2] * ((c + 1) / 8) for c in range(channels)]).astype("<f4")
    request["source"]["precision"] = "F32"
    request["source"]["channel_ids"] = [f"input.{c}" for c in range(channels)]
    request["input_conversion"] = "F32ToF64Exact"
    request["input_ports"] = list(reversed(range(channels))) if reverse else list(range(channels))
    return request, values


def check_output(directory, request, values, tolerances):
    arrays, hashes, header = filters.read_result(directory, request, acquisition=True)
    selected = values[:, request["input_ports"]].astype("<f8")
    observed_mask = np.ones(len(values), dtype=bool)
    for start, end in request["gaps"]:
        observed_mask[start:end] = False
    raw = selected[observed_mask]
    expected = oracle.fir_sum(selected, request["gaps"])
    comparisons = {}
    for name, array in arrays.items():
        if name.endswith(".raw_f32_as_f64"):
            if array.tobytes() != raw.tobytes():
                raise fft.ReferenceError("Raw f32 values/ports changed before explicit widening")
        elif name.endswith(".output"):
            comparisons[name] = fft.compare(array, expected, tolerances["fir"], "exact-widened f32 finite sum")
            if hashes[name] != hashes["whole.output"]:
                raise fft.ReferenceError("Widened FIR output changed across callback patterns")
        else:
            run = header["runs"][name.removesuffix(".fft_over_n")]
            start, end = next(w["interval"] for w in run["windows"] if w["numeric"])
            comparisons[name] = fft.compare(
                array[..., 0] + 1j * array[..., 1],
                np.fft.rfft(expected[start:end], axis=0) / 64,
                fft.TOLERANCES["f64"],
                "widened shared FFT",
            )
    return {"output_sha256": hashes, "comparisons": comparisons, "graph": header}


def verify_case(binary, case, channels, reverse, directory, tolerances):
    request, values = prepare(case, channels, reverse)
    directory.mkdir()
    input_path, request_path = directory / "input.f32.bin", directory / "request.json"
    data = values.tobytes()
    input_path.write_bytes(data)
    fft.write_json(request_path, request)
    record = candidate.run_command(
        [str(binary), "--acquisition", str(request_path), str(input_path), str(directory / "output")]
    )
    result = check_output(directory / "output", request, values, tolerances)
    if input_path.read_bytes() != data:
        raise fft.ReferenceError("Candidate mutated the f32 input artifact")
    return {
        "id": directory.name,
        "channels": channels,
        "input_ports": request["input_ports"],
        "fixture_input_sha256": case["arrays"]["input"]["sha256"],
        "input_f32_sha256": fft.digest(data),
        "command": record,
        **result,
    }


def verify(output, *, portable=False):
    started = time.perf_counter()
    manifest = filters.load_manifest(portable=portable)
    source, runners = filters.source_hashes(), core.hashes(RUNNERS)
    binary, build = filters.build()
    binary_hash = fft.digest(binary.read_bytes())
    output.mkdir(parents=True)
    try:
        cases = [case for case in manifest["cases"] if case["spec"]["kind"] == "fir"]
        corpus = [
            verify_case(
                binary,
                case,
                channels,
                reverse,
                output / f"{case['spec']['id']}-{channels}ch-{'reverse' if reverse else 'forward'}",
                manifest["tolerances"],
            )
            for case in cases
            for channels in (2, 4, 8)
            for reverse in (False, True)
        ]
        fft.assert_headless()
        if (
            source != filters.source_hashes()
            or runners != core.hashes(RUNNERS)
            or binary_hash != fft.digest(binary.read_bytes())
        ):
            raise fft.ReferenceError("Source, runner or binary changed during f32 input comparison")
        snapshot = output / "source-snapshot"
        for name, expected in {**{f"native/{p}": h for p, h in source.items()}, **runners}.items():
            target = snapshot / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
            if fft.digest(target.read_bytes()) != expected:
                raise fft.ReferenceError("Evidence source snapshot changed")
        binary_copy = output / "binaries" / binary.name
        binary_copy.parent.mkdir()
        shutil.copyfile(binary, binary_copy)
        if fft.digest(binary_copy.read_bytes()) != binary_hash:
            raise fft.ReferenceError("Evidence binary snapshot changed")
        result = {
            "schema_version": 1,
            "task": "MIG-006-D-explicit-f32-input",
            "status": "pass",
            "mode": "portable" if portable else "pinned-reference",
            "environment": fft.environment(),
            "fixture_manifest_sha256": filters.MANIFEST_SHA256,
            "source_sha256": source,
            "runner_sha256": runners,
            "binary_sha256": binary_hash,
            "build": build,
            "corpus": corpus,
            "elapsed_seconds": time.perf_counter() - started,
            "limitations": [
                "Saved f32 input through the real queue; live backend and Qt filter connection unverified",
                "Exact widening preserves device precision; arithmetic/filter output is f64",
                "P2 causal 3-tap FIR 48 -> 24 kHz only; no f32 arithmetic, chains or SOS gap recovery",
                "Mapped Trigger position/history metadata only; derived Qt Trigger/save integration pending",
                "Processing latency unknown; long runs, performance, other OS and physical clocks unverified",
            ],
        }
        fft.write_json(output / "report.json", result)
        artifacts = {
            str(p.relative_to(output)): fft.digest(p.read_bytes()) for p in sorted(output.rglob("*")) if p.is_file()
        }
        fft.write_json(output / "evidence-audit.json", {"schema_version": 1, "artifacts_sha256": artifacts})
        return result
    except (fft.ReferenceError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        fft.write_json(
            output / "failure.json",
            {"status": "fail", "error": str(error), "source_sha256": source, "binary_sha256": binary_hash},
        )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--portable", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or output.is_relative_to((ROOT / "migration/fixtures").resolve()):
        parser.error("Output must be new and outside fixtures")
    try:
        result = verify(output, portable=args.portable)
    except (fft.ReferenceError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"Explicit f32 input failed: {error}", file=sys.stderr)
        return 1
    print(f"Explicit f32 input OK: {len(result['corpus'])} cases × 5 callback patterns")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
