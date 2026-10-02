"""MIG-006-E: immutable calibration/exchange and shared FFT using saved inputs only.

NumPy-only headless runner; no fixture regeneration, devices, Qt or product exporter changes.
"""

from __future__ import annotations

import argparse
import csv
import io
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
            "result-candidate",
        ],
        env=env,
    )
    return native / "target/debug" / ("result-candidate.exe" if os.name == "nt" else "result-candidate"), record


def read_result(directory):
    document = core.read_json((directory / "result.json").read_bytes())
    csv_text = (directory / "result.csv").read_text()
    if not csv_text.endswith('"\n'):
        raise fft.ReferenceError("Truncated CSV row")
    try:
        rows = list(csv.reader(io.StringIO(csv_text, newline=""), strict=True))
    except csv.Error as error:
        raise fft.ReferenceError(f"Invalid CSV: {error}") from error
    if (
        len(rows) < 3
        or len(rows[0]) != 2
        or rows[0][0] != "# MIG-006-E exchange v1"
        or rows[1] != ["metric", "index", "value", "reason"]
    ):
        raise fft.ReferenceError("Result CSV schema mismatch")
    reread = core.read_json(rows[0][1])
    for column in reread["columns"].values():
        if column["values"] or column["reasons"]:
            raise fft.ReferenceError("CSV metadata contains numeric payload")
    for row in rows[2:]:
        if len(row) != 4 or row[0] not in reread["columns"]:
            raise fft.ReferenceError("CSV row mismatch")
        column = reread["columns"][row[0]]
        if row[1] != str(len(column["values"])):
            raise fft.ReferenceError("CSV row order mismatch")
        value = None if not row[2] else float(row[2])
        reason = row[3] or None
        if (value is None) != (reason is not None) or (value is not None and not np.isfinite(value)):
            raise fft.ReferenceError("CSV null/reason or finite-value mismatch")
        column["values"].append(value)
        column["reasons"].append(reason)
    # Exact f64/f32-representable values; no tolerance for a serialization roundtrip.
    if core.json_bytes(reread) != core.json_bytes(document):
        raise fft.ReferenceError("CSV/JSON roundtrip mismatch")
    return document


def validate_async_audit(audit, document, directory):
    """Accept completed worker receipts only, with the submitted snapshot identity."""
    if (
        set(audit) != {"capacity", "receipts", "snapshot_released_by_worker"}
        or type(audit["capacity"]) is not int
        or audit["capacity"] != 2
        or audit["snapshot_released_by_worker"] is not True
        or len(audit["receipts"]) != 6
    ):
        raise fft.ReferenceError("Async save capacity/ownership inventory mismatch")
    operations = [
        ("result.json", "json", "saved", None),
        ("result.csv", "csv", "saved", None),
        ("result.json", "json", "failed", "AlreadyExists"),
        ("result.csv", "csv", "failed", "AlreadyExists"),
        ("absent/result.json", "json", "failed", "NotFound"),
        ("recovered.json", "json", "saved", None),
    ]
    for index, (receipt, (name, fmt, status, kind)) in enumerate(zip(audit["receipts"], operations, strict=True), 1):
        expected = {
            "operation_id": index,
            "result_id": document["capture"]["result_id"],
            "generation": document["source"]["generation"],
            "interval": document["interval"],
            "destination": str(directory / name),
            "format": fmt,
        }
        if (
            set(receipt) != set(expected) | {"status"}
            or any(core.json_bytes(receipt[key]) != core.json_bytes(value) for key, value in expected.items())
            or type(receipt["operation_id"]) is not int
            or type(receipt["generation"]) is not int
        ):
            raise fft.ReferenceError("Async save receipt identity mismatch")
        outcome = receipt["status"]
        if kind is None:
            if outcome != {"state": status}:
                raise fft.ReferenceError("Async save is not completed")
        elif (
            set(outcome) != {"state", "kind", "message"}
            or outcome["state"] != status
            or outcome["kind"] != kind
            or not isinstance(outcome["message"], str)
            or not outcome["message"]
        ):
            raise fft.ReferenceError("Async save failure mismatch")
    return audit


def check_async_roundtrips(binary, directory):
    document = read_result(directory)
    records = []
    for fmt in ("json", "csv"):
        original = directory / f"result.{fmt}"
        original_hash = fft.digest(original.read_bytes())
        output = directory / f"async-from-{fmt}"
        command = candidate.run_command([str(binary), f"--async-read-{fmt}", str(original), str(output)])
        if core.json_bytes(read_result(output)) != core.json_bytes(document):
            raise fft.ReferenceError("Async save changed numeric arrays or provenance")
        if (
            fft.digest(original.read_bytes()) != original_hash
            or (output / "recovered.json").read_bytes() != (output / "result.json").read_bytes()
            or (output / "absent").exists()
            or any(output.glob("*.tmp"))
            or any(output.glob(".*.tmp"))
        ):
            raise fft.ReferenceError("Async save modified input or left partial output")
        audit = validate_async_audit(core.read_json((output / "audit.json").read_bytes()), document, output)
        records.append(
            {
                "format": fmt,
                "command": command,
                "audit": audit,
                "input_sha256": original_hash,
                "file_sha256": {p.name: fft.digest(p.read_bytes()) for p in sorted(output.iterdir())},
            }
        )
    return records


def pair(value):
    return None if value is None else [value["numerator"], value["denominator"]]


def fixture_projection(document):
    """Rearrange candidate observations into the already reviewed exchange shape.

    This adapter does not calculate expected values or calibrate anything.
    """
    source, capture, columns = document["source"], document["capture"], document["columns"]
    timebase = dict(source["timebase"])
    timebase.pop("revision")
    for name in ("rate", "nominal_rate", "origin_seconds", "uncertainty_seconds"):
        timebase[name] = pair(timebase[name])

    # Rust's typed f64 schema writes 1.0; the older fixture spells integral coefficients as 1.
    # Normalize only these two scalar representations; their numeric values remain exact.
    def legacy_scalar(value):
        return int(value) if type(value) is float and value.is_integer() else value

    axis = dict(document["axis"])
    axis["correction"] = legacy_scalar(axis["correction"])
    profiles = [dict(c["profile"]) for c in document["calibration"]]
    for profile in profiles:
        profile["v_per_fs"] = legacy_scalar(profile["v_per_fs"])
    return {
        "result_id": capture["result_id"],
        "operation_revision": document["operation_revision"],
        "stream_id": source["stream_id"],
        "generation": source["generation"],
        "interval": document["interval"],
        "timebase": timebase,
        "trigger_id": capture["trigger_id"],
        "route_revision": source["route_revision"],
        "tap": "input.raw" if source["tap"] == "InputRaw" else source["tap"],
        "acquired_host_seconds": pair(capture["acquired_host_seconds"]),
        "result_host_seconds": pair(capture["result_host_seconds"]),
        "validity": document["validity"],
        "axis": axis,
        "units": {name: columns[name]["unit"] for name in ("peak_fs", "rms_fs", "rms_v", "dbv", "spl")},
        "channels": [
            {
                "id": channel,
                **{name: columns[name]["values"][i] for name in ("peak_fs", "rms_fs", "rms_v", "dbv", "spl")},
                "calibration": profiles[i],
                "validity": {name: columns[name]["reasons"][i] for name in ("rms_v", "spl")},
            }
            for i, channel in enumerate(source["channel_ids"])
        ],
    }


def request_for(case):
    request = graph.request_for(case)
    start, end = case["metadata"]["interval"]
    ids = request["key"]["source"]["channel_ids"]
    return {
        **request,
        "capture": {
            "result_id": f"saved.{case['spec']['id']}",
            "trigger_id": "synthetic.result-trigger",
            "acquired_host_seconds": None,
            "trigger": None,
            "clock_mapping": None,
            "result_host_seconds": {"numerator": 11, "denominator": 1},
        },
        "frequency_correction": 1.0001,
        "profiles": {
            channel: {
                "revision": "synthetic.profile.1",
                "device_binding": {"device": "saved-fixture", "port": i},
                "is_calibrated": i != len(ids) - 1,
                "v_per_fs": 1 + i / 4,
                "applied_interval": [start, end],
            }
            for i, channel in enumerate(ids)
        },
    }


def validate_corpus(document, request, case):
    source = request["key"]["source"]
    exact = {
        "schema_version": 1,
        "source": source,
        "capture": request["capture"],
        "operation_revision": graph.TRANSFORM_REVISION,
        "interval": case["metadata"]["interval"],
        "conditions": {**request["key"], "input_gains": []},
        "validity": [],
        "error": None,
        "calibration": [
            {"channel_id": channel, "profile": request["profiles"][channel], "application": "after_analysis"}
            for channel in source["channel_ids"]
        ],
    }
    if set(document) != set(exact) | {"raw_result_id", "axis", "columns"}:
        raise fft.ReferenceError("Result document inventory mismatch")
    if any(core.json_bytes(document[k]) != core.json_bytes(v) for k, v in exact.items()):
        raise fft.ReferenceError("Result provenance/calibration mismatch")
    if any(type(v) is not int or v <= 0 for v in document["raw_result_id"]) or len(document["raw_result_id"]) != 2:
        raise fft.ReferenceError("Result identity mismatch")
    spec, channels = case["spec"], len(source["channel_ids"])
    n, bins = spec["n"], spec["n"] // 2 + 1
    shapes = candidate.shapes_for(candidate.request_for(case))
    shapes.pop("frequency_hz")
    shapes.update(rms_v=[channels], dbv=[channels], spl=[channels], psd_v2_hz=[bins, channels])
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
    if set(document["columns"]) != set(shapes):
        raise fft.ReferenceError("Result column inventory mismatch")
    arrays = {}
    for name, shape in shapes.items():
        column = document["columns"][name]
        precision = source["precision"] if name == "inverse_windowed" else "F64"
        if (
            set(column) != {"shape", "precision", "unit", "values", "reasons"}
            or column["shape"] != shape
            or column["unit"] != units[name]
            or column["precision"] != precision
        ):
            raise fft.ReferenceError("Result column metadata mismatch")
        if len(column["values"]) != np.prod(shape) or len(column["reasons"]) != np.prod(shape):
            raise fft.ReferenceError("Result column shape mismatch")
        for value, reason in zip(column["values"], column["reasons"], strict=True):
            if (value is None) != (reason is not None) or (
                value is not None and (type(value) not in (int, float) or not np.isfinite(value))
            ):
                raise fft.ReferenceError("Result invalid numeric/null/reason")
        arrays[name] = np.asarray(column["values"], dtype=float).reshape(shape)
    axis = document["axis"]
    nominal = np.arange(bins) * spec["rate_hz"] / n
    if (
        set(axis) != {"dimension", "unit", "nominal", "corrected", "correction"}
        or axis["dimension"] != "frequency"
        or axis["unit"] != "Hz"
        or axis["correction"] != 1.0001
        or not np.array_equal(axis["nominal"], nominal)
        or not np.array_equal(axis["corrected"], nominal * 1.0001)
    ):
        raise fft.ReferenceError("Result frequency axis mismatch")
    # Independent expectation from the candidate's relative values: test scale and density Jacobian.
    gain = np.array([1 + i / 4 for i in range(channels)])
    for name, expected in {
        "rms_v": arrays["rms_fs"] * gain,
        "dbv": 20 * np.log10(arrays["rms_fs"] * gain),
        "psd_v2_hz": arrays["psd_fs2_hz"] * gain**2 / 1.0001,
    }.items():
        fft.compare(arrays[name][..., :-1], expected[..., :-1], {"atol": 1e-12, "rtol": 1e-12}, name)
        reasons = np.asarray(document["columns"][name]["reasons"]).reshape(shapes[name])
        if not np.isnan(arrays[name][..., -1]).all() or not (reasons[..., -1] == "uncalibrated").all():
            raise fft.ReferenceError("Uncalibrated absolute channel mismatch")
    if not np.isnan(arrays["spl"]).all() or document["columns"]["spl"]["reasons"] != ["uncalibrated"] * channels:
        raise fft.ReferenceError("Uncalibrated SPL mismatch")
    return arrays


def verify(*, portable=False, async_save=False, output=None):
    started = time.perf_counter()
    manifest, manifest_hash = candidate.load_manifest(core.DEFAULT_FIXTURES, portable=portable, is_core=True)
    scenarios = core.read_json(core.checked_file(core.DEFAULT_FIXTURES, manifest["scenarios"]))
    if core.json_bytes(scenarios) != core.json_bytes(core.cases.scenarios()):
        raise fft.ReferenceError("Reviewed calibration scenarios changed")
    # Audit every saved input/output hash, not just the subset being exercised.
    for case in manifest["tones"]:
        core.load_tone(core.DEFAULT_FIXTURES, case)
    exports = {}
    for entry in manifest["exports"]:
        data = core.checked_file(core.DEFAULT_FIXTURES, entry)
        exports[entry["case_id"], entry["format"]] = (
            core.read_json(data) if entry["format"] == "json" else core.read_csv(data)
        )
    binary, build_record = build()
    contracts, corpus, async_records = [], [], []
    if output is not None:
        output = Path(output).resolve()
        output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="migration-results-") as temp:
        temp = output or Path(temp)
        for case in [c for c in scenarios if c["operation"] == "calibration"]:
            request, output = temp / "request.json", temp / case["id"]
            fft.write_json(request, {"schema_version": 1, "input": case["input"]})
            command = candidate.run_command([str(binary), "--tone", str(request), str(output)])
            observed = fixture_projection(read_result(output))
            core.compare_tree(observed, case["expected"])
            for fmt in ("json", "csv"):
                core.compare_tree(observed, exports[case["id"], fmt])
            audit = core.read_json((output / "audit.json").read_bytes())
            if audit != {
                "profile_change_kept_old_result": True,
                "roundtrips": 2,
                "existing_destination_rejected": True,
            }:
                raise fft.ReferenceError("Profile/roundtrip invariant mismatch")
            contracts.append(
                {
                    "id": case["id"],
                    "command": command,
                    "audit": audit,
                    "file_sha256": {p.name: fft.digest(p.read_bytes()) for p in sorted(output.iterdir())},
                }
            )
            if async_save:
                async_records.append({"id": case["id"], "runs": check_async_roundtrips(binary, output)})
        for case in manifest["tones"]:
            request_data = request_for(case)
            request, output = temp / "request.json", temp / case["spec"]["id"]
            fft.write_json(request, request_data)
            directory = core.DEFAULT_FIXTURES / case["spec"]["id"]
            input_path = directory / case["arrays"]["input"]["file"]
            command = candidate.run_command([str(binary), "--fft", str(request), str(input_path), str(output)])
            observed = validate_corpus(read_result(output), request_data, case)
            if fft.digest(input_path.read_bytes()) != case["arrays"]["input"]["sha256"]:
                raise fft.ReferenceError("Candidate changed fixture input")
            precision = "f32" if case["spec"]["dtype"] == "<f4" else "f64"
            comparisons = {}
            for origin in ("theory", "current"):
                comparisons[origin] = {
                    name: fft.compare(
                        observed[name][..., 0] + 1j * observed[name][..., 1]
                        if name == "fft_over_n"
                        else observed[name],
                        fft.read_array(directory, entry),
                        fft.TOLERANCES[precision],
                        f"result {origin}.{name}",
                    )
                    for name in candidate.shapes_for(candidate.request_for(case))
                    if name not in {"frequency_hz", "tone_rms_fs", "asd_fs_sqrt_hz"}
                    for entry in [case["arrays"][f"{origin}.{name}"]]
                }
            factor = np.full(case["spec"]["n"] // 2 + 1, np.sqrt(2.0))
            factor[0] = 1.0
            if case["spec"]["n"] % 2 == 0:
                factor[-1] = 1.0
            comparisons["relations"] = {
                "tone_rms": fft.compare(
                    observed["tone_rms_fs"],
                    observed["peak_fs"] / factor[:, None],
                    fft.TOLERANCES[precision],
                    "tone RMS",
                ),
                "asd_squared": fft.compare(
                    observed["asd_fs_sqrt_hz"] ** 2, observed["psd_fs2_hz"], fft.TOLERANCES[precision], "ASD squared"
                ),
            }
            audit = core.read_json((output / "audit.json").read_bytes())
            if (
                audit["shared_allocation"] is not True
                or audit["fft_evaluations"] != 1
                or audit["roundtrips"] != 2
                or audit["existing_destination_rejected"] is not True
                or audit["after_views"]["nodes"] != 1
                or audit["after_views"]["subscriptions"] != 1
                or any(
                    audit["after_shutdown"][k] != 0
                    for k in ("nodes", "subscriptions", "cache_results", "cache_numeric_bytes", "in_flight")
                )
            ):
                raise fft.ReferenceError("Shared save session/lifetime mismatch")
            corpus.append(
                {
                    "id": case["spec"]["id"],
                    "input_sha256": case["arrays"]["input"]["sha256"],
                    "command": command,
                    "audit": audit,
                    "comparisons": comparisons,
                    "file_sha256": {p.name: fft.digest(p.read_bytes()) for p in sorted(output.iterdir())},
                }
            )
            if async_save:
                async_records.append({"id": case["spec"]["id"], "runs": check_async_roundtrips(binary, output)})
    fft.assert_headless()
    paths = [ROOT / "native" / p for p in ("Cargo.toml", "Cargo.lock", "rust-toolchain.toml")]
    for crate in ("dsp-core", "graph-core"):
        paths += [ROOT / "native" / crate / "Cargo.toml", *sorted((ROOT / "native" / crate).rglob("*.rs"))]
    return {
        "schema_version": 1,
        "task": "MIG-006-E-async-save" if async_save else "MIG-006-E",
        "status": "pass",
        "mode": "portable" if portable else "pinned-reference",
        "environment": fft.environment(),
        "fixture_manifest_sha256": manifest_hash,
        "source_sha256": {str(p.relative_to(ROOT)): fft.digest(p.read_bytes()) for p in paths},
        "runner_sha256": {
            name: fft.digest((ROOT / "scripts" / name).read_bytes())
            for name in (
                "migration_result_candidate.py",
                "migration_graph_candidate.py",
                "migration_fft_candidate.py",
                "migration_core_reference.py",
            )
        },
        "binary_sha256": fft.digest(binary.read_bytes()),
        "build": build_record,
        "contracts": contracts,
        "corpus": corpus,
        "async_saves": async_records,
        "elapsed_seconds": time.perf_counter() - started,
        "limitations": [
            "Experimental versioned exchange, no legacy product importer or automatic settings migration",
            "Basic post-analysis V/FS calibration on input.raw only; SPL, frequency/phase calibration maps and physical device calibration remain unverified",
            "Qt save controls, legacy product compatibility, paired-file transactions and live save-session integration remain unverified",
            "Worker job count is bounded; total retained bytes and encoder scratch memory are not a measured memory budget",
            "Active writes cannot be interrupted; join/Drop must run on a teardown thread, never the GUI or callback",
            "Atomic no-clobber publication requires hard-link support; directory crash durability not evaluated",
            "Not a performance, other-OS or technology-adoption result",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--portable", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--async-save", action="store_true", help="also verify the bounded file worker from both JSON and CSV"
    )
    parser.add_argument("--output", type=Path, help="new directory retaining verified snapshot artifacts")
    args = parser.parse_args()
    try:
        report = verify(portable=args.portable, async_save=args.async_save, output=args.output)
        if args.report:
            fft.write_json(args.report, report)
        print(
            f"PASS: {len(report['contracts'])} calibration contracts, 4 saved exchanges, {len(report['corpus'])} shared FFT results; JSON/CSV exact roundtrips"
        )
        if args.async_save:
            print(
                f"PASS: {sum(len(case['runs']) for case in report['async_saves'])} async save runs, no-clobber/failure/recovery receipts"
            )
    except (fft.ReferenceError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
