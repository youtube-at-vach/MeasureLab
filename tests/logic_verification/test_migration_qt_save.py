"""Completion/identity/file/translation corruption must not pass Qt save diagnostics."""

from copy import deepcopy
import csv
import io
import json
import subprocess
import sys

import numpy as np
import pytest

from scripts import migration_qt_save as save
from scripts import migration_qt_live as live


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
        formats=[
            catalog["migration.display.save_" + key] for key in ("v1_json", "v1_csv", "product_json", "product_csv")
        ],
        companion=catalog["migration.display.save_csv_companion"],
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


@pytest.mark.parametrize("fault", [None, "v1_format", "missing_sidecar", "cancelled_sidecar"])
def test_product_csv_receipt_requires_pair_and_explicit_format(tmp_path, fault):
    path = tmp_path / "result.csv"
    sidecar = tmp_path / "result.csv.metadata.json"
    path.write_text("csv")
    sidecar.write_text("metadata")
    frame = {"result_id": "1:2", "source": {"generation": 1}, "interval": [10, 20]}
    receipt = {
        "operation_id": 1,
        "result_id": "1:2",
        "generation": 1,
        "interval": [10, 20],
        "destination": str(path),
        "format": "product_csv",
        "status": {"state": "saved"},
    }
    if fault == "v1_format":
        receipt["format"] = "csv"
    elif fault == "missing_sidecar":
        sidecar.unlink()
    elif fault == "cancelled_sidecar":
        receipt["status"]["state"] = "cancelled"
        path.unlink()
    if fault:
        with pytest.raises(save.fft.ReferenceError):
            save.validate_receipts([receipt], tmp_path, [frame], [path.name], product=True)
    else:
        save.validate_receipts([receipt], tmp_path, [frame], [path.name], product=True)


@pytest.mark.parametrize("fault", [None, "replaced_sidecar", "missing_csv", "wrong_failure"])
def test_product_partial_pair_audit_preserves_old_file_and_rejects_restore(tmp_path, fault):
    path = tmp_path / "partial.csv"
    sidecar = tmp_path / "partial.csv.metadata.json"
    path.write_text("orphan csv")
    sidecar.write_bytes(save.PARTIAL_METADATA)
    receipt = {"status": {"state": "failed", "kind": "AlreadyExists"}}
    if fault == "replaced_sidecar":
        sidecar.write_text("changed")
    elif fault == "missing_csv":
        path.unlink()
    elif fault == "wrong_failure":
        receipt["status"]["kind"] = "NotFound"
    if fault:
        with pytest.raises(save.fft.ReferenceError):
            save.validate_partial_pair(receipt, tmp_path, None)
    else:
        save.validate_partial_pair(receipt, tmp_path, None)


def test_product_trace_without_carrier_is_not_a_complete_result(tmp_path):
    path = tmp_path / "legacy.json"
    path.write_text('{"version":"1.0","traces":[]}')
    with pytest.raises(save.fft.ReferenceError, match="missing complete snapshot"):
        save.read_document(path, product=True)


@pytest.mark.parametrize(
    "fault", [None, "generation", "ports", "interval", "windows", "capacity", "bytes", "nonfinite", "tone", "outside"]
)
def test_live_save_raw_archive_binds_generation_ports_and_saved_interval(tmp_path, fault):
    case = live.cases()[1]
    request = live.request_for(case, tmp_path)
    request["format"]["generation"] = 5
    samples = np.tile(live.stimulus(case)[:, case["ports"]], (4, 1))
    raw = tmp_path / "save-input-5.f32"
    samples.tofile(raw)
    record = dict(
        schema_version=1,
        format=deepcopy(request["format"]),
        precision="F32",
        n=live.N,
        interval=[0, live.N * 4],
        windows=4,
        byte_count=samples.nbytes,
        max_bytes=8 * 1024 * 1024,
        max_windows=256,
    )
    interval = [2 * live.N, 3 * live.N]
    if fault == "generation":
        record["format"]["generation"] = 6
    elif fault == "ports":
        record["format"]["input_ports"].reverse()
    elif fault == "interval":
        record["interval"][0] = 1
    elif fault == "windows":
        record["windows"] = 257
    elif fault == "capacity":
        record["max_bytes"] *= 2
    elif fault == "bytes":
        raw.write_bytes(raw.read_bytes()[:-4])
    elif fault == "nonfinite":
        samples[0, 0] = np.nan
        samples.tofile(raw)
    elif fault == "tone":
        np.zeros_like(samples).tofile(raw)
    elif fault == "outside":
        interval = [4 * live.N, 5 * live.N]
    (tmp_path / "save-input-5.json").write_text(json.dumps(record))
    if fault:
        with pytest.raises(save.fft.ReferenceError):
            save.live_samples(tmp_path, request, interval)
    else:
        np.testing.assert_array_equal(save.live_samples(tmp_path, request, interval), samples[2 * live.N : 3 * live.N])


@pytest.mark.parametrize("fault", [None, "delay", "busy", "cancel", "blocked", "no_progress", "writing", "identity"])
def test_slow_save_requires_observed_writer_queue_and_independent_graph_progress(fault):
    receipts = [dict(operation_id=i, result_id="1:3", status={"state": s}) for i, s in ((6, "saved"), (7, "cancelled"))]
    outstanding = deepcopy(receipts)
    outstanding[0]["status"]["state"] = "writing"
    outstanding[1]["status"]["state"] = "queued"
    record = {"load": dict(before=5, after=20, blocked_gui_fft=15, busy=True, cancelled=True, outstanding=outstanding)}
    request = {"save_diagnostic_delay_ms": 250}
    if fault == "delay":
        request["save_diagnostic_delay_ms"] = 0
    elif fault in ("busy", "cancel"):
        record["load"]["busy" if fault == "busy" else "cancelled"] = False
    elif fault == "blocked":
        record["load"]["blocked_gui_fft"] = 0
    elif fault == "no_progress":
        record["load"]["after"] = 5
    elif fault == "writing":
        outstanding[0]["status"]["state"] = "saved"
    elif fault == "identity":
        outstanding[1]["operation_id"] = 8
    if fault:
        with pytest.raises(save.fft.ReferenceError):
            save.validate_load(record, receipts, request)
    else:
        save.validate_load(record, receipts, request)


def test_slow_save_requires_device_opt_in_before_output_creation(tmp_path):
    result = subprocess.run(  # noqa: S603 - explicit repository diagnostic script
        [sys.executable, save.__file__, "--qt-prefix", str(tmp_path), "--output", str(tmp_path / "run"), "--load-test"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2 and "explicit --virtual-device" in result.stderr
    assert not (tmp_path / "run").exists()
