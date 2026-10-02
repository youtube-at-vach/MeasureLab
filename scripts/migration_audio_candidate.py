"""MIG-005-A: immutable route/tap/block fixtures through the Rust audio boundary.

No devices opened. Expectations and fixture bytes are never regenerated.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import migration_core_reference as core  # noqa: E402
from scripts import migration_fft_candidate as candidate  # noqa: E402
from scripts import migration_fft_reference as fft  # noqa: E402

OPERATIONS = {"route", "route_changes", "taps", "blocks"}


def build(package="audio-core", *, release=False):
    env = candidate.cargo_environment()
    command = [
        candidate.rust_tool("cargo", env),
        "+1.98.1",
        "build",
        "--offline",
        "--locked",
        "--manifest-path",
        str(ROOT / "native/Cargo.toml"),
        "--target-dir",
        str(ROOT / "native/target"),
        "-p",
        package,
    ]
    if release:
        command.append("--release")
    record = candidate.run_command(command, env=env)
    return ROOT / "native/target" / ("release" if release else "debug") / package, record


def reviewed_cases(directory=core.DEFAULT_FIXTURES, *, portable=False):
    manifest = json.loads((directory / "manifest.json").read_bytes())
    core.validate_manifest(manifest, portable)
    cases = core.read_json(core.checked_file(directory, manifest["scenarios"]))
    if core.json_bytes(cases) != core.json_bytes(core.cases.scenarios()):
        raise fft.ReferenceError("Reviewed scenario input/expectation mismatch")
    return [case for case in cases if case["operation"] in OPERATIONS]


def validate_results(cases, observed):
    if not isinstance(observed, list) or len(observed) != len(cases):
        raise fft.ReferenceError("Audio fixture result count mismatch")
    for case, result in zip(cases, observed, strict=True):
        if not isinstance(result, dict) or set(result) != {"id", "observed"} or result["id"] != case["id"]:
            raise fft.ReferenceError("Audio fixture result identity mismatch")
        core.compare_tree(result["observed"], case["expected"], case["id"])


def verify_queues(binary, *, portable=False):
    manifest, manifest_hash = candidate.load_manifest(core.DEFAULT_FIXTURES, portable=portable, is_core=True)
    results = []
    for case in manifest["tones"]:
        core.load_tone(core.DEFAULT_FIXTURES, case)
        spec = case["spec"]
        source = core.DEFAULT_FIXTURES / spec["id"] / case["arrays"]["input"]["file"]
        with tempfile.TemporaryDirectory(prefix="migration-queue-") as temp:
            request = {
                "schema_version": 1,
                "channel_ids": case["metadata"]["channel_ids"],
                "dtype": spec["dtype"],
                "frames": spec["n"],
                "chunk_frames": 256,
                "capacity": 4096,
                "generation": 3,
                "rate": 48000,
            }
            request_path = Path(temp) / "request.json"
            fft.write_json(request_path, request)
            output = Path(temp) / "output"
            record = candidate.run_command([str(binary), "--queue", str(request_path), str(source), str(output)])
            observed = json.loads((output / "manifest.json").read_bytes())
            expected_format = {
                "stream_id": "fixture.audio",
                "generation": 3,
                "timebase_id": "fixture.timebase",
                "clock_domain": "fixture.virtual",
                "rate": [48000, 1],
                "input_ids": request["channel_ids"],
                "input_ports": list(range(len(request["channel_ids"]))),
                "output_ids": [],
                "output_ports": [],
            }
            expected = {
                "schema_version": 1,
                "format": expected_format,
                "dtype": spec["dtype"],
                "frames": spec["n"],
                "samples": list(range(spec["n"])),
                "gaps": [],
            }
            if observed != expected or (output / "output.bin").read_bytes() != source.read_bytes():
                raise fft.ReferenceError("Queue changed original sample bytes, positions, precision or identity")
        results.append(
            {
                "id": spec["id"],
                "input_sha256": fft.digest(source.read_bytes()),
                "manifest_sha256": manifest_hash,
                "status": "pass",
                "command": record,
            }
        )
    return results


def verify(*, portable=False):
    binary, build_record = build()
    cases = reviewed_cases(portable=portable)
    with tempfile.TemporaryDirectory(prefix="migration-audio-") as temp:
        request = Path(temp) / "cases.json"
        # Send input and operation only; expected results never enter the Rust process.
        fft.write_json(request, [{key: case[key] for key in ("id", "operation", "input")} for case in cases])
        record = candidate.run_command([str(binary), str(request)])
        observed = json.loads(gzip.decompress(base64.b64decode(record["log_gzip_base64"])))
    validate_results(cases, observed)
    queues = verify_queues(binary, portable=portable)
    return {
        "schema_version": 1,
        "task": "MIG-005-A",
        "queues": queues,
        "cases": observed,
        "commands": [build_record, record],
        "source_sha256": {
            str(path.relative_to(ROOT)): fft.digest(path.read_bytes())
            for path in [
                *sorted((ROOT / "native/audio-core/src").rglob("*.rs")),
                ROOT / "native/Cargo.lock",
                Path(__file__),
            ]
        },
        "fixture_manifest_sha256": fft.digest((core.DEFAULT_FIXTURES / "manifest.json").read_bytes()),
        "binary_sha256": fft.digest(binary.read_bytes()),
        "status": "pass",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--portable", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = verify(portable=args.portable)
    if args.report:
        fft.write_json(args.report, report)
    print(
        f"Audio candidate OK: {len(report['cases'])} immutable route/tap/block cases; {len(report['queues'])} exact 4/8ch f32/f64 queues"
    )


if __name__ == "__main__":
    main()
