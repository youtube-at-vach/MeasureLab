"""Cross-language product import and failure without invented provenance."""

import copy
import itertools
import json
from pathlib import Path
import subprocess

import pytest

from scripts import migration_product_import_candidate as runner
from scripts import migration_product_exchange as product
from scripts import migration_result_candidate as result
from src.core.export.csv_exporter import CsvTraceExporter
from src.core.export.trace import ExportTrace

pytestmark = pytest.mark.native


@pytest.fixture(scope="module")
def binary():
    return result.build()[0]


@pytest.fixture(scope="module")
def snapshot(binary, tmp_path_factory):
    directory = tmp_path_factory.mktemp("import-snapshot")
    cases = result.core.read_json((result.core.DEFAULT_FIXTURES / "scenarios.json").read_bytes())
    case = next(c for c in cases if c["operation"] == "calibration")
    request = directory / "request.json"
    result.fft.write_json(request, {"schema_version": 1, "input": case["input"]})
    result.candidate.run_command([str(binary), "--tone", str(request), str(directory / "result")])
    return result.read_result(directory / "result")


def rejected(binary, path, output, *, spec=None, fmt="json"):
    command = [str(binary), f"--product-import-{fmt}", str(path)]
    if spec is not None:
        command[1] = "--product-import-csv-spec"
        command.append(str(spec))
    command.append(str(output))
    original = path.read_bytes()
    observed = subprocess.run(command, capture_output=True, check=False)  # noqa: S603 - fixed local candidate
    assert observed.returncode != 0 and observed.stderr
    assert not output.exists()
    assert path.read_bytes() == original


def test_legacy_json_and_sidecar_preserve_metadata_and_have_no_result(binary, tmp_path):
    document = runner.compatibility.legacy_document()
    path = tmp_path / "old.json"
    product.save_json(path, document)
    loaded, _ = runner.native_import(binary, path, tmp_path / "native-json")
    runner.compare_import(loaded, product.import_json(path.read_bytes()))
    assert loaded["snapshot"] is None and loaded["acquisition"] == product.UNKNOWN
    assert loaded["document"]["traces"][1]["calibration"]["is_calibrated"] is False
    csv = tmp_path / "old.csv"
    product.save_csv_pair(csv, document)
    loaded, _ = runner.native_import(binary, csv, tmp_path / "native-pair", fmt="csv")
    runner.compare_import(loaded, product.load_csv_pair(csv))


@pytest.mark.parametrize(
    "layout,delimiter,headers,metadata,bom",
    list(itertools.product(("independent", "merged"), ("comma", "tab"), (False, True), (False, True), (False, True))),
)
def test_actual_csv_options_match_independent_python_reader(
    binary, tmp_path, layout, delimiter, headers, metadata, bom
):
    document = runner.compatibility.legacy_document()
    spec = product.csv_spec(
        document, layout=layout, delimiter=delimiter, include_headers=headers, include_metadata=metadata, utf8_bom=bom
    )
    path, descriptor = tmp_path / "old.csv", tmp_path / "spec.json"
    result.fft.write_json(descriptor, spec)
    assert CsvTraceExporter().export_traces(
        str(path), [ExportTrace.from_dict(t) for t in document["traces"]], spec["options"]
    )
    loaded, _ = runner.native_import(binary, path, tmp_path / "native", fmt="csv", spec=descriptor)
    runner.compare_import(loaded, product.import_csv(path.read_bytes(), spec))
    assert loaded["snapshot"] is None and loaded["acquisition"] == product.UNKNOWN
    if layout == "merged":
        assert loaded["sample_relation"] == "merged_grid_may_be_interpolated"
        assert loaded["document"]["traces"][0]["y_data"] == [-9.0, -6.25, -3.5, -1.75, 0.0]
    else:
        assert loaded["document"] == document


@pytest.mark.parametrize(
    "fault",
    [
        "version",
        "duplicate_id",
        "empty_id",
        "shape",
        "secondary",
        "missing_secondary",
        "bool_numeric",
        "large_integer",
        "beyond_u64",
        "metadata_beyond_u64",
        "nonfinite",
        "metadata_nonfinite",
        "calibration_bool",
        "coefficient",
        "offset",
        "axis",
        "field",
        "duplicate_key",
        "truncated",
        "reserved_carrier",
    ],
)
def test_legacy_import_rejects_corrupt_or_ambiguous_json_without_output(binary, tmp_path, fault):
    document = runner.compatibility.legacy_document()
    t = document["traces"][0]
    if fault == "version":
        document["version"] = "2.0"
    elif fault == "duplicate_id":
        document["traces"][1]["id"] = t["id"]
    elif fault == "empty_id":
        t["id"] = ""
    elif fault == "shape":
        t["y_data"].pop()
    elif fault == "secondary":
        t["y2_axis"] = None
    elif fault == "missing_secondary":
        del t["y2_data"]
    elif fault == "bool_numeric":
        t["y_data"][0] = True
    elif fault == "large_integer":
        t["y_data"][0] = 2**53 + 1
    elif fault == "beyond_u64":
        t["y_data"][0] = 2**64 + 1
    elif fault == "metadata_beyond_u64":
        t["metadata"]["integer"] = 2**64 + 1
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
    elif fault == "field":
        t["extra"] = 0
    elif fault == "reserved_carrier":
        t["metadata"][product.MARKER] = None
    payload = json.dumps(document).encode()
    if fault == "duplicate_key":
        payload = payload.replace(b'"version": "1.0"', b'"version": "1.0", "version": "1.0"')
    elif fault == "truncated":
        payload = payload[:-1]
    path = tmp_path / "bad.json"
    path.write_bytes(payload)
    rejected(binary, path, tmp_path / "output")


@pytest.mark.parametrize(
    "fault",
    [
        "width",
        "nonfinite",
        "missing",
        "interior_padding",
        "header",
        "metadata",
        "options",
        "descriptor",
        "blank",
        "quote",
        "bom",
    ],
)
def test_legacy_csv_corruption_rejected(binary, tmp_path, fault):
    spec = product.csv_spec(runner.compatibility.legacy_document(), include_headers=False, include_metadata=False)
    payload = b"0,-9,-180,0.5,0.125\r\n1,-3.5,0,1.5,0.25\r\n2,0,180,,\r\n"
    if fault == "width":
        payload = payload.replace(b"0,-9,-180", b"0,-9")
    elif fault == "nonfinite":
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
    elif fault == "blank":
        payload += b"\n"
    elif fault == "quote":
        payload = b'"' + payload
    elif fault == "bom":
        payload = b"\xef\xbb\xbf" + payload
    path, descriptor = tmp_path / "bad.csv", tmp_path / "spec.json"
    path.write_bytes(payload)
    result.fft.write_json(descriptor, spec)
    rejected(binary, path, tmp_path / "output", spec=descriptor, fmt="csv")


@pytest.mark.parametrize("fmt", ["json", "csv", "csv_spec"])
def test_complete_snapshot_restores_all_values_profile_and_invalid_reasons(binary, snapshot, tmp_path, fmt):
    document = product.projection(snapshot)
    path = tmp_path / ("product.json" if fmt == "json" else "product.csv")
    spec = None
    if fmt == "json":
        product.save_json(path, document)
    else:
        product.save_csv_pair(path, document)
        if fmt == "csv_spec":
            spec = tmp_path / "spec.json"
            result.fft.write_json(spec, product.csv_spec(document))
    loaded, _ = runner.native_import(
        binary, path, tmp_path / "native", fmt="json" if fmt == "json" else "csv", spec=spec
    )
    assert result.core.json_bytes(loaded["snapshot"]) == result.core.json_bytes(snapshot)
    assert loaded["snapshot"]["columns"]["spl"]["values"] == [None] * len(snapshot["source"]["channel_ids"])
    assert loaded["acquisition"]["channel_ids"] == snapshot["source"]["channel_ids"]


@pytest.mark.parametrize(
    "fault", ["projection", "carrier", "position", "duplicate", "profile", "sidecar_missing", "sidecar_hash"]
)
def test_damaged_carrier_or_sidecar_never_falls_back_to_legacy(binary, snapshot, tmp_path, fault):
    document = product.projection(snapshot)
    if fault.startswith("sidecar"):
        path = tmp_path / "product.csv"
        sidecar = product.save_csv_pair(path, document)
        if fault == "sidecar_missing":
            sidecar.unlink()
        else:
            metadata = result.core.read_json(sidecar.read_bytes())
            metadata["csv_sha256"] = "0" * 64
            result.fft.write_json(sidecar, metadata)
        rejected(binary, path, tmp_path / "output", fmt="csv")
        return
    if fault == "projection":
        document["traces"][1]["y_data"][0] += 1
    elif fault == "carrier":
        document["traces"][0]["metadata"][product.MARKER] = None
    elif fault == "position":
        document["traces"].reverse()
    elif fault == "duplicate":
        document["traces"].append(copy.deepcopy(document["traces"][0]))
    elif fault == "profile":
        document["traces"][0]["metadata"][product.MARKER]["snapshot"]["calibration"][0]["profile"]["v_per_fs"] *= 2
    path = tmp_path / "bad.json"
    result.fft.write_json(path, document)
    rejected(binary, path, tmp_path / "output")


def test_restored_product_is_independent_of_the_input_and_existing_results(binary, snapshot, tmp_path):
    document = product.projection(snapshot)
    path = tmp_path / "product.json"
    product.save_json(path, document)
    loaded, _ = runner.native_import(binary, path, tmp_path / "first")
    before = (tmp_path / "first/imported.json").read_bytes()
    path.write_bytes(b"invalid")
    rejected(binary, path, tmp_path / "bad")
    path.unlink()
    product.save_json(path, document)
    again, _ = runner.native_import(binary, path, tmp_path / "again")
    assert loaded == again
    assert (tmp_path / "first/imported.json").read_bytes() == before
    assert not list(Path(tmp_path).glob(".migration-product-*.tmp"))
