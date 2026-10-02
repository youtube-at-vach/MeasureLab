"""Completion/identity/file/translation corruption must not pass Qt save diagnostics."""

from copy import deepcopy
import csv
import io
import json
import subprocess
import sys

import pytest

from scripts import migration_qt_save as save


def ui(language):
    catalog = json.loads((save.ROOT / f"src/assets/lang/{language}.json").read_text())
    labels = {
        key: catalog["migration.display.save_" + suffix]
        for key, suffix in {
            "title": "measurement",
            "path": "path",
            "format": "format",
            "save": "measurement",
            "cancel": "cancel",
            "finish": "finish",
            "status": "failed",
        }.items()
    }
    labels.update(
        close=catalog["migration.display.calibration_close"],
        note=catalog["migration.display.save_note"] + "\n" + catalog["migration.display.save_finish_note"],
    )
    return {
        "closed": True,
        "detached_hold": True,
        "restart": True,
        "recreate": True,
        "blocked_gui_fft": 3,
        "minimum": [900, 600],
        "size": [1000, 640],
        "dialog": {"labels": labels, "labels_fit": True, "size": [560, 440]},
    }


@pytest.mark.parametrize("language", save.LANGUAGES)
def test_all_actual_save_labels_and_geometry(language):
    record = ui(language)
    text = f"DISPLAY_LANGUAGE {language}\nqml: DISPLAY_SAVE {json.dumps(record)}\n"
    assert save.validate_ui(text, language) == record


@pytest.mark.parametrize(
    "fault", ["wrong_language", "clipped", "oversize", "undersize", "blocked", "lifecycle", "repeated"]
)
def test_bad_ui_evidence_is_rejected(fault):
    record = ui("ja")
    if fault == "wrong_language":
        record["dialog"]["labels"] = ui("en")["dialog"]["labels"]
    elif fault == "clipped":
        record["dialog"]["labels_fit"] = False
    elif fault == "oversize":
        record["dialog"]["size"][1] = 691
    elif fault == "undersize":
        record["size"][0] = 400
    elif fault == "blocked":
        record["blocked_gui_fft"] = 0
    elif fault == "lifecycle":
        record["closed"] = False
    text = f"DISPLAY_LANGUAGE ja\nDISPLAY_SAVE {json.dumps(record)}\n"
    if fault == "repeated":
        text += text
    with pytest.raises(save.fft.ReferenceError):
        save.validate_ui(text, "ja")


@pytest.mark.parametrize(
    "fault",
    [
        "queued",
        "writing",
        "identity",
        "generation",
        "interval",
        "operation",
        "float_id",
        "path",
        "format",
        "missing",
        "cancelled_file",
    ],
)
def test_admission_stale_identity_or_receipt_file_mismatch_rejected(tmp_path, fault):
    frame = {"result_id": "1:2", "source": {"generation": 1}, "interval": [10, 20]}
    receipt = {
        "operation_id": 1,
        "result_id": "1:2",
        "generation": 1,
        "interval": [10, 20],
        "destination": str(tmp_path / "result.json"),
        "format": "json",
        "status": {"state": "saved"},
    }
    (tmp_path / "result.json").write_text("{}")
    if fault in ("queued", "writing", "cancelled_file"):
        receipt["status"]["state"] = "cancelled" if fault == "cancelled_file" else fault
    elif fault == "identity":
        receipt["result_id"] = "1:3"
    elif fault == "generation":
        receipt["generation"] = 2
    elif fault == "interval":
        receipt["interval"] = [11, 21]
    elif fault in ("operation", "float_id"):
        receipt["operation_id"] = 2 if fault == "operation" else 1.0
    elif fault == "path":
        receipt["destination"] = str(tmp_path / "other.json")
    elif fault == "format":
        receipt["format"] = "csv"
    else:
        (tmp_path / "result.json").unlink()
    with pytest.raises(save.fft.ReferenceError):
        save.validate_receipts([receipt], tmp_path, [frame], ["result.json"])


def csv_document(rows):
    stream = io.StringIO(newline="")
    csv.writer(stream).writerows(rows)
    return stream.getvalue()


@pytest.mark.parametrize(
    "fault", [None, "truncated", "duplicate", "order", "nonfinite", "null", "numeric_metadata", "empty_header"]
)
def test_csv_reader_keeps_exact_null_reasons_and_rejects_corruption(tmp_path, fault):
    document = {"source": {"generation": 3}, "columns": {"value": {"shape": [2], "values": [], "reasons": []}}}
    rows = [
        ["# MIG-006-E exchange v1", json.dumps(document)],
        ["metric", "index", "value", "reason"],
        ["value", "0", "1.2345678901234567", ""],
        ["value", "1", "", "uncalibrated"],
    ]
    if fault == "truncated":
        rows.pop()
    elif fault == "duplicate":
        rows.append(deepcopy(rows[-1]))
    elif fault == "order":
        rows[2][1] = "1"
    elif fault == "nonfinite":
        rows[2][2] = "nan"
    elif fault == "null":
        rows[-1][-1] = ""
    elif fault == "numeric_metadata":
        document["columns"]["value"]["values"] = [2]
        rows[0][1] = json.dumps(document)
    elif fault == "empty_header":
        rows[0] = []
    path = tmp_path / "result.csv"
    path.write_text(csv_document(rows))
    if fault:
        with pytest.raises(save.fft.ReferenceError):
            save.read_document(path)
    else:
        expected = deepcopy(document)
        expected["columns"]["value"].update(values=[1.2345678901234567, None], reasons=[None, "uncalibrated"])
        assert save.read_document(path) == expected


def test_save_runner_is_headless():
    result = subprocess.run(
        [sys.executable, "-c", "from scripts import migration_qt_save as s; s.fft.assert_headless()"],
        cwd=save.ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
