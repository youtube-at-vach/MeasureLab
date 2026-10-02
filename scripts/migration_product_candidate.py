"""MIG-006-E-compat: saved native snapshots and real product JSON/CSV exporters.

Headless, NumPy-only evaluation; no devices, GUI, fixture regeneration or adoption decision.
"""

from __future__ import annotations

import argparse
import copy
import itertools
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import migration_product_exchange as product  # noqa: E402
from scripts import migration_result_candidate as result  # noqa: E402

core, fft = result.core, result.fft


def legacy_document():
    """Independent legacy observation, with no invented stream/clock/profile revision."""
    return {
        "version": "1.0",
        "traces": [
            {
                "id": "legacy.alpha",
                "name": '=電圧,"α"\ntrace',
                "source_module": "legacy, module",
                "timestamp": "2026-10-02T09:00:00+09:00",
                "plot_type": "frequency_response",
                "x_axis": {"dimension": "frequency", "base_unit": "Hz", "display_unit": "kHz", "is_log": True},
                "y_axis": {"dimension": "voltage", "base_unit": "V", "display_unit": "dBV", "is_log": False},
                "y2_axis": {"dimension": "phase", "base_unit": "rad", "display_unit": "deg", "is_log": False},
                "x_data": [0.0, 1.0, 2.0],
                "y_data": [-9.0, -3.5, 0.0],
                "y2_data": [-180.0, 0.0, 180.0],
                "calibration": {
                    "is_calibrated": True,
                    "input_sensitivity": 0.125,
                    "applied_offset_db": 2.75,
                    "reference_level": "absolute",
                },
                "metadata": {
                    "nested": {"comment": 'comma, quote" and newline\n', "unknown": None},
                    "gain_applied": True,
                },
            },
            {
                "id": "legacy.beta",
                "name": "@未校正",
                "source_module": "legacy",
                "timestamp": "",
                "plot_type": "spectrum",
                "x_axis": product.axis("frequency", "Hz"),
                "y_axis": product.axis("amplitude", "FS"),
                "y2_axis": None,
                "x_data": [0.5, 1.5],
                "y_data": [0.125, 0.25],
                "y2_data": None,
                "calibration": {
                    "is_calibrated": False,
                    "input_sensitivity": 1.0,
                    "applied_offset_db": 0.0,
                    "reference_level": "relative",
                },
                "metadata": {"note": "coefficient 1 is not calibration evidence"},
            },
        ],
    }


def verify_legacy(output):
    from src.core.export.csv_exporter import CsvTraceExporter
    from src.core.export.json_exporter import JsonTraceExporter
    from src.core.export.trace import ExportTrace

    document = legacy_document()
    traces = [ExportTrace.from_dict(t) for t in document["traces"]]
    output.mkdir()
    path = output / "legacy.json"
    if not JsonTraceExporter().export_traces(str(path), traces, {}):
        raise fft.ReferenceError("Legacy product JSON export failed")
    loaded = product.import_json(product.read_file(path))
    if loaded.document != document or loaded.snapshot is not None or loaded.acquisition != product.UNKNOWN:
        raise fft.ReferenceError("Legacy JSON lost metadata or invented provenance")
    comparisons = []
    for layout, delimiter, headers, metadata, bom in itertools.product(
        ("independent", "merged"), ("comma", "tab"), (False, True), (False, True), (False, True)
    ):
        name = f"{layout}-{delimiter}-{int(headers)}-{int(metadata)}-{int(bom)}.csv"
        spec = product.csv_spec(
            document,
            layout=layout,
            delimiter=delimiter,
            include_headers=headers,
            include_metadata=metadata,
            utf8_bom=bom,
        )
        path = output / name
        if not CsvTraceExporter().export_traces(str(path), traces, spec["options"]):
            raise fft.ReferenceError("Legacy product CSV export failed")
        loaded = product.import_csv(product.read_file(path), spec)
        if loaded.acquisition != product.UNKNOWN or loaded.snapshot is not None:
            raise fft.ReferenceError("Legacy CSV invented acquisition provenance")
        if layout == "independent":
            if loaded.document != document or loaded.sample_relation != "original_trace_arrays":
                raise fft.ReferenceError("Independent legacy CSV did not roundtrip")
        else:
            # Hand-calculated union/interpolations from the two legacy traces above.
            x = [0.0, 0.5, 1.0, 1.5, 2.0]
            expected = copy.deepcopy(document)
            for t in expected["traces"]:
                t["x_data"] = x
            expected["traces"][0]["y_data"] = [-9.0, -6.25, -3.5, -1.75, 0.0]
            expected["traces"][0]["y2_data"] = [-180.0, -90.0, 0.0, 90.0, 180.0]
            expected["traces"][1]["y_data"] = [0.125, 0.125, 0.1875, 0.25, 0.25]
            if loaded.document != expected or loaded.sample_relation != "merged_grid_may_be_interpolated":
                raise fft.ReferenceError("Merged CSV changed its table or claimed original samples")
        comparisons.append({"file": name, "options": spec["options"], "relation": loaded.sample_relation})
    return comparisons


def validate_native_audit(audit, expected, directory):
    """Require terminal receipts and actual files for the submitted snapshot."""
    if (
        set(audit) != {"capacity", "receipts", "snapshot_released_by_worker", "partial_pair_rejected"}
        or type(audit["capacity"]) is not int
        or audit["capacity"] != 2
        or audit["snapshot_released_by_worker"] is not True
        or audit["partial_pair_rejected"] is not True
        or len(audit["receipts"]) != 8
    ):
        raise fft.ReferenceError("Native product worker capacity/ownership inventory mismatch")
    operations = [
        ("product.json", "product_json", "saved", None),
        ("product.csv", "product_csv", "saved", None),
        ("product.json", "product_json", "failed", "AlreadyExists"),
        ("product.csv", "product_csv", "failed", "AlreadyExists"),
        ("absent/product.json", "product_json", "failed", "NotFound"),
        ("orphan.csv", "product_csv", "failed", "AlreadyExists"),
        ("recovered.json", "product_json", "saved", None),
        ("recovered.csv", "product_csv", "saved", None),
    ]
    for index, (receipt, (name, fmt, state, kind)) in enumerate(zip(audit["receipts"], operations, strict=True), 1):
        identity = {
            "operation_id": index,
            "result_id": expected["capture"]["result_id"],
            "generation": expected["source"]["generation"],
            "interval": expected["interval"],
            "destination": str(directory / name),
            "format": fmt,
        }
        status = receipt.get("status", {})
        if (
            set(receipt) != set(identity) | {"status"}
            or any(receipt[k] != v or type(receipt[k]) is not type(v) for k, v in identity.items())
            or any(type(v) is not int for v in receipt["interval"])
            or status.get("state") != state
            or set(status) != ({"state", "kind", "message"} if kind else {"state"})
            or (kind and (status["kind"] != kind or not isinstance(status["message"], str) or not status["message"]))
        ):
            raise fft.ReferenceError("Native product receipt identity or actual completion mismatch")
    if (
        not (directory / "orphan.csv").is_file()
        or (directory / "orphan.csv.metadata.json").read_bytes() != b"existing user sidecar"
        or (directory / "absent").exists()
        or any(p.name.endswith(".tmp") for p in directory.iterdir())
    ):
        raise fft.ReferenceError("Native product partial publication or cleanup mismatch")


def verify_native(binary, codec, expected, source, fmt, directory):
    """Both native-worker -> real product reader and actual exporter -> native reader."""
    command = result.candidate.run_command(
        [str(binary), f"--product-save-{fmt}", str(source / f"result.{fmt}"), str(directory)]
    )
    audit = core.read_json((directory / "audit.json").read_bytes())
    validate_native_audit(audit, expected, directory)
    document = product.projection(expected)
    for name in ("product", "recovered"):
        for imported in (
            product.import_json(product.read_file(directory / f"{name}.json"), codec),
            product.load_csv_pair(directory / f"{name}.csv", codec),
        ):
            if core.json_bytes(imported.snapshot) != core.json_bytes(expected) or imported.document != document:
                raise fft.ReferenceError("Native product writer disagrees with actual ExportTrace schema")
    try:
        product.load_csv_pair(directory / "orphan.csv", codec)
    except (fft.ReferenceError, ValueError):
        pass
    else:
        raise fft.ReferenceError("Partial native product pair was restored")
    actual = directory / "actual-exporter"
    actual.mkdir()
    product.save_json(actual / "product.json", document)
    product.save_csv_pair(actual / "product.csv", document)
    reads = []
    for file_fmt in ("json", "csv"):
        target = actual / f"native-read-{file_fmt}"
        reads.append(
            result.candidate.run_command(
                [str(binary), f"--product-read-{file_fmt}", str(actual / f"product.{file_fmt}"), str(target)]
            )
        )
        if core.json_bytes(result.read_result(target)) != core.json_bytes(expected):
            raise fft.ReferenceError("Actual exporter to native reader changed the complete snapshot")
    return {"save_command": command, "read_commands": reads, "audit": audit, "exact_cross_language_roundtrips": 6}


def verify(*, output, portable=False, native_product=False):
    started = time.perf_counter()
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    try:
        reference = result.verify(portable=portable, output=output / "snapshots")
        fft.write_json(output / "snapshot-report.json", reference)
        binary, build = result.build()
        codec = product.NativeCodec(binary)
        runs = []
        for case in reference["contracts"] + reference["corpus"]:
            source = output / "snapshots" / case["id"]
            expected = result.read_result(source)
            for fmt in ("json", "csv"):
                directory = output / f"{case['id']}-from-{fmt}"
                directory.mkdir()
                input_path = source / f"result.{fmt}"
                original = fft.digest(input_path.read_bytes())
                validated = codec.decode(product.read_file(input_path), fmt)
                if core.json_bytes(validated) != core.json_bytes(expected):
                    raise fft.ReferenceError("Native snapshot input changed")
                document = product.projection(validated)
                json_path, csv_path = directory / "product.json", directory / "product.csv"
                product.save_json(json_path, document)
                product.save_csv_pair(csv_path, document)
                for imported in (
                    product.import_json(product.read_file(json_path), codec),
                    product.load_csv_pair(csv_path, codec),
                ):
                    if core.json_bytes(imported.snapshot) != core.json_bytes(expected) or imported.document != document:
                        raise fft.ReferenceError("Compatibility roundtrip changed arrays/calibration/provenance")
                before = {p.name: fft.digest(p.read_bytes()) for p in directory.iterdir()}
                for save, destination in (
                    (product.save_json, json_path),
                    (product.save_csv_pair, csv_path),
                ):
                    try:
                        save(destination, document)
                    except FileExistsError:
                        pass
                    else:
                        raise fft.ReferenceError("Compatibility export replaced a destination")
                if before != {
                    p.name: fft.digest(p.read_bytes()) for p in directory.iterdir()
                } or original != fft.digest(input_path.read_bytes()):
                    raise fft.ReferenceError("Compatibility export modified existing files/input")
                native = (
                    verify_native(binary, codec, expected, source, fmt, directory / "native-worker")
                    if native_product
                    else None
                )
                if original != fft.digest(input_path.read_bytes()):
                    raise fft.ReferenceError("Native product worker modified its snapshot input")
                runs.append(
                    {
                        "id": case["id"],
                        "input_format": fmt,
                        "input_sha256": original,
                        "trace_count": len(document["traces"]),
                        "omitted": document["traces"][0]["metadata"][product.MARKER]["omitted"],
                        "file_sha256": before,
                        "exact_snapshot_roundtrips": 2,
                        "existing_files_preserved": True,
                        **({"native": native} if native_product else {}),
                    }
                )
        legacy = verify_legacy(output / "legacy")
        fft.assert_headless()
        files = [
            ROOT / "scripts" / name
            for name in (
                "migration_product_candidate.py",
                "migration_product_exchange.py",
                "migration_result_candidate.py",
            )
        ]
        files += list((ROOT / "src/core/export").glob("*.py"))
        files += [ROOT / "src/core/localization.py", ROOT / "src/core/utils.py"]
        report = {
            "schema_version": 1,
            "task": "MIG-006-E-native-product" if native_product else "MIG-006-E-compat",
            "status": "pass",
            "mode": "portable" if portable else "pinned-reference",
            "environment": fft.environment(),
            "source_sha256": {str(p.relative_to(ROOT)): fft.digest(p.read_bytes()) for p in files},
            "native_binary_sha256": fft.digest(binary.read_bytes()),
            "native_source_sha256": reference["source_sha256"],
            "build": build,
            "snapshot_report_sha256": fft.digest((output / "snapshot-report.json").read_bytes()),
            "native_validation_commands": codec.commands,
            "runs": runs,
            "legacy_csv": legacy,
            "artifact_sha256": {
                str(p.relative_to(output)): fft.digest(p.read_bytes()) for p in sorted(output.rglob("*")) if p.is_file()
            },
            "elapsed_seconds": time.perf_counter() - started,
            "limitations": [
                "Native product snapshot codec/worker evaluated; Qt product format and live save integration remain pending"
                if native_product
                else "Python evaluation adapter only; native product codec and Qt product format integration remain pending",
                "Product JSON 1.0 remains unchanged; an experimental reserved carrier metadata envelope retains the snapshot",
                "Null projections are explicitly omitted from legacy display arrays; all values/reasons remain in the retained snapshot",
                "CSV requires explicit descriptors; merged tables may contain interpolated samples and do not restore the original grid",
                "CSV and metadata sidecar publish independently; failure can leave an orphan CSV; no pair transaction",
                "Historical nonfinite/ambiguous files are rejected; no automatic settings or calibration profile activation on restart",
                "Hard-link publication requires filesystem support; no crash-durability, performance, other-OS or adoption result",
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
    parser.add_argument("--native-product", action="store_true", help="also compare native product codec/file worker")
    args = parser.parse_args()
    try:
        report = verify(output=args.output, portable=args.portable, native_product=args.native_product)
        print(
            f"PASS: {len(report['runs'])} compatibility runs, 24 exact snapshot roundtrips, legacy JSON and {len(report['legacy_csv'])} CSV modes"
        )
        if args.native_product:
            print("PASS: native product worker, 72 exact cross-language roundtrips, 48 saved/48 failed receipts")
    except (fft.ReferenceError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
