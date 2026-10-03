"""MIG-007-A-save: Qt admission, immutable full-result saves and I/O failure recovery.

Saved original or opt-in BlackHole input bytes; no implicit build or fixture regeneration.
Short correctness diagnostics, including injected slow I/O, not performance acceptance.
"""

from __future__ import annotations

import argparse
import csv
import io
from importlib import metadata
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
PARTIAL_METADATA = b'{"old_sidecar":true}\n'


def read_document(path, *, product=False, codec=None):
    """Independent strict CSV reader, preserving every null/reason and metadata field."""
    if product:
        from scripts import migration_product_exchange as exchange

        imported = (
            exchange.import_json(exchange.read_file(path), codec)
            if path.suffix == ".json"
            else exchange.load_csv_pair(path, codec)
        )
        if imported.snapshot is None:
            raise fft.ReferenceError("product save missing complete snapshot")
        return imported.snapshot
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
        formats=[
            catalog["migration.display.save_" + key] for key in ("v1_json", "v1_csv", "product_json", "product_csv")
        ],
        companion=catalog["migration.display.save_csv_companion"],
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


def validate_receipts(receipts, directory, frames, names, *, product=False):
    if len(receipts) != len(names):
        raise fft.ReferenceError("missing save receipts")
    for index, (receipt, name) in enumerate(zip(receipts, names, strict=True), 1):
        if receipt["operation_id"] != index or type(receipt["operation_id"]) is not int:
            raise fft.ReferenceError("save operation identity")
        expected_format = ("product_" if product else "") + Path(name).suffix[1:]
        if receipt["destination"] != str(directory / name) or receipt["format"] != expected_format:
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
        if product and path.suffix == ".csv":
            sidecar = Path(str(path) + ".metadata.json")
            if state == "saved" and not sidecar.is_file() or state == "cancelled" and sidecar.exists():
                raise fft.ReferenceError("save receipt/sidecar mismatch")


def validate_run(
    output, directory, request, language, case, *, product=False, codec=None, live_evidence=None, load=False
):
    record = validate_ui(output, language)
    retired = [audio.core.read_json(v.encode()) for v in re.findall(r"DISPLAY_SAVE_RETIRED (.+)", output)]
    if len(retired) != 2 or any(v["error"] is not None for v in retired):
        raise fft.ReferenceError("missing or failed save retirement")
    old = next((v["receipts"] for v in retired if len(v["receipts"]) == 9 + int(product) + 2 * int(load)), None)
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
    expected_states = ["saved", "saved", "failed", "failed", "saved", "saved", "saved"]
    if product:
        names.insert(4, "partial.csv")
        expected_states.insert(4, "failed")
    normal_count = 5 + int(product)
    if load:
        names[normal_count:normal_count] = ["slow.json", "cancelled.csv"]
        expected_states[normal_count:normal_count] = ["saved", "cancelled"]
        validate_load(record, old[normal_count : normal_count + 2], request)
        normal_count += 2
    validate_receipts(old, directory, [normal] * normal_count + [held] * 4, names, product=product)
    validate_receipts(new, directory, [teardown] * 2, ["teardown.json", "teardown.csv"], product=product)
    if [r["status"]["state"] for r in old[: len(expected_states)]] != expected_states:
        raise fft.ReferenceError("save failure/recovery outcomes")
    if old[2]["status"]["kind"] != "AlreadyExists" or old[3]["status"]["kind"] != "NotFound":
        raise fft.ReferenceError("unexpected save I/O failures")
    if product:
        validate_partial_pair(old[4], directory, codec)
    expected_profiles = edit.edited_profiles(request)["edited"]
    edit.exact_qml(record["calibration"]["profiles"], expected_profiles, "profile edited after pin")
    if record["calibration"]["status"] != "applied":
        raise fft.ReferenceError("profile edit was not applied")
    comparisons, documents = [], {}
    for receipt, frame in [(r, normal if i < normal_count else held) for i, r in enumerate(old)] + [
        (r, teardown) for r in new
    ]:
        if receipt["status"]["state"] != "saved":
            continue
        path = Path(receipt["destination"])
        document = read_document(path, product=product, codec=codec)
        edit.exact_qml(frame, projection_for(document), "pinned projection/full result")
        if frame["result_id"] in documents:
            trigger.exact(document, documents[frame["result_id"]], "all saved arrays and provenance are identical")
        else:
            bound = {**request, "format": {**request["format"], "generation": frame["source"]["generation"]}}
            if frame["result_id"] == held["result_id"]:
                bound["calibration"] = expected_profiles
            samples = (
                live_samples(live_evidence, bound, document["interval"])
                if live_evidence is not None
                else edit.samples_for(None, bound, case, start=document["interval"][0])
            )
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
        read_document(directory / "normal.json", product=product, codec=codec),
        read_document(directory / "recovery.json", product=product, codec=codec),
        "existing destination unchanged after failure",
    )
    expected_files = {Path(r["destination"]) for r in old + new if r["status"]["state"] == "saved"}
    if product:
        expected_files |= {Path(str(p) + ".metadata.json") for p in expected_files if p.suffix == ".csv"}
        expected_files |= {directory / "partial.csv", directory / "partial.csv.metadata.json"}
    if set(directory.rglob("*")) != expected_files:
        raise fft.ReferenceError("unexpected saved/temporary/stale files")
    record.update(retired=retired, comparisons=comparisons)
    if product:
        record["codec_commands"] = codec.commands
    return record


def validate_load(record, receipts, request):
    """Only injected writer latency proves this concurrency exercise, never a disk budget."""
    load = record.get("load", {})
    if request.get("save_diagnostic_delay_ms") != 250 or any(load.get(k) is not True for k in ("busy", "cancelled")):
        raise fft.ReferenceError("missing explicit slow save/busy/cancel evidence")
    before, after, stalled = (load.get(k) for k in ("before", "after", "blocked_gui_fft"))
    if any(type(v) is not int or v < 0 for v in (before, after, stalled)) or after < before + 2 or stalled < 2:
        raise fft.ReferenceError("slow save blocked acquisition")
    outstanding = load.get("outstanding", [])
    if len(outstanding) != 2 or [r["status"]["state"] for r in outstanding] != ["writing", "queued"]:
        raise fft.ReferenceError("slow writer/queued operation not observed")
    for observed, completed in zip(outstanding, receipts, strict=True):
        trigger.exact(
            {k: v for k, v in observed.items() if k != "status"},
            {k: v for k, v in completed.items() if k != "status"},
            "slow operation identity",
        )


def read_live_inputs(directory, request, generation):
    """Strict generation/port/interval binding for the bounded raw diagnostic archive."""
    metadata_path = directory / f"save-input-{generation}.json"
    raw_path = directory / f"save-input-{generation}.f32"
    record = audio.core.read_json(metadata_path.read_bytes())
    interval, windows = record.get("interval"), record.get("windows")
    if (
        not isinstance(interval, list)
        or len(interval) != 2
        or any(type(v) is not int for v in interval)
        or interval[0] != 0
        or type(windows) is not int
        or not 1 <= windows <= 256
        or interval[1] != request["n"] * windows
    ):
        raise fft.ReferenceError("live save raw interval/capacity")
    expected = dict(
        schema_version=1,
        format={**request["format"], "generation": generation},
        precision="F32",
        n=request["n"],
        interval=interval,
        windows=windows,
        byte_count=interval[1] * len(request["format"]["input_ids"]) * 4,
        max_bytes=8 * 1024 * 1024,
        max_windows=256,
    )
    trigger.exact(record, expected, "live save raw metadata")
    if expected["byte_count"] > expected["max_bytes"] or raw_path.stat().st_size != expected["byte_count"]:
        raise fft.ReferenceError("live save raw byte count/capacity")
    samples = np.frombuffer(raw_path.read_bytes(), dtype="<f4").reshape(interval[1], -1)
    if not np.all(np.isfinite(samples)):
        raise fft.ReferenceError("live save raw nonfinite input")
    return record, samples


def live_samples(directory, request, interval):
    from scripts import migration_qt_live as live

    record, all_samples = read_live_inputs(directory, request, request["format"]["generation"])
    if (
        len(interval) != 2
        or any(type(v) is not int for v in interval)
        or interval[0] < 0
        or interval[1] - interval[0] != request["n"]
        or interval[1] > record["interval"][1]
    ):
        raise fft.ReferenceError("saved interval missing from live raw evidence")
    samples = all_samples[interval[0] : interval[1]]
    peaks = np.abs(np.fft.rfft(samples.astype(float), axis=0)) * 2 / request["n"]
    channels = samples.shape[1]
    if not np.array_equal(peaks.argmax(axis=0), live.BINS[:channels]) or not np.allclose(
        peaks[live.BINS[:channels], np.arange(channels)], np.arange(1, channels + 1) / 512, rtol=0, atol=1e-6
    ):
        raise fft.ReferenceError("saved live tone/port mismatch")
    return samples


def validate_live_inputs(directory, request, *, count):
    paths = sorted(directory.glob("save-input-*.json"))
    live_paths = sorted(directory.glob("live-*.json"))
    if len(paths) != count or len(live_paths) != count or len(list(directory.glob("save-input-*.f32"))) != count:
        raise fft.ReferenceError("missing live save raw generations")
    observed = []
    for path in live_paths:
        metrics = audio.core.read_json(path.read_bytes())
        generation = metrics["generation"]
        record, _ = read_live_inputs(directory, request, generation)
        if record["windows"] != metrics["fft_evaluations"] or record["interval"][1] > metrics["captured_frames"]:
            raise fft.ReferenceError("live save raw/graph coverage mismatch")
        observed.append(
            dict(
                metadata=record,
                metadata_sha256=sha256(directory / f"save-input-{generation}.json"),
                input_sha256=sha256(directory / f"save-input-{generation}.f32"),
            )
        )
    return observed


def validate_partial_pair(receipt, directory, codec):
    """A pair failure must preserve the pre-existing sidecar and reject restoration."""
    if receipt["status"].get("kind") != "AlreadyExists":
        raise fft.ReferenceError("unexpected sidecar publication failure")
    path = directory / "partial.csv"
    if not path.is_file() or Path(str(path) + ".metadata.json").read_bytes() != PARTIAL_METADATA:
        raise fft.ReferenceError("partial CSV/old sidecar not preserved")
    try:
        read_document(path, product=True, codec=codec)
    except fft.ReferenceError:
        return
    raise fft.ReferenceError("partial product pair was restored")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qt-prefix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-dir", type=Path, default=ROOT / "native/target/debug")
    parser.add_argument("--language", choices=LANGUAGES, action="append")
    parser.add_argument("--all-inputs", action="store_true")
    parser.add_argument(
        "--virtual-device", action="store_true", help="explicit opt-in to BlackHole input/output on macOS"
    )
    parser.add_argument(
        "--load-test", action="store_true", help="inject 250 ms writer latency; check busy/cancel and acquisition"
    )
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--portable", action="store_true")
    parser.add_argument(
        "--product-format", action="store_true", help="exercise native product JSON/CSV and sidecar failure"
    )
    args = parser.parse_args()
    if args.output.exists() or args.repeat < 1 or not np.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("new output directory and positive repeat/timeout required")
    if args.virtual_device and sys.platform != "darwin":
        parser.error("BlackHole requires macOS")
    if args.load_test and not args.virtual_device:
        parser.error("--load-test requires explicit --virtual-device")
    env, version = qt_environment(args.qt_prefix)
    binaries = [
        args.target_dir.resolve() / (name + (".exe" if os.name == "nt" else ""))
        for name in ("cxxqt-display", "qtbridge-display")
    ]
    if not all(p.is_file() for p in binaries):
        parser.error("build both Qt displays first")
    reader = args.target_dir.resolve() / ("result-candidate.exe" if os.name == "nt" else "result-candidate")
    if args.product_format and not reader.is_file():
        parser.error("build result-candidate for independent full-snapshot validation")
    manifest, manifest_hash = candidate.load_manifest(audio.core.DEFAULT_FIXTURES, portable=args.portable, is_core=True)
    if args.virtual_device:
        from scripts import migration_qt_live as live

        cases, runner = live.cases(), live.run_display
    else:
        cases, runner = manifest["tones"] if args.all_inputs else manifest["tones"][:1], run_display
    languages = args.language or (("en",) if args.virtual_device else LANGUAGES)
    args.output.mkdir(parents=True)
    started = time.monotonic()
    runs = []
    for repeat in range(args.repeat):
        for language in languages:
            for case in cases:
                name = case["id"] if args.virtual_device else case["spec"]["id"]
                for binary in binaries:
                    options = {"save_load": args.load_test} if args.virtual_device else {}
                    run = runner(
                        binary,
                        env,
                        args.output / f"{repeat}-{language}-{name}-{binary.stem}",
                        case,
                        args.timeout,
                        language=language,
                        calibration=True,
                        saving=True,
                        product_saving=args.product_format,
                        **options,
                    )
                    runs.append(run)
                    print(
                        f"{binary.name} {language} {name}: {'PASS' if run['passed'] else 'FAIL'} {run['reason'] or ''}",
                        flush=True,
                    )
                    if not run["passed"]:
                        print(
                            "\n".join(line for line in run["output"].splitlines() if "DISPLAY_SAVE {" not in line)[
                                -5000:
                            ],
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
                "qt_live",
                "audio_virtual",
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
    if args.product_format:
        helpers += [ROOT / "scripts/migration_product_exchange.py"]
        paths += sorted((ROOT / "src/core/export").glob("*.py"))
        paths += [ROOT / "src/core/localization.py", ROOT / "src/core/utils.py"]
    fft.write_json(
        args.output / "report.json",
        {
            "schema_version": 1,
            "task": "MIG-007-A-product-save" if args.product_format else "MIG-007-A-save",
            "passed": all(r["passed"] for r in runs),
            "duration_seconds": time.monotonic() - started,
            "qt_version": version,
            "mode": "portable" if args.portable else "pinned-reference",
            "measurement_kind": "BlackHole_slow_writer_correctness_only"
            if args.load_test
            else "BlackHole_correctness_only"
            if args.virtual_device
            else "saved_input_correctness_only",
            "injected_writer_delay_ms": 250 if args.load_test else 0,
            "host": {
                "os": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "macos": platform.mac_ver()[0],
            },
            "python_version": platform.python_version(),
            "versions": {
                name: metadata.version(name)
                for name in (("numpy", "sounddevice") if args.virtual_device else ("numpy",))
            },
            "fixture_manifest_sha256": manifest_hash,
            "source_sha256": {str(p.relative_to(ROOT)): sha256(p) for p in sorted(paths)},
            "runner_sha256": {str(p.relative_to(ROOT)): sha256(p) for p in helpers},
            "codec_binary_sha256": sha256(reader) if args.product_format else None,
            "runs": runs,
            "files_sha256": {
                str(p.relative_to(args.output)): sha256(p) for p in sorted(args.output.rglob("*")) if p.is_file()
            },
            "limitations": [
                "product codec with carrier/sidecar; final schema pending"
                if args.product_format
                else "v1 evaluation codec; product formats tested separately",
                "CSV pair publication is not transactional",
                "two-job bound, no process byte budget",
                "short correctness diagnostic, no load/performance acceptance",
                "injected writer wait is not measured disk latency; bounded raw archive is diagnostic only",
                "no other-OS or real window manager acceptance",
            ],
        },
    )
    return 0 if all(r["passed"] for r in runs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
