"""Async-save receipts must describe completed I/O and the submitted snapshot."""

import copy
import json
import subprocess
import sys

import pytest

from scripts import migration_result_candidate as result
from scripts import migration_fft_reference as fft


def audit_fixture(directory):
    document = {"capture": {"result_id": "held.old"}, "source": {"generation": 7}, "interval": [0, 8]}
    operations = [
        ("result.json", "json", "saved", None),
        ("result.csv", "csv", "saved", None),
        ("result.json", "json", "failed", "AlreadyExists"),
        ("result.csv", "csv", "failed", "AlreadyExists"),
        ("absent/result.json", "json", "failed", "NotFound"),
        ("recovered.json", "json", "saved", None),
    ]
    receipts = []
    for index, (name, fmt, state, kind) in enumerate(operations, 1):
        receipts.append(
            {
                "operation_id": index,
                "result_id": "held.old",
                "generation": 7,
                "interval": [0, 8],
                "destination": str(directory / name),
                "format": fmt,
                "status": {"state": state, **({"kind": kind, "message": "I/O error"} if kind else {})},
            }
        )
    return document, {"capacity": 2, "receipts": receipts, "snapshot_released_by_worker": True}


@pytest.mark.parametrize(
    "fault",
    [
        "queued",
        "writing",
        "cancelled",
        "lost_failure",
        "wrong_error",
        "empty_error",
        "result_id",
        "generation",
        "interval",
        "path",
        "format",
        "duplicate_id",
        "bool_id",
        "bool_generation",
        "missing_receipt",
        "capacity",
        "retained_snapshot",
        "unknown_field",
    ],
)
def test_corrupt_save_receipts_are_not_completion(tmp_path, fault):
    document, original = audit_fixture(tmp_path)
    audit = copy.deepcopy(original)
    if fault in {"queued", "writing", "cancelled"}:
        audit["receipts"][0]["status"] = {"state": fault}
    elif fault == "lost_failure":
        audit["receipts"][2]["status"] = {"state": "saved"}
    elif fault == "wrong_error":
        audit["receipts"][2]["status"]["kind"] = "NotFound"
    elif fault == "empty_error":
        audit["receipts"][2]["status"]["message"] = ""
    elif fault == "result_id":
        audit["receipts"][0]["result_id"] = "current.new"
    elif fault == "generation":
        audit["receipts"][0]["generation"] = 8
    elif fault == "interval":
        audit["receipts"][0]["interval"] = [8, 16]
    elif fault == "path":
        audit["receipts"][0]["destination"] = str(tmp_path / "other.json")
    elif fault == "format":
        audit["receipts"][0]["format"] = "csv"
    elif fault == "duplicate_id":
        audit["receipts"][1]["operation_id"] = 1
    elif fault == "bool_id":
        audit["receipts"][0]["operation_id"] = True
    elif fault == "bool_generation":
        audit["receipts"][0]["generation"] = True
    elif fault == "missing_receipt":
        audit["receipts"].pop()
    elif fault == "capacity":
        audit["capacity"] = True
    elif fault == "retained_snapshot":
        audit["snapshot_released_by_worker"] = False
    else:
        audit["receipts"][0]["unverified"] = True
    with pytest.raises(fft.ReferenceError):
        result.validate_async_audit(audit, document, tmp_path)


@pytest.mark.native
def test_async_saved_corpus_and_receipts_in_headless_process(tmp_path):
    output = tmp_path / "artifacts"
    report_path = output / "report.json"
    completed = subprocess.run(  # noqa: S603 - fixed local evaluation runner, explicit argv
        [
            sys.executable,
            str(result.ROOT / "scripts/migration_result_candidate.py"),
            "--portable",
            "--async-save",
            "--output",
            str(output),
            "--report",
            str(report_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(report_path.read_bytes())
    assert report["status"] == "pass"
    assert report["task"] == "MIG-006-E-async-save"
    assert len(report["contracts"]) == 2
    assert len(report["corpus"]) == 4
    assert len(report["async_saves"]) == 6
    for case in report["async_saves"]:
        for run in case["runs"]:
            directory = output / case["id"] / f"async-from-{run['format']}"
            result.validate_async_audit(run["audit"], result.read_result(directory), directory)
            for name, digest in run["file_sha256"].items():
                assert fft.digest((directory / name).read_bytes()) == digest
    assert len(list(output.rglob("recovered.json"))) == 12
    assert not list(output.rglob("*.tmp"))
