"""Actual product formats, explicit CSV losses and native snapshot corruption rejection."""

import copy
import itertools
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import migration_product_candidate as runner
from scripts import migration_product_exchange as product
from scripts import migration_result_candidate as result
from src.core.export.csv_exporter import CsvTraceExporter
from src.core.export.json_exporter import JsonTraceExporter
from src.core.export.trace import ExportTrace


def legacy():
    return runner.legacy_document()


def test_actual_legacy_json_preserves_axes_calibration_metadata_and_unknown(tmp_path):
    document = legacy()
    path = tmp_path / "old.json"
    assert JsonTraceExporter().export_traces(str(path), [ExportTrace.from_dict(t) for t in document["traces"]], {})
    loaded = product.import_json(path.read_bytes())
    assert loaded.document == document
    assert loaded.snapshot is None
    assert loaded.acquisition == product.UNKNOWN
    assert all(v is None for v in loaded.acquisition.values())
    assert loaded.document["traces"][1]["calibration"]["is_calibrated"] is False
    output = tmp_path / "again.json"
    product.save_json(output, loaded.document)
    assert product.import_json(output.read_bytes()).document == document


@pytest.mark.parametrize(
    "layout,delimiter,headers,metadata,bom",
    list(itertools.product(("independent", "merged"), ("comma", "tab"), (False, True), (False, True), (False, True))),
)
def test_actual_csv_modes_keep_values_without_reapplying_calibration(
    tmp_path, layout, delimiter, headers, metadata, bom
):
    document = legacy()
    spec = product.csv_spec(
        document, layout=layout, delimiter=delimiter, include_headers=headers, include_metadata=metadata, utf8_bom=bom
    )
    path = tmp_path / "old.csv"
    assert CsvTraceExporter().export_traces(
        str(path), [ExportTrace.from_dict(t) for t in document["traces"]], spec["options"]
    )
    loaded = product.import_csv(path.read_bytes(), spec)
    assert loaded.snapshot is None and loaded.acquisition == product.UNKNOWN
    for original, t in zip(document["traces"], loaded.document["traces"], strict=True):
        for key in ("x_axis", "y_axis", "y2_axis", "calibration", "metadata", "name", "timestamp"):
            assert original[key] == t[key]
    if layout == "independent":
        assert loaded.document == document
        assert loaded.sample_relation == "original_trace_arrays"
    else:
        assert loaded.sample_relation == "merged_grid_may_be_interpolated"
        assert loaded.document["traces"][0]["x_data"] == [0.0, 0.5, 1.0, 1.5, 2.0]
        assert loaded.document["traces"][0]["y_data"] == [-9.0, -6.25, -3.5, -1.75, 0.0]
        assert loaded.document["traces"][1]["y_data"] == [0.125, 0.125, 0.1875, 0.25, 0.25]


@pytest.mark.parametrize(
    "fault",
    [
        "version",
        "unknown_field",
        "duplicate_id",
        "shape",
        "secondary",
        "bool_numeric",
        "large_integer",
        "nonfinite",
        "metadata_nonfinite",
        "calibration_bool",
        "coefficient",
        "offset",
        "axis",
    ],
)
def test_legacy_json_rejects_ambiguous_or_invalid_values(fault):
    doc = legacy()
    t = doc["traces"][0]
    if fault == "version":
        doc["version"] = "2.0"
    elif fault == "unknown_field":
        t["imaginary_field"] = 0
    elif fault == "duplicate_id":
        doc["traces"][1]["id"] = t["id"]
    elif fault == "shape":
        t["y_data"].pop()
    elif fault == "secondary":
        t["y2_axis"] = None
    elif fault == "bool_numeric":
        t["y_data"][0] = True
    elif fault == "large_integer":
        t["y_data"][0] = 2**53 + 1
    elif fault == "nonfinite":
        t["y_data"][0] = float("nan")
    elif fault == "metadata_nonfinite":
        t["metadata"]["bad"] = float("inf")
    elif fault == "calibration_bool":
        t["calibration"]["is_calibrated"] = "false"
    elif fault == "coefficient":
        t["calibration"]["input_sensitivity"] = 0
    elif fault == "offset":
        t["calibration"]["applied_offset_db"] = "0"
    elif fault == "axis":
        t["x_axis"]["is_log"] = 1
    with pytest.raises((result.fft.ReferenceError, ValueError)):
        product.import_json(json.dumps(doc).encode())


def test_legacy_duplicate_json_keys_and_truncation_are_rejected():
    payload = json.dumps(legacy()).encode()
    for bad in (payload[:-1], payload.replace(b'"version": "1.0"', b'"version": "1.0", "version": "1.0"')):
        with pytest.raises((result.fft.ReferenceError, ValueError)):
            product.import_json(bad)


@pytest.mark.parametrize(
    "fault", ["width", "nan", "missing", "interior_padding", "header", "metadata", "options", "descriptor"]
)
def test_csv_corruption_and_missing_descriptors_rejected(tmp_path, fault):
    doc = legacy()
    spec = product.csv_spec(doc, include_headers=False, include_metadata=False)
    payload = b"0,-9,-180,0.5,0.125\r\n1,-3.5,0,1.5,0.25\r\n2,0,180,,\r\n"
    if fault == "width":
        payload = payload.replace(b"0,-9,-180", b"0,-9")
    elif fault == "nan":
        payload = payload.replace(b"-9", b"NaN")
    elif fault == "missing":
        payload = payload.replace(b"-9", b"")
    elif fault == "interior_padding":
        payload = payload.replace(b"0.5,0.125", b",")
    elif fault == "header":
        spec["options"]["include_headers"] = True
        payload = b"x,y\n" + payload
    elif fault == "metadata":
        spec["options"]["include_metadata"] = True
    elif fault == "options":
        spec["options"]["include_headers"] = "false"
    elif fault == "descriptor":
        del spec["descriptors"][0]["calibration"]
    with pytest.raises((result.fft.ReferenceError, ValueError)):
        product.import_csv(payload, spec)


def test_csv_sidecar_digest_missing_and_pair_partial_failure(tmp_path):
    path = tmp_path / "old.csv"
    sidecar = product.save_csv_pair(path, legacy())
    assert product.load_csv_pair(path).document == legacy()
    original = sidecar.read_bytes()
    sidecar.unlink()
    with pytest.raises(OSError):
        product.load_csv_pair(path)
    sidecar.write_bytes(original)
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(result.fft.ReferenceError, match="sidecar"):
        product.load_csv_pair(path)
    partial = tmp_path / "partial.csv"
    Path(str(partial) + ".metadata.json").write_text("occupied")
    with pytest.raises(FileExistsError):
        product.save_csv_pair(partial, legacy())
    assert partial.exists()  # Explicitly not a two-file transaction.
    assert Path(str(partial) + ".metadata.json").read_text() == "occupied"
    with pytest.raises((ValueError, result.fft.ReferenceError)):
        product.load_csv_pair(partial)
    assert not list(tmp_path.glob(".migration-product-*.tmp"))


def test_failed_export_does_not_publish_and_recovers(tmp_path, monkeypatch):
    original = JsonTraceExporter.export_traces
    monkeypatch.setattr(JsonTraceExporter, "export_traces", lambda *args: False)
    path = tmp_path / "failed.json"
    with pytest.raises(OSError, match="exporter failed"):
        product.save_json(path, legacy())
    assert not path.exists() and not list(tmp_path.glob("*.tmp"))
    monkeypatch.setattr(JsonTraceExporter, "export_traces", original)
    product.save_json(path, legacy())
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        product.save_json(path, legacy())
    assert path.read_bytes() == before
    with pytest.raises(FileNotFoundError):
        product.save_json(tmp_path / "absent/out.json", legacy())


@pytest.fixture(scope="module")
def native_codec():
    binary, _ = result.build()
    return product.NativeCodec(binary)


@pytest.fixture(scope="module")
def native_snapshot(native_codec, tmp_path_factory):
    directory = tmp_path_factory.mktemp("product-native")
    scenarios = result.core.read_json((result.core.DEFAULT_FIXTURES / "scenarios.json").read_bytes())
    case = next(c for c in scenarios if c["operation"] == "calibration")
    request = directory / "request.json"
    result.fft.write_json(request, {"schema_version": 1, "input": case["input"]})
    result.candidate.run_command([str(native_codec.binary), "--tone", str(request), str(directory / "result")])
    return result.read_result(directory / "result")


@pytest.mark.native
def test_nulls_keep_reasons_in_snapshot_without_zero_or_nan_projection(native_codec, native_snapshot, tmp_path):
    snapshot = copy.deepcopy(native_snapshot)
    for name in ("peak_fs", "rms_fs", "rms_v", "dbv"):
        snapshot["columns"][name]["values"][0] = None
        snapshot["columns"][name]["reasons"][0] = "nonfinite"
    snapshot = native_codec.decode(result.core.json_bytes(snapshot))
    document = product.projection(snapshot)
    envelope = document["traces"][0]["metadata"][product.MARKER]
    assert {item["metric"] for item in envelope["omitted"]} >= {"peak_fs", "rms_fs", "spl"}
    assert all(product.finite(v) for t in document["traces"] for v in t["y_data"])
    path = tmp_path / "invalid-observations.json"
    product.save_json(path, document)
    assert product.import_json(path.read_bytes(), native_codec).snapshot == snapshot
    assert product.import_json(path.read_bytes(), native_codec).snapshot["columns"]["peak_fs"]["values"][0] is None


@pytest.mark.native
@pytest.mark.parametrize(
    "fault",
    [
        "envelope",
        "snapshot_shape",
        "projection_value",
        "projection_unit",
        "carrier_position",
        "duplicate_carrier",
        "omitted",
        "snapshot_calibration",
    ],
)
def test_product_snapshot_corruption_fails_native_and_projection_validation(native_codec, native_snapshot, fault):
    document = product.projection(native_snapshot)
    envelope = document["traces"][0]["metadata"][product.MARKER]
    if fault == "envelope":
        envelope["version"] = 2
    elif fault == "snapshot_shape":
        envelope["snapshot"]["columns"]["rms_fs"]["shape"] = [1]
    elif fault == "projection_value":
        document["traces"][1]["y_data"][0] += 1
    elif fault == "projection_unit":
        document["traces"][1]["y_axis"]["display_unit"] = "V"
    elif fault == "carrier_position":
        document["traces"].reverse()
    elif fault == "duplicate_carrier":
        document["traces"][1]["metadata"][product.MARKER] = copy.deepcopy(envelope)
    elif fault == "omitted":
        envelope["omitted"].clear()
    elif fault == "snapshot_calibration":
        envelope["snapshot"]["calibration"][0]["profile"]["v_per_fs"] = 0
    with pytest.raises(result.fft.ReferenceError):
        product.import_json(result.core.json_bytes(document), native_codec)


@pytest.mark.native
def test_native_validator_required_and_old_snapshot_unaffected(native_codec, native_snapshot):
    original = copy.deepcopy(native_snapshot)
    document = product.projection(native_snapshot)
    with pytest.raises(result.fft.ReferenceError, match="native validation"):
        product.import_json(result.core.json_bytes(document))
    document["traces"][0]["metadata"][product.MARKER]["snapshot"]["source"]["generation"] += 1
    assert native_snapshot == original


@pytest.mark.native
def test_complete_corpus_headless_product_roundtrips(tmp_path):
    output = tmp_path / "complete"
    completed = subprocess.run(  # noqa: S603 - fixed local runner, explicit argv
        [
            sys.executable,
            str(runner.ROOT / "scripts/migration_product_candidate.py"),
            "--portable",
            "--native-product",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = result.core.read_json((output / "report.json").read_bytes())
    assert report["status"] == "pass"
    assert len(report["runs"]) == 12 and len(report["legacy_csv"]) == 32
    assert sum(run["exact_snapshot_roundtrips"] for run in report["runs"]) == 24
    for run in report["runs"]:
        assert run["existing_files_preserved"]
    assert report["native_binary_sha256"]
    assert report["task"] == "MIG-006-E-native-product"
    assert sum(run["native"]["exact_cross_language_roundtrips"] for run in report["runs"]) == 72
    receipts = [receipt for run in report["runs"] for receipt in run["native"]["audit"]["receipts"]]
    assert sum(r["status"]["state"] == "saved" for r in receipts) == 48
    assert sum(r["status"]["state"] == "failed" for r in receipts) == 48


@pytest.mark.native
@pytest.mark.parametrize(
    "delimiter,headers,metadata,bom", list(itertools.product(("comma", "tab"), *[(False, True)] * 3))
)
def test_actual_independent_csv_option_sets_restore_with_native_product_reader(
    native_codec, native_snapshot, tmp_path, delimiter, headers, metadata, bom
):
    import hashlib

    document = product.projection(native_snapshot)
    spec = product.csv_spec(
        document, delimiter=delimiter, include_headers=headers, include_metadata=metadata, utf8_bom=bom
    )
    path = tmp_path / "actual.csv"
    assert CsvTraceExporter().export_traces(
        str(path), [ExportTrace.from_dict(t) for t in document["traces"]], spec["options"]
    )
    sidecar = {
        "schema_version": 1,
        "kind": product.CSV_KIND,
        "csv_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        **spec,
    }
    Path(str(path) + ".metadata.json").write_bytes(result.core.json_bytes(sidecar))
    output = tmp_path / "native"
    result.candidate.run_command([str(native_codec.binary), "--product-read-csv", str(path), str(output)])
    assert result.read_result(output) == native_snapshot


@pytest.mark.native
@pytest.mark.parametrize("fault", ["projection", "carrier", "duplicate_key", "large_integer", "nonfinite", "legacy"])
def test_native_product_json_reader_rejects_modified_or_unknown_results(native_codec, native_snapshot, tmp_path, fault):
    document = product.projection(native_snapshot)
    if fault == "projection":
        document["traces"][1]["y_data"][0] += 1
    elif fault == "carrier":
        document["traces"][0]["metadata"][product.MARKER]["snapshot"]["source"]["tap"] = "OutputMixed"
    elif fault == "large_integer":
        document["traces"][1]["y_data"][0] = 2**53 + 1
    elif fault == "nonfinite":
        document["traces"][1]["y_data"][0] = float("nan")
    elif fault == "legacy":
        document = legacy()
    payload = json.dumps(document)
    if fault == "duplicate_key":
        payload = payload.replace('"version": "1.0"', '"version": "1.0", "version": "1.0"', 1)
    path = tmp_path / "modified.json"
    path.write_text(payload)
    with pytest.raises(result.fft.ReferenceError):
        result.candidate.run_command(
            [str(native_codec.binary), "--product-read-json", str(path), str(tmp_path / "native")]
        )


@pytest.mark.parametrize(
    "fault",
    [
        "capacity",
        "generation",
        "interval_bool",
        "format",
        "pending",
        "partial_saved",
        "missing_receipt",
        "orphan",
        "temporary",
    ],
)
def test_native_product_receipt_audit_rejects_false_completion(tmp_path, fault):
    expected = {"capture": {"result_id": "old-result"}, "source": {"generation": 7}, "interval": [0, 8]}
    specs = [
        ("product.json", "product_json", None),
        ("product.csv", "product_csv", None),
        ("product.json", "product_json", "AlreadyExists"),
        ("product.csv", "product_csv", "AlreadyExists"),
        ("absent/product.json", "product_json", "NotFound"),
        ("orphan.csv", "product_csv", "AlreadyExists"),
        ("recovered.json", "product_json", None),
        ("recovered.csv", "product_csv", None),
    ]
    audit = {"capacity": 2, "snapshot_released_by_worker": True, "partial_pair_rejected": True, "receipts": []}
    for i, (name, fmt, kind) in enumerate(specs, 1):
        audit["receipts"].append(
            {
                "operation_id": i,
                "result_id": "old-result",
                "generation": 7,
                "interval": [0, 8],
                "destination": str(tmp_path / name),
                "format": fmt,
                "status": {"state": "failed", "kind": kind, "message": "expected I/O failure"}
                if kind
                else {"state": "saved"},
            }
        )
    (tmp_path / "orphan.csv").write_bytes(b"partial CSV")
    (tmp_path / "orphan.csv.metadata.json").write_bytes(b"existing user sidecar")
    runner.validate_native_audit(audit, expected, tmp_path)
    receipt = audit["receipts"][0]
    if fault == "capacity":
        audit["capacity"] = True
    elif fault == "generation":
        receipt["generation"] += 1
    elif fault == "interval_bool":
        receipt["interval"][0] = False
    elif fault == "format":
        receipt["format"] = "json"
    elif fault == "pending":
        receipt["status"] = {"state": "writing"}
    elif fault == "partial_saved":
        audit["receipts"][5]["status"] = {"state": "saved"}
    elif fault == "missing_receipt":
        audit["receipts"].pop()
    elif fault == "orphan":
        (tmp_path / "orphan.csv.metadata.json").write_bytes(b"replaced user's metadata")
    else:
        (tmp_path / "partial.tmp").write_bytes(b"partial")
    with pytest.raises(result.fft.ReferenceError):
        runner.validate_native_audit(audit, expected, tmp_path)
