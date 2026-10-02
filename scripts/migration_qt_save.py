"""MIG-007-A-save: Qt admission, immutable full-result saves and I/O failure recovery.

Saved original input bytes only; no implicit build or fixture regeneration.
Short correctness diagnostics, not load/performance or product-format acceptance.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
from pathlib import Path
import platform
import re
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import migration_qt_calibration as calibration  # noqa: E402
from scripts import migration_qt_calibration_edit as edit  # noqa: E402
from scripts.migration_qt_display import projection_for, qt_environment, run_display  # noqa: E402
from scripts.migration_qt_probe import sha256  # noqa: E402

audio, candidate, fft, trigger = calibration.audio, calibration.candidate, calibration.fft, calibration.trigger
LANGUAGES = calibration.LANGUAGES


def read_document(path):
    """Independent strict CSV reader, preserving every null/reason and metadata field."""
    if path.suffix == ".json":
        return audio.core.read_json(path.read_bytes())
    rows = list(csv.reader(io.StringIO(path.read_text(), newline=""), strict=True))
    if len(rows) < 3 or len(rows[0]) != 2 or rows[0][0] != "# MIG-006-E exchange v1":
        raise fft.ReferenceError("save CSV schema")
    if rows[1] != ["metric", "index", "value", "reason"]:
        raise fft.ReferenceError("save CSV header")
    document = audio.core.read_json(rows[0][1])
    for column in document["columns"].values():
        if column["values"] or column["reasons"]:
            raise fft.ReferenceError("save CSV numeric metadata")
    for row in rows[2:]:
        if len(row) != 4 or row[0] not in document["columns"]:
            raise fft.ReferenceError("save CSV row")
        column = document["columns"][row[0]]
        if row[1] != str(len(column["values"])):
            raise fft.ReferenceError("save CSV order")
        value, reason = float(row[2]) if row[2] else None, row[3] or None
        if (value is None) != (reason is not None) or value is not None and not np.isfinite(value):
            raise fft.ReferenceError("save CSV null/reason")
        column["values"].append(value)
        column["reasons"].append(reason)
    for column in document["columns"].values():
        if len(column["values"]) != int(np.prod(column["shape"])):
            raise fft.ReferenceError("save CSV truncated column")
    return document


def validate_ui(output, language):
    records = re.findall(r"DISPLAY_SAVE (.+)", output)
    if len(records) != 1 or f"DISPLAY_LANGUAGE {language}\n" not in output:
        raise fft.ReferenceError("missing save UI/language evidence")
    record = audio.core.read_json(records[0].encode())
    if any(record.get(k) is not True for k in ("closed", "detached_hold", "restart", "recreate")):
        raise fft.ReferenceError("incomplete save lifecycle")
    if type(record.get("blocked_gui_fft")) is not int or record["blocked_gui_fft"] < 2:
        raise fft.ReferenceError("save blocked acquisition")
    dialog = record["dialog"]
    catalog = json.loads((ROOT / f"src/assets/lang/{language}.json").read_text())
    expected = {
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
    expected.update(
        close=catalog["migration.display.calibration_close"],
        note=catalog["migration.display.save_note"] + "\n" + catalog["migration.display.save_finish_note"],
    )
    trigger.exact(dialog["labels"], expected, "translated save dialog")
    if dialog["labels_fit"] is not True:
        raise fft.ReferenceError("clipped save dialog labels")
    for size in (record["minimum"], record["size"], dialog["size"]):
        if len(size) != 2 or any(type(v) not in (int, float) or not np.isfinite(v) or v <= 0 for v in size):
            raise fft.ReferenceError("invalid save geometry")
    if any(size[0] > 1180 or size[1] > 690 for size in (record["minimum"], dialog["size"])):
        raise fft.ReferenceError("save UI exceeds size limit")
    if any(a > b for a, b in zip(record["minimum"], record["size"], strict=True)):
        raise fft.ReferenceError("save window below minimum")
    return record


def validate_receipts(receipts, directory, frames, names):
    if len(receipts) != len(names):
        raise fft.ReferenceError("missing save receipts")
    for index, (receipt, name) in enumerate(zip(receipts, names, strict=True), 1):
        if receipt["operation_id"] != index or type(receipt["operation_id"]) is not int:
            raise fft.ReferenceError("save operation identity")
        if receipt["destination"] != str(directory / name) or receipt["format"] != Path(name).suffix[1:]:
            raise fft.ReferenceError("save destination/format")
        frame = frames[index - 1]
        for field, value in (
            ("result_id", frame["result_id"]),
            ("generation", frame["source"]["generation"]),
            ("interval", frame["interval"]),
        ):
            trigger.exact(receipt[field], value, "save receipt " + field)
        state = receipt["status"]["state"]
        if state not in ("saved", "failed", "cancelled"):
            raise fft.ReferenceError("acceptance is not file completion")
        path = directory / name
        if state == "saved" and not path.is_file() or state == "cancelled" and path.exists():
            raise fft.ReferenceError("save receipt/file mismatch")


def validate_run(output, directory, request, language, case):
    record = validate_ui(output, language)
    retired = [audio.core.read_json(v.encode()) for v in re.findall(r"DISPLAY_SAVE_RETIRED (.+)", output)]
    if len(retired) != 2 or any(v["error"] is not None for v in retired):
        raise fft.ReferenceError("missing or failed save retirement")
    old = next((v["receipts"] for v in retired if len(v["receipts"]) == 9), None)
    new = next((v["receipts"] for v in retired if len(v["receipts"]) == 2), None)
    if old is None or new is None:
        raise fft.ReferenceError("retired save session mismatch")
    edit.exact_qml(record["receipts"], old, "GUI/retired receipts")
    normal, held, teardown = record["normal"], record["trigger"]["frame"], record["teardown"]
    names = [
        "normal.json",
        "normal.csv",
        "normal.json",
        "missing/result.json",
        "recovery.json",
        "trigger.json",
        "trigger.csv",
        "stop.json",
        "stop.csv",
    ]
    validate_receipts(old, directory, [normal] * 5 + [held] * 4, names)
    validate_receipts(new, directory, [teardown] * 2, ["teardown.json", "teardown.csv"])
    if [r["status"]["state"] for r in old[:7]] != ["saved", "saved", "failed", "failed", "saved", "saved", "saved"]:
        raise fft.ReferenceError("save failure/recovery outcomes")
    if old[2]["status"]["kind"] != "AlreadyExists" or old[3]["status"]["kind"] != "NotFound":
        raise fft.ReferenceError("unexpected save I/O failures")
    expected_profiles = edit.edited_profiles(request)["edited"]
    edit.exact_qml(record["calibration"]["profiles"], expected_profiles, "profile edited after pin")
    if record["calibration"]["status"] != "applied":
        raise fft.ReferenceError("profile edit was not applied")
    comparisons, documents = [], {}
    for receipt, frame in [(r, normal if i < 5 else held) for i, r in enumerate(old)] + [(r, teardown) for r in new]:
        if receipt["status"]["state"] != "saved":
            continue
        path = Path(receipt["destination"])
        document = read_document(path)
        edit.exact_qml(frame, projection_for(document), "pinned projection/full result")
        if frame["result_id"] in documents:
            trigger.exact(document, documents[frame["result_id"]], "all saved arrays and provenance are identical")
        else:
            bound = {**request, "format": {**request["format"], "generation": frame["source"]["generation"]}}
            if frame["result_id"] == held["result_id"]:
                bound["calibration"] = expected_profiles
            samples = edit.samples_for(None, bound, case, start=document["interval"][0])
            read = None
            if document["capture"]["trigger"] is not None:
                response = record["trigger"]
                read = {
                    "history": response["history"],
                    "raw_result_id": {"graph": document["raw_result_id"][0], "serial": document["raw_result_id"][1]},
                    "result_id": frame["result_id"],
                    "event": response["request"]["event"],
                }
            comparisons.append(calibration.validate_result(document, bound, samples, case, read=read))
        documents[frame["result_id"]] = document
    trigger.exact(
        read_document(directory / "normal.json"),
        read_document(directory / "recovery.json"),
        "existing destination unchanged after failure",
    )
    expected_files = {Path(r["destination"]) for r in old + new if r["status"]["state"] == "saved"}
    if set(directory.rglob("*")) != expected_files:
        raise fft.ReferenceError("unexpected saved/temporary/stale files")
    record.update(retired=retired, comparisons=comparisons)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qt-prefix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-dir", type=Path, default=ROOT / "native/target/debug")
    parser.add_argument("--language", choices=LANGUAGES, action="append")
    parser.add_argument("--all-inputs", action="store_true")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--portable", action="store_true")
    args = parser.parse_args()
    if args.output.exists() or not np.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("new output directory and positive timeout required")
    env, version = qt_environment(args.qt_prefix)
    binaries = [
        args.target_dir.resolve() / (name + (".exe" if os.name == "nt" else ""))
        for name in ("cxxqt-display", "qtbridge-display")
    ]
    if not all(p.is_file() for p in binaries):
        parser.error("build both Qt displays first")
    manifest, manifest_hash = candidate.load_manifest(audio.core.DEFAULT_FIXTURES, portable=args.portable, is_core=True)
    args.output.mkdir(parents=True)
    started = time.monotonic()
    runs = []
    for language in args.language or LANGUAGES:
        for case in manifest["tones"] if args.all_inputs else manifest["tones"][:1]:
            for binary in binaries:
                run = run_display(
                    binary,
                    env,
                    args.output / f"{language}-{case['spec']['id']}-{binary.stem}",
                    case,
                    args.timeout,
                    language=language,
                    calibration=True,
                    saving=True,
                )
                runs.append(run)
                print(
                    f"{binary.name} {language} {case['spec']['id']}: {'PASS' if run['passed'] else 'FAIL'} {run['reason'] or ''}",
                    flush=True,
                )
                if not run["passed"]:
                    print(
                        "\n".join(line for line in run["output"].splitlines() if "DISPLAY_SAVE {" not in line)[-5000:],
                        flush=True,
                    )
    paths = [
        p
        for p in (ROOT / "native").rglob("*")
        if p.is_file() and "target" not in p.parts and p.suffix in (".rs", ".qml", ".toml", ".lock")
    ]
    paths += sorted((ROOT / "src/assets/lang").glob("*.json"))
    helpers = [
        Path(__file__),
        *(
            ROOT / "scripts" / f"migration_{name}.py"
            for name in (
                "qt_display",
                "qt_calibration",
                "qt_calibration_edit",
                "qt_trigger",
                "qt_probe",
                "qt_workspace",
                "trigger_candidate",
                "audio_graph",
                "fft_candidate",
                "fft_reference",
                "fft_oracle",
                "core_reference",
                "graph_candidate",
            )
        ),
    ]
    fft.write_json(
        args.output / "report.json",
        {
            "schema_version": 1,
            "task": "MIG-007-A-save",
            "passed": all(r["passed"] for r in runs),
            "duration_seconds": time.monotonic() - started,
            "qt_version": version,
            "mode": "portable" if args.portable else "pinned-reference",
            "measurement_kind": "saved_input_correctness_only",
            "host": {"os": platform.system(), "release": platform.release(), "machine": platform.machine()},
            "fixture_manifest_sha256": manifest_hash,
            "source_sha256": {str(p.relative_to(ROOT)): sha256(p) for p in sorted(paths)},
            "runner_sha256": {str(p.relative_to(ROOT)): sha256(p) for p in helpers},
            "runs": runs,
            "files_sha256": {
                str(p.relative_to(args.output)): sha256(p) for p in sorted(args.output.rglob("*")) if p.is_file()
            },
            "limitations": [
                "v1 evaluation codec; native product codec pending",
                "two-job bound, no process byte budget",
                "short correctness diagnostic, no load/performance acceptance",
                "no other-OS or real window manager acceptance",
            ],
        },
    )
    return 0 if all(r["passed"] for r in runs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
