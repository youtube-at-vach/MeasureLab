"""Calibration/exchange comparisons and corrupt-file/request rejection at the native boundary."""

import copy
import csv
import io
import json
import subprocess
import sys

import pytest

from scripts import migration_result_candidate as result
from scripts import migration_fft_reference as fft
from scripts import migration_fft_candidate as candidate


@pytest.fixture(scope="module")
def result_binary():
    binary, _ = result.build()
    return binary


@pytest.fixture
def tone_output(result_binary, tmp_path):
    scenarios = json.loads((result.core.DEFAULT_FIXTURES / "scenarios.json").read_bytes())
    case = next(c for c in scenarios if c["operation"] == "calibration")
    request = tmp_path / "request.json"
    fft.write_json(request, {"schema_version": 1, "input": case["input"]})
    output = tmp_path / "output"
    candidate.run_command([str(result_binary), "--tone", str(request), str(output)])
    return case, output, request


def rejected(binary, mode, input_path, output):
    completed = subprocess.run(  # noqa: S603 - local built harness, explicit argv
        [str(binary), mode, str(input_path), str(output)], capture_output=True, check=False
    )
    assert completed.returncode != 0
    assert completed.stderr
    assert not output.exists()


@pytest.mark.native
def test_saved_calibration_and_four_exchange_examples(tone_output):
    case, output, _ = tone_output
    observed = result.fixture_projection(result.read_result(output))
    result.core.compare_tree(observed, case["expected"])
    assert observed["timebase"]["uncertainty_seconds"] is None
    assert observed["acquired_host_seconds"] is None
    manifest = json.loads((result.core.DEFAULT_FIXTURES / "manifest.json").read_bytes())
    for entry in manifest["exports"]:
        if entry["case_id"] == case["id"]:
            data = result.core.checked_file(result.core.DEFAULT_FIXTURES, entry)
            expected = result.core.read_json(data) if entry["format"] == "json" else result.core.read_csv(data)
            result.core.compare_tree(observed, expected)


@pytest.mark.native
@pytest.mark.parametrize(
    "fault",
    [
        "schema",
        "source",
        "missing_column",
        "shape",
        "zero_unknown",
        "reason",
        "unit",
        "precision",
        "calibration_id",
        "coefficient",
        "interval",
        "nan",
        "duplicate_key",
        "truncated",
        "spl",
    ],
)
def test_native_read_rejects_corrupt_result_before_publication(result_binary, tone_output, tmp_path, fault):
    _, directory, _ = tone_output
    original = (directory / "result.json").read_bytes()
    doc = json.loads(original)
    if fault == "schema":
        doc["schema_version"] = 2
    elif fault == "source":
        doc["source"]["generation"] += 1
    elif fault == "missing_column":
        del doc["columns"]["rms_fs"]
    elif fault == "shape":
        doc["columns"]["rms_fs"]["shape"] = [1]
    elif fault == "zero_unknown":
        doc["columns"]["rms_v"]["values"][-1] = 0
        doc["columns"]["rms_v"]["reasons"][-1] = None
    elif fault == "reason":
        doc["columns"]["spl"]["reasons"][0] = None
    elif fault == "unit":
        doc["columns"]["rms_fs"]["unit"] = "V"
    elif fault == "precision":
        doc["columns"]["rms_fs"]["precision"] = "F32"
    elif fault == "calibration_id":
        doc["calibration"][0]["channel_id"] = "other"
    elif fault == "coefficient":
        doc["calibration"][0]["profile"]["v_per_fs"] = 0
    elif fault == "interval":
        doc["calibration"][0]["profile"]["applied_interval"] = [1, 4096]
    elif fault == "nan":
        doc["columns"]["rms_fs"]["values"][0] = float("nan")
    elif fault == "spl":
        doc["columns"]["spl"]["values"][0] = 0
        doc["columns"]["spl"]["reasons"][0] = None
    payload = json.dumps(doc).encode()
    if fault == "duplicate_key":
        payload = payload.replace(b'"schema_version": 1', b'"schema_version": 1, "schema_version": 1')
    elif fault == "truncated":
        payload = payload[:-1]
    path = tmp_path / "corrupt.json"
    path.write_bytes(payload)
    rejected(result_binary, "--read-json", path, tmp_path / "rejected")
    assert (directory / "result.json").read_bytes() == original


@pytest.mark.native
@pytest.mark.parametrize("fault", ["missing", "duplicate", "nonfinite", "reason", "order", "metadata", "truncated"])
def test_native_and_independent_csv_reader_reject_corruption(result_binary, tone_output, tmp_path, fault):
    _, directory, _ = tone_output
    rows = list(csv.reader(io.StringIO((directory / "result.csv").read_text(), newline="")))
    if fault == "missing":
        rows.pop()
    elif fault == "duplicate":
        rows.append(rows[-1])
    elif fault == "nonfinite":
        row = next(r for r in rows[2:] if r[2])
        row[2] = "NaN"
    elif fault == "reason":
        row = next(r for r in rows[2:] if not r[2])
        row[3] = ""
    elif fault == "order":
        rows[2][1] = "1"
    elif fault == "metadata":
        rows[0][0] = "# MIG-006-E exchange v2"
    stream = io.StringIO(newline="")
    csv.writer(stream, quoting=csv.QUOTE_ALL, lineterminator="\n").writerows(rows)
    payload = stream.getvalue().encode()
    if fault == "truncated":
        payload = payload[:-2]
    path = tmp_path / "corrupt.csv"
    path.write_bytes(payload)
    rejected(result_binary, "--read-csv", path, tmp_path / "rejected")
    (directory / "result.csv").write_bytes(payload)
    with pytest.raises((fft.ReferenceError, ValueError)):
        result.read_result(directory)


@pytest.mark.native
@pytest.mark.parametrize(
    "fault",
    [
        "zero_rate",
        "duplicate_channel",
        "negative_gain",
        "unknown_channel",
        "empty_profile",
        "wrong_interval",
        "correction",
        "unknown_field",
        "schema",
    ],
)
def test_native_rejects_invalid_calibration_requests(result_binary, tone_output, tmp_path, fault):
    _, _, request_path = tone_output
    request = json.loads(request_path.read_bytes())
    data = request["input"]
    if fault == "zero_rate":
        data["provenance"]["timebase"]["rate"] = [0, 1]
    elif fault == "duplicate_channel":
        data["channel_order"][1] = data["channel_order"][0]
    elif fault == "negative_gain":
        data["profiles"]["input.alpha"]["v_per_fs"] = -1
    elif fault == "unknown_channel":
        data["profiles"]["unknown"] = copy.deepcopy(data["profiles"]["input.alpha"])
    elif fault == "empty_profile":
        data["profiles"]["input.alpha"]["revision"] = ""
    elif fault == "wrong_interval":
        data["profiles"]["input.alpha"]["applied_interval"] = [1, 4000]
    elif fault == "correction":
        data["frequency_correction"] = 0
    elif fault == "unknown_field":
        data["unknown"] = True
    else:
        request["schema_version"] = 2
    fft.write_json(request_path, request)
    rejected(result_binary, "--tone", request_path, tmp_path / "rejected")


@pytest.mark.native
def test_entire_saved_corpus_calibration_and_save_session(tmp_path):
    # Pytest's common conftest imports Qt/audio. Check the runner in its own headless process.
    report_path = tmp_path / "report.json"
    completed = subprocess.run(  # noqa: S603 - fixed local Python runner, explicit argv
        [
            sys.executable,
            str(result.ROOT / "scripts/migration_result_candidate.py"),
            "--portable",
            "--report",
            str(report_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(report_path.read_bytes())
    assert len(report["contracts"]) == 2
    assert len(report["corpus"]) == 4
    for case in report["corpus"]:
        assert case["audit"]["fft_evaluations"] == 1
        assert case["audit"]["after_views"]["subscriptions"] == 1
        assert case["audit"]["after_shutdown"]["nodes"] == 0
