"""Generate/verify MIG-003-B: source-pinned N-channel FFT and new-contract cases.

Generate only into a NEW directory. Verify consumes saved inputs and expectations
without updating them. CSV/JSON below are fixture exchange formats, not a proposed
product format or a claim that the existing exporters implement the new contract.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import migration_core_cases as cases  # noqa: E402
from scripts import migration_core_oracle as model  # noqa: E402
from scripts import migration_fft_oracle as fft_oracle  # noqa: E402
from scripts import migration_fft_reference as fft  # noqa: E402

DEFAULT_FIXTURES = ROOT / "migration/fixtures/core-v1"
CONTRACT = "MIG-002-core-v0.1"
SCHEMA_VERSION = 1
GENERATOR_PATHS = (
    "scripts/migration_core_reference.py",
    "scripts/migration_core_oracle.py",
    "scripts/migration_core_cases.py",
    *fft.GENERATOR_PATHS,
)
CONTRACT_PATHS = ("migration/contracts/core.md", "migration/contracts/numerics.md")
NUMERIC_FIELDS = {
    "values",
    "peak_fs",
    "rms_fs",
    "rms_v",
    "dbv",
    "spl",
    "nominal",
    "corrected",
    "output.mixed",
    "output.device_buffer",
}
CSV_FIELDS = ["id", "peak_fs", "rms_fs", "rms_v", "dbv", "spl", "validity", "calibration"]


def compare_tree(actual, expected, path="root", numeric=False):
    """Metadata is exact; only declared measurement fields use tolerances."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or actual.keys() != expected.keys():
            raise fft.ReferenceError(f"{path}: metadata keys mismatch")
        for key, value in expected.items():
            compare_tree(actual[key], value, f"{path}.{key}", key in NUMERIC_FIELDS)
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            raise fft.ReferenceError(f"{path}: length/shape mismatch")
        for index, value in enumerate(expected):
            compare_tree(actual[index], value, f"{path}[{index}]", numeric)
    elif numeric and type(expected) in (int, float):
        if type(actual) not in (int, float) or not math.isfinite(actual):
            raise fft.ReferenceError(f"{path}: nonfinite/non-numeric value")
        tolerance = fft.TOLERANCES["db_f64"] if path.endswith(".dbv") else {"atol": 1e-12, "rtol": 1e-12}
        fft.compare(actual, expected, tolerance, path)
    elif type(actual) is not type(expected) or actual != expected:
        raise fft.ReferenceError(f"{path}: exact metadata mismatch: {actual!r} != {expected!r}")


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def read_json(data):
    def reject(value):
        raise fft.ReferenceError(f"Non-standard JSON constant: {value}")

    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise fft.ReferenceError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(data, parse_constant=reject, object_pairs_hook=unique_pairs)


def csv_bytes(result):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    metadata = {key: value for key, value in result.items() if key != "channels"}
    writer.writerow(["# MIG-003-B exchange v1", json.dumps(metadata, sort_keys=True, allow_nan=False)])
    writer.writerow(CSV_FIELDS)
    for channel in result["channels"]:
        writer.writerow(
            [
                json.dumps(channel[key], sort_keys=True, allow_nan=False)
                if key in ("validity", "calibration")
                else ""
                if channel[key] is None
                else channel[key]
                for key in CSV_FIELDS
            ]
        )
    return stream.getvalue().encode("utf-8")


def read_csv(data):
    rows = list(csv.reader(io.StringIO(data.decode("utf-8"), newline="")))
    if len(rows) < 3 or len(rows[0]) != 2 or rows[0][0] != "# MIG-003-B exchange v1" or rows[1] != CSV_FIELDS:
        raise fft.ReferenceError("CSV schema mismatch")
    result = read_json(rows[0][1])
    result["channels"] = []
    for row in rows[2:]:
        if len(row) != len(CSV_FIELDS):
            raise fft.ReferenceError("CSV column mismatch")
        channel = {}
        for key, cell in zip(CSV_FIELDS, row, strict=True):
            if key == "id":
                channel[key] = cell
            elif key in ("validity", "calibration"):
                channel[key] = read_json(cell)
            else:
                channel[key] = None if cell == "" else float(cell)
                if channel[key] is not None and not math.isfinite(channel[key]):
                    raise fft.ReferenceError("CSV nonfinite value")
        result["channels"].append(channel)
    return result


def save_result(path, result, format_id):
    """No success returned until the write completes; exceptions propagate."""
    data = json_bytes(result) if format_id == "json" else csv_bytes(result)
    with path.open("xb") as output:
        if output.write(data) != len(data):
            raise OSError("Incomplete result write")


def hashes(paths):
    return {name: fft.digest((ROOT / name).read_bytes()) for name in paths}


def header():
    return {
        "schema_version": SCHEMA_VERSION,
        "contract": CONTRACT,
        "contract_sha256": hashes(CONTRACT_PATHS),
        "reference_commit": fft.REFERENCE_COMMIT,
        "source_sha256": fft.source_hashes(),
        "generator_sha256": hashes(GENERATOR_PATHS),
        "environment": fft.environment(),
        "fft_tolerances": fft.TOLERANCES,
        "core_tolerances": {"atol": 1e-12, "rtol": 1e-12, "metadata": "exact", "db": fft.TOLERANCES["db_f64"]},
        "limitations": [
            "FFTManager is called once per channel; this does not validate AudioEngine N-channel support",
            "State, routing, history and calibration cases are new-contract oracles, not legacy engine results",
            "History cases model interval availability; no streaming storage or shared graph is implemented",
            "CSV/JSON are fixture exchange formats, not existing product exporter compatibility",
            "No candidate core, physical I/O, GUI, throughput or other OS validation",
        ],
    }


def tone_metadata(spec):
    ids = cases.CHANNEL_IDS[: len(spec["tones"])]
    return {
        **cases.provenance(),
        "result_id": spec["id"],
        "operation_revision": "fft-reference-v1",
        "channel_ids": ids,
        "dtype": spec["dtype"],
        "shape": [spec["n"], len(ids)],
        "layout": "C/frame-major",
        "calibration": {ch: {"revision": None, "state": "uncalibrated"} for ch in ids},
        "input_formula": "A*cos(2*pi*k*n/N+phase)",
        "seed": None,
        "current_origin": "FFTManager per channel, contract normalization adapter",
        "theory_origin": "analytic finite geometric sum, before f32 input quantization",
    }


def file_entry(path, origin):
    return {"file": path.name, "sha256": fft.digest(path.read_bytes()), "origin": origin}


def checked_file(directory, entry):
    name = entry["file"]
    if not isinstance(name, str) or Path(name).name != name:
        raise fft.ReferenceError("Unsafe fixture path")
    data = (directory / name).read_bytes()
    if fft.digest(data) != entry["sha256"]:
        raise fft.ReferenceError(f"{name}: SHA-256 mismatch")
    return data


def generate(directory):
    manifest = header()
    if directory.exists():
        raise fft.ReferenceError("Generation requires a new directory; expectations are never overwritten")
    directory.mkdir(parents=True)
    examples = cases.scenarios()
    for case in examples:
        compare_tree(model.evaluate(case), case["expected"], case["id"])
    scenario_path = directory / "scenarios.json"
    scenario_path.write_bytes(json_bytes(examples))
    manifest["scenarios"] = file_entry(scenario_path, "hand-calculated new-contract examples")
    manifest["exports"] = []
    for case in examples:
        if case["operation"] != "calibration":
            continue
        for format_id in ("json", "csv"):
            path = directory / f"{case['id']}.{format_id}"
            save_result(path, case["expected"], format_id)
            manifest["exports"].append(
                {"case_id": case["id"], "format": format_id, **file_entry(path, "new-contract exchange example")}
            )
    manifest["tones"] = []
    with fft.reference_backend() as (manager, window):
        for spec in cases.tone_specs():
            x = fft_oracle.make_input(spec)
            theory = fft_oracle.theory(spec, x)
            current = fft.current(spec, x, manager, window)
            fft.evaluate(spec, current, theory)
            case_dir = directory / spec["id"]
            case_dir.mkdir()
            arrays = {"input": fft.store_array(case_dir, "input", x, "fixed-input")}
            for origin, values in (("theory", theory), ("current", current)):
                for key, value in values.items():
                    arrays[f"{origin}.{key}"] = fft.store_array(case_dir, f"{origin}.{key}", value, origin)
            manifest["tones"].append({"spec": spec, "metadata": tone_metadata(spec), "arrays": arrays})
            manager._plans.clear()
            window.cache_clear()
    fft.assert_headless()
    fft.write_json(directory / "manifest.json", manifest)
    return manifest


def validate_manifest(manifest, portable=False):
    expected = header()
    if set(manifest) != set(expected) | {"scenarios", "exports", "tones"}:
        raise fft.ReferenceError("Manifest keys mismatch")
    for key, value in expected.items():
        if key == "environment" and portable:
            continue
        if manifest[key] != value:
            raise fft.ReferenceError(f"Manifest {key} mismatch")
    if manifest["scenarios"]["file"] != "scenarios.json":
        raise fft.ReferenceError("Scenario filename mismatch")
    if [case["spec"] for case in manifest["tones"]] != cases.tone_specs():
        raise fft.ReferenceError("Tone case/spec mismatch")
    expected_exports = [
        (case["id"], fmt) for case in cases.scenarios() if case["operation"] == "calibration" for fmt in ("json", "csv")
    ]
    if [(item["case_id"], item["format"]) for item in manifest["exports"]] != expected_exports:
        raise fft.ReferenceError("Export inventory mismatch")
    for entry in manifest["exports"]:
        if (
            entry["file"] != f"{entry['case_id']}.{entry['format']}"
            or entry["origin"] != "new-contract exchange example"
        ):
            raise fft.ReferenceError("Export metadata mismatch")
    for case in manifest["tones"]:
        if case["metadata"] != tone_metadata(case["spec"]):
            raise fft.ReferenceError("Tone metadata mismatch")


def load_tone(directory, case):
    spec = case["spec"]
    n, channels = spec["n"], len(spec["tones"])
    shapes = {
        "window": [n],
        "fft_over_n": [n // 2 + 1, channels, 2],
        "inverse_windowed": [n, channels],
        "frequency_hz": [n // 2 + 1],
        "peak_fs": [n // 2 + 1, channels],
        "psd_fs2_hz": [n // 2 + 1, channels],
        "rms_fs": [channels],
        "integrated_power_fs2": [channels],
        "time_window_power_fs2": [channels],
    }
    wanted = {"input"} | {f"{origin}.{key}" for origin in ("theory", "current") for key in shapes}
    if set(case["arrays"]) != wanted:
        raise fft.ReferenceError("Tone array inventory mismatch")
    result = {}
    for name, entry in case["arrays"].items():
        key = name.split(".")[-1]
        shape = [n, channels] if name == "input" else shapes[key]
        dtype = spec["dtype"] if name in ("input", "current.inverse_windowed") else "<f8"
        encoding = "real-imag-last-axis" if key == "fft_over_n" else None
        origin = "fixed-input" if name == "input" else name.split(".")[0]
        if (
            entry["shape"] != shape
            or entry["dtype"] != dtype
            or entry["complex"] != encoding
            or entry["origin"] != origin
            or entry["file"] != f"{name}.bin"
        ):
            raise fft.ReferenceError(f"{name}: array schema mismatch")
        result[name] = fft.read_array(directory / spec["id"], entry)
    return result


def verify(directory, portable=False, baseline=None):
    started = time.perf_counter()
    manifest = read_json((directory / "manifest.json").read_bytes())
    validate_manifest(manifest, portable)
    if baseline is not None and manifest != read_json(baseline.read_bytes()):
        raise fft.ReferenceError("Manifest differs from saved baseline")
    examples = read_json(checked_file(directory, manifest["scenarios"]))
    # The reviewed table is also checked exactly, independently of a caller-edited hash.
    if json_bytes(examples) != json_bytes(cases.scenarios()):
        raise fft.ReferenceError("Reviewed scenario input/expectation mismatch")
    for case in examples:
        compare_tree(model.evaluate(case), case["expected"], case["id"])
    lookup = {case["id"]: case for case in examples}
    for entry in manifest["exports"]:
        saved = checked_file(directory, entry)
        case = lookup[entry["case_id"]]
        decode = read_json if entry["format"] == "json" else read_csv
        encode = json_bytes if entry["format"] == "json" else csv_bytes
        compare_tree(decode(saved), case["expected"], entry["file"])
        compare_tree(decode(encode(model.evaluate(case))), case["expected"], "roundtrip")
    tones = []
    with fft.reference_backend() as (manager, window):
        for case in manifest["tones"]:
            spec = case["spec"]
            arrays = load_tone(directory, case)
            x = arrays["input"]
            theory = fft_oracle.theory(spec, x)
            current = fft.current(spec, x, manager, window)
            precision = "f32" if spec["dtype"] == "<f4" else "f64"
            for origin, values in (("theory", theory), ("current", current)):
                for key, value in values.items():
                    fft.compare(
                        value,
                        arrays[f"{origin}.{key}"],
                        fft.TOLERANCES["window" if key == "window" else precision],
                        key,
                    )
            # AC01 explicitly checks per-ID peak bin as well as complex/phase/RMS.
            expected_bins = [tone[0] for tone in spec["tones"]]
            if np.argmax(current["peak_fs"], axis=0).tolist() != expected_bins:
                raise fft.ReferenceError("Per-channel peak bin mismatch")
            tones.append({"id": spec["id"], **fft.evaluate(spec, current, theory)})
            manager._plans.clear()
            window.cache_clear()
    fft.assert_headless()
    return {
        "status": "pass",
        "mode": "portable-comparison" if portable else "pinned-reference",
        "manifest_sha256": fft.digest((directory / "manifest.json").read_bytes()),
        "environment": fft.environment(),
        "generator_sha256": hashes(GENERATOR_PATHS),
        "elapsed_seconds": time.perf_counter() - started,
        "process_peak_rss_bytes": fft.peak_rss_bytes(),
        "scenarios": [{"id": case["id"], "acceptance": case["acceptance"], "status": "pass"} for case in examples],
        "tones": tones,
        "exports": len(manifest["exports"]),
        "limitations": manifest["limitations"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    create = subcommands.add_parser("generate")
    create.add_argument("--output", type=Path, required=True)
    check = subcommands.add_parser("verify")
    check.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    check.add_argument("--portable", action="store_true")
    check.add_argument("--baseline", type=Path)
    check.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "generate":
            generate(args.output)
            print(f"Generated core fixture: {args.output}")
        else:
            if args.report and (args.report.exists() or args.report.resolve().is_relative_to(args.fixtures.resolve())):
                raise fft.ReferenceError("Report must be a new file outside the fixture directory")
            report = verify(args.fixtures, args.portable, args.baseline)
            if args.report:
                fft.write_json(args.report, report)
            print(
                f"Core reference OK: {len(report['tones'])} FFT, {len(report['scenarios'])} contract cases, "
                f"{report['exports']} exports ({report['mode']}); no GUI/device imports"
            )
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"Core reference failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
