"""MIG-006-E-native-import: native legacy observations and validated snapshots.

Use actual product exporters, the independent Python reader and saved numeric
oracles. No Qt, device, fixture regeneration or acquisition-setting mutation.
"""

from __future__ import annotations

import argparse
import copy
import itertools
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import migration_product_candidate as compatibility  # noqa: E402
from scripts import migration_product_exchange as product  # noqa: E402
from scripts import migration_result_candidate as result  # noqa: E402

core, fft = result.core, result.fft


def imported_value(imported):
    return {
        "document": imported.document,
        "snapshot": imported.snapshot,
        "acquisition": imported.acquisition,
        "sample_relation": imported.sample_relation,
    }


def native_import(binary, path, output, *, fmt="json", spec=None):
    input_paths = [path]
    if spec is not None:
        input_paths.append(spec)
    elif fmt == "csv":
        input_paths.append(Path(str(path) + ".metadata.json"))
    input_hashes = {str(p): fft.digest(p.read_bytes()) for p in input_paths}
    command = [str(binary), f"--product-import-{fmt}", str(path)]
    if spec is not None:
        command[1] = "--product-import-csv-spec"
        command.append(str(spec))
    command.append(str(output))
    record = result.candidate.run_command(command)
    loaded = core.read_json((output / "imported.json").read_bytes())
    audit = core.read_json((output / "audit.json").read_bytes())
    if audit != {"product_import_validated": True, "has_snapshot": loaded["snapshot"] is not None}:
        raise fft.ReferenceError("Native import reported an unvalidated outcome")
    if any(fft.digest(Path(p).read_bytes()) != digest for p, digest in input_hashes.items()):
        raise fft.ReferenceError("Native import modified a source file/descriptor")
    record["input_sha256"] = input_hashes
    return loaded, record


def compare_import(loaded, expected):
    if core.json_bytes(loaded) != core.json_bytes(imported_value(expected)):
        raise fft.ReferenceError("Native import changed values/axes/calibration/metadata or invented acquisition")


def verify_legacy(binary, output):
    from src.core.export.csv_exporter import CsvTraceExporter
    from src.core.export.trace import ExportTrace

    output.mkdir()
    document = compatibility.legacy_document()
    traces = [ExportTrace.from_dict(t) for t in document["traces"]]
    path = output / "legacy.json"
    product.save_json(path, document)
    expected = product.import_json(product.read_file(path))
    loaded, record = native_import(binary, path, output / "native-json")
    compare_import(loaded, expected)
    json_record = {"command": record, "file_sha256": fft.digest(path.read_bytes())}
    csv_records = []
    for layout, delimiter, headers, metadata, bom in itertools.product(
        ("independent", "merged"), ("comma", "tab"), (False, True), (False, True), (False, True)
    ):
        name = f"{layout}-{delimiter}-{int(headers)}-{int(metadata)}-{int(bom)}"
        spec = product.csv_spec(
            document,
            layout=layout,
            delimiter=delimiter,
            include_headers=headers,
            include_metadata=metadata,
            utf8_bom=bom,
        )
        path, spec_path = output / f"{name}.csv", output / f"{name}.spec.json"
        fft.write_json(spec_path, spec)
        if not CsvTraceExporter().export_traces(str(path), traces, spec["options"]):
            raise fft.ReferenceError("Actual legacy CSV export failed")
        expected = product.import_csv(product.read_file(path), spec)
        hand = copy.deepcopy(document)
        if layout == "merged":
            for trace in hand["traces"]:
                trace["x_data"] = [0.0, 0.5, 1.0, 1.5, 2.0]
            hand["traces"][0]["y_data"] = [-9.0, -6.25, -3.5, -1.75, 0.0]
            hand["traces"][0]["y2_data"] = [-180.0, -90.0, 0.0, 90.0, 180.0]
            hand["traces"][1]["y_data"] = [0.125, 0.125, 0.1875, 0.25, 0.25]
        if expected.document != hand or expected.acquisition != product.UNKNOWN or expected.snapshot is not None:
            raise fft.ReferenceError("Independent legacy oracle/provenance mismatch")
        loaded, record = native_import(binary, path, output / f"native-{name}", fmt="csv", spec=spec_path)
        compare_import(loaded, expected)
        csv_records.append(
            {"options": spec["options"], "command": record, "sample_relation": loaded["sample_relation"]}
        )
    pair = output / "legacy-pair.csv"
    product.save_csv_pair(pair, document)
    loaded, pair_record = native_import(binary, pair, output / "native-pair", fmt="csv")
    compare_import(loaded, product.load_csv_pair(pair))
    return {"json": json_record, "csv": csv_records, "pair_command": pair_record}


def verify(*, output, portable=False):
    started = time.perf_counter()
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    try:
        source_paths = [
            ROOT / "scripts" / name
            for name in (
                "migration_product_import_candidate.py",
                "migration_product_candidate.py",
                "migration_product_exchange.py",
                "migration_result_candidate.py",
                "migration_graph_candidate.py",
                "migration_fft_candidate.py",
                "migration_fft_reference.py",
                "migration_core_reference.py",
            )
        ]
        source_paths += list((ROOT / "src/core/export").glob("*.py"))
        source_paths += [ROOT / "src/core/localization.py", ROOT / "src/core/utils.py"]
        source_paths += [ROOT / "native" / name for name in ("Cargo.toml", "Cargo.lock", "rust-toolchain.toml")]
        for crate in ("graph-core", "dsp-core", "audio-core"):
            source_paths += [ROOT / "native" / crate / "Cargo.toml", *sorted((ROOT / "native" / crate).rglob("*.rs"))]
        sources = {str(p.relative_to(ROOT)): fft.digest(p.read_bytes()) for p in source_paths}
        reference = result.verify(portable=portable, output=output / "snapshots")
        fft.write_json(output / "snapshot-report.json", reference)
        binary, build = result.build()
        # Freeze the executable before other test/build commands can replace it.
        (output / "binaries").mkdir()
        fixed = output / "binaries" / binary.name
        shutil.copy2(binary, fixed)
        binary_hash = fft.digest(fixed.read_bytes())
        codec = product.NativeCodec(fixed)
        legacy = verify_legacy(fixed, output / "legacy")
        runs = []
        inputs = {}
        for case in reference["contracts"] + reference["corpus"]:
            source = output / "snapshots" / case["id"]
            expected = result.read_result(source)
            document = product.projection(expected)
            directory = output / case["id"]
            directory.mkdir()
            path_json, path_csv = directory / "product.json", directory / "product.csv"
            product.save_json(path_json, document)
            product.save_csv_pair(path_csv, document)
            spec_path = directory / "csv.spec.json"
            fft.write_json(spec_path, product.csv_spec(document))
            before = {str(p): fft.digest(p.read_bytes()) for p in directory.iterdir()}
            commands = []
            for fmt, spec in (("json", None), ("csv", None), ("csv", spec_path)):
                path = path_json if fmt == "json" else path_csv
                target = directory / ("native-csv-spec" if spec is not None else f"native-{fmt}")
                loaded, command = native_import(fixed, path, target, fmt=fmt, spec=spec)
                python = (
                    product.import_json(product.read_file(path), codec)
                    if fmt == "json"
                    else product.load_csv_pair(path, codec)
                )
                compare_import(loaded, python)
                if core.json_bytes(loaded["snapshot"]) != core.json_bytes(expected):
                    raise fft.ReferenceError("Native import changed full numeric/provenance snapshot")
                commands.append(command)
            if any(fft.digest(Path(p).read_bytes()) != digest for p, digest in before.items()):
                raise fft.ReferenceError("Native import modified a source product file")
            inputs.update(before)
            runs.append({"id": case["id"], "commands": commands, "exact_snapshot_imports": 3})
        if any(fft.digest((ROOT / p).read_bytes()) != digest for p, digest in sources.items()):
            raise fft.ReferenceError("Source changed during import verification")
        if fft.digest(fixed.read_bytes()) != binary_hash:
            raise fft.ReferenceError("Frozen candidate binary changed during verification")
        fft.assert_headless()
        report = {
            "schema_version": 1,
            "task": "MIG-006-E-native-import",
            "status": "pass",
            "mode": "portable" if portable else "pinned-reference",
            "environment": fft.environment(),
            "build": build,
            "binary_sha256": fft.digest(fixed.read_bytes()),
            "source_sha256": sources,
            "fixture_manifest_sha256": reference["fixture_manifest_sha256"],
            "snapshot_report_sha256": fft.digest((output / "snapshot-report.json").read_bytes()),
            "input_sha256": inputs,
            "runs": runs,
            "legacy": legacy,
            "native_validation_commands": codec.commands,
            "artifact_sha256": {
                str(p.relative_to(output)): fft.digest(p.read_bytes()) for p in sorted(output.rglob("*")) if p.is_file()
            },
            "elapsed_seconds": time.perf_counter() - started,
            "limitations": [
                "Synchronous file-worker API; Qt import delivery, cancellation and shutdown remain pending",
                "CSV descriptors/options are explicit; merged tables do not restore original samples or complete snapshots",
                "Legacy acquisition provenance remains null; imported result profiles never activate acquisition settings",
                "Each file <=256 MiB, <=1024 traces and <=4,000,000 numeric scalars; no process RSS/byte budget",
                "Integer JSON tokens outside signed/unsigned 64-bit are rejected before serde can round them; no bigint metadata support",
                "Paired-file transactions, live/save-load performance, other OS and adoption remain unverified",
            ],
        }
        fft.write_json(output / "report.json", report)
        return report
    except Exception as error:
        fft.write_json(
            output / "failure.json",
            {"status": "failed", "error": str(error), "elapsed_seconds": time.perf_counter() - started},
        )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new directory for all evidence")
    parser.add_argument("--portable", action="store_true")
    args = parser.parse_args()
    try:
        report = verify(output=args.output, portable=args.portable)
        print(
            f"PASS: legacy JSON/pair and {len(report['legacy']['csv'])} CSV modes; {len(report['runs']) * 3} exact native snapshot imports"
        )
    except (fft.ReferenceError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
