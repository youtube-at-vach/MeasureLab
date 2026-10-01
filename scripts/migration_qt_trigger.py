"""MIG-007-A: explicit Qt trigger requests -> analysis owner -> two shared views.

Original saved input or exact BlackHole input, immutable full-result evidence,
independent NumPy oracle, nine-language controls and lifecycle checks.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import re
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import migration_audio_graph as audio  # noqa: E402
from scripts import migration_fft_candidate as candidate  # noqa: E402
from scripts import migration_fft_reference as fft  # noqa: E402
from scripts import migration_trigger_candidate as trigger  # noqa: E402
from scripts.migration_qt_display import qt_environment, run_display  # noqa: E402
from scripts.migration_qt_probe import sha256  # noqa: E402
from scripts.migration_qt_workspace import LANGUAGES  # noqa: E402

LIFECYCLE = (
    "pending",
    "retry",
    "shared_raw",
    "hold_continued",
    "detached_hold",
    "gap",
    "stale",
    "release",
    "cancelled",
    "restart",
    "recreate",
)


def validate_ui(output, language):
    records = re.findall(r"DISPLAY_TRIGGER (.+)", output)
    if len(records) != 1 or f"DISPLAY_LANGUAGE {language}\n" not in output:
        raise fft.ReferenceError("missing trigger UI/language evidence")
    record = audio.core.read_json(records[0].encode())
    if any(record.get(key) is not True for key in (*LIFECYCLE, "buttons_fit")):
        raise fft.ReferenceError("incomplete trigger lifecycle or clipped buttons")
    if type(record.get("blocked_gui_fft")) is not int or record["blocked_gui_fft"] < 2:
        raise fft.ReferenceError("acquisition did not advance while the GUI was blocked")
    catalog = json.loads((ROOT / f"src/assets/lang/{language}.json").read_text())
    labels = {
        key: catalog["migration.display.trigger_" + suffix]
        for key, suffix in {
            "capture": "capture",
            "retry": "retry",
            "release": "release",
            "sample": "sample",
            "status": "complete",
        }.items()
    }
    trigger.exact(record["labels"], labels, "translated trigger labels")
    minimum, size = record["minimum"], record["size"]
    if (
        len(minimum) != 2
        or len(size) != 2
        or any(type(v) is not int or v <= 0 for v in minimum + size)
        or minimum[0] > 1180
        or minimum[1] > 690
        or any(a > b for a, b in zip(minimum, size, strict=True))
    ):
        raise fft.ReferenceError("trigger UI size exceeds limit")
    return record


def validate_receipt(receipt, request):
    """Check sample-derived interval, exact original event and no fabricated pending data."""
    fields = {
        "schema_version",
        "revision",
        "request",
        "status",
        "reason",
        "history",
        "fractional_residual",
        "fft_origin",
        "frame",
        "acquired_until",
        "trigger_evaluations",
        "continuous_evaluations",
    }
    if not isinstance(receipt, dict) or set(receipt) != fields or type(receipt["schema_version"]) is not int:
        raise fft.ReferenceError("invalid trigger receipt inventory")
    revision, body = receipt["revision"], receipt["request"]
    event = body["event"]
    n, fmt = request["n"], request["format"]
    sample = event["sample"]
    if (
        type(revision) is not int
        or revision <= 0
        or type(sample["numerator"]) is not int
        or sample["numerator"] % 2 != 1
        or sample["denominator"] != 2
    ):
        raise fft.ReferenceError("invalid trigger revision or fractional position")
    expected = {
        "id": f"qt.event.{revision}",
        "stream_id": fmt["stream_id"],
        "generation": fmt["generation"],
        "timebase_id": fmt["timebase_id"],
        "sample": sample,
        "source": "qt.manual",
        "kind": "manual",
        "polarity": "none",
        "condition_revision": "manual.v1",
        "validity": [],
        "received_host_seconds": None,
    }
    trigger.exact(event, expected, "Qt event")
    trigger.exact(
        {k: v for k, v in body.items() if k != "event"},
        {
            "request_id": f"qt.manual.{revision}",
            "pre": n // 2,
            "post": n - n // 2,
        },
        "Qt request",
    )
    start = sample["numerator"] // 2 - n // 2
    end, high = start + n, receipt["acquired_until"]
    if type(high) is not int or high < 0 or start < 0 or start % n:
        raise fft.ReferenceError("invalid acquired position or capture interval")
    status = receipt["status"]
    if status not in ("pending", "gap", "complete") or any(
        type(receipt[k]) is not int or receipt[k] < 0 for k in ("trigger_evaluations", "continuous_evaluations")
    ):
        raise fft.ReferenceError("invalid trigger status or counters")
    pending = [[max(start, high), end]] if end > high else []
    missing = [[start, end]] if status == "gap" else []
    trigger.exact(
        receipt["history"],
        {
            "stream_id": fmt["stream_id"],
            "generation": fmt["generation"],
            "timebase_id": fmt["timebase_id"],
            "interval": [start, end],
            "status": "snapshot" if status == "complete" else status,
            "missing": missing,
            "pending": pending,
            "reason": "missing" if missing else None,
        },
        "Qt history",
    )
    trigger.exact(receipt["fractional_residual"], {"numerator": 1, "denominator": 2}, "Qt residual")
    if receipt["schema_version"] != 1 or receipt["reason"] != ("missing" if missing else None):
        raise fft.ReferenceError("invalid trigger receipt metadata")
    if status != "complete" and (receipt["frame"] is not None or receipt["fft_origin"] != "none"):
        raise fft.ReferenceError("pending/gap contains numeric data")
    if status == "complete":
        frame = receipt["frame"]
        if not isinstance(frame, dict) or receipt["fft_origin"] not in (
            "computed",
            "continuous-cache",
            "trigger-cache",
        ):
            raise fft.ReferenceError("complete trigger has no projection or FFT origin")
        raw_id = frame["raw_result_id"]
        if not isinstance(raw_id, list) or len(raw_id) != 2 or any(type(v) is not int or v <= 0 for v in raw_id):
            raise fft.ReferenceError("invalid shared raw identity")
    if status == "pending" and not pending or status == "complete" and (pending or high < end):
        raise fft.ReferenceError("trigger completion disagrees with acquisition")
    return start


def validate_captures(directory, request, case=None):
    first_results = sorted(directory.glob("generation-*.json"))
    if len(first_results) != 2:
        raise fft.ReferenceError("expected two running generations")
    generation = audio.core.read_json(first_results[0].read_bytes())["source"]["generation"]
    request = {**request, "format": {**request["format"], "generation": generation}}
    records = {}
    for path in directory.glob(f"trigger-{generation}-*.json"):
        if path.name.endswith(".result.json"):
            continue
        receipt = audio.core.read_json(path.read_bytes())
        revision, status = receipt["revision"], receipt["status"]
        if path.name != f"trigger-{generation}-{revision}-{status}.json" or (revision, status) in records:
            raise fft.ReferenceError("trigger evidence filename/revision mismatch")
        validate_receipt(receipt, request)
        if status != "complete" and any(path.with_suffix(suffix).exists() for suffix in (".result.json", ".bin")):
            raise fft.ReferenceError("pending/gap has saved numeric evidence")
        records[revision, status] = receipt
    required = {(1, "pending"), (1, "complete"), (2, "complete"), (3, "gap")}
    if not required.issubset(records) or set(records) - required - {(4, "pending")}:
        raise fft.ReferenceError("missing or unexpected trigger capture evidence")
    pending, first, second, gap = (
        records[key] for key in ((1, "pending"), (1, "complete"), (2, "complete"), (3, "gap"))
    )
    trigger.exact(pending["request"], first["request"], "unchanged explicit retry")
    if first["history"]["interval"] != second["history"]["interval"] or gap["history"]["interval"] != [0, request["n"]]:
        raise fft.ReferenceError("trigger retry/shared/expired interval mismatch")
    if (
        first["frame"]["raw_result_id"] != second["frame"]["raw_result_id"]
        or first["frame"]["result_id"] == second["frame"]["result_id"]
        or second["fft_origin"] not in ("continuous-cache", "trigger-cache")
        or first["trigger_evaluations"] != second["trigger_evaluations"]
    ):
        raise fft.ReferenceError("trigger raw FFT is not shared")
    observed = []
    for revision in (1, 2):
        receipt = records[revision, "complete"]
        stem = directory / f"trigger-{generation}-{revision}-complete"
        document = audio.core.read_json(stem.with_suffix(".result.json").read_bytes())
        raw = stem.with_suffix(".bin").read_bytes()
        dtype = "<f4" if request["precision"] == "F32" else "<f8"
        channels, n = len(request["format"]["input_ids"]), request["n"]
        values = np.frombuffer(raw, dtype=dtype)
        if values.size != n * channels or not np.all(np.isfinite(values)):
            raise fft.ReferenceError("trigger captured bytes shape/nonfinite")
        samples = values.reshape(n, channels)
        start = receipt["history"]["interval"][0]
        if case:
            source = audio.core.DEFAULT_FIXTURES / case["spec"]["id"]
            expected_raw = audio.core.checked_file(source, case["arrays"]["input"])
            expected_samples = np.frombuffer(expected_raw, dtype=dtype).reshape(n, channels)[
                :, request["format"]["input_ports"]
            ]
            if raw != np.roll(expected_samples, -start % n, axis=0).tobytes():
                raise fft.ReferenceError("trigger retained bytes differ from original input")
        else:
            from scripts.migration_qt_live import BINS

            peaks = np.abs(np.fft.rfft(samples.astype(float), axis=0)) * 2 / n
            if not np.array_equal(peaks.argmax(axis=0), BINS[:channels]) or not np.allclose(
                peaks[BINS[:channels], np.arange(channels)], np.arange(1, channels + 1) / 512, rtol=0, atol=1e-6
            ):
                raise fft.ReferenceError("live trigger tone/port binding mismatch")
        rid = receipt["frame"]["raw_result_id"]
        read = {
            "history": receipt["history"],
            "raw_result_id": {"graph": rid[0], "serial": rid[1]},
            "result_id": receipt["frame"]["result_id"],
            "event": receipt["request"]["event"],
        }
        comparisons = trigger.validate_document(
            document, read, request, case or {"spec": {"rate_hz": 48000, "window": "boxcar"}}, samples, alignment=0
        )
        expected_projection = {
            "schema_version": 1,
            "result_id": document["capture"]["result_id"],
            "source": document["source"],
            "interval": document["interval"],
            "frequency_hz": document["axis"]["corrected"],
            "peak_fs": document["columns"]["peak_fs"],
            "validity": document["validity"],
            "error": document["error"],
            "clock_origin": "unknown",
            "calibration": "uncalibrated",
            "capture": document["capture"],
            "raw_result_id": document["raw_result_id"],
        }
        trigger.exact(receipt["frame"], expected_projection, "Qt projection matches full result")
        observed.append({"revision": revision, "interval": [start, start + n], "comparisons": comparisons})
    return {"captures": observed, "files_sha256": {p.name: sha256(p) for p in sorted(directory.glob("trigger-*"))}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qt-prefix", type=Path, required=True)
    parser.add_argument("--target-dir", type=Path, default=ROOT / "native/target/debug")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--language", choices=LANGUAGES, action="append")
    parser.add_argument("--all-inputs", action="store_true")
    parser.add_argument("--virtual-device", action="store_true")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--portable", action="store_true")
    args = parser.parse_args()
    if args.output.exists() or args.repeat < 1 or not np.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("new output directory and positive repeat/timeout required")
    if args.virtual_device and sys.platform != "darwin":
        parser.error("BlackHole validation requires macOS")
    env, version = qt_environment(args.qt_prefix)
    binaries = [
        args.target_dir.resolve() / (name + (".exe" if os.name == "nt" else ""))
        for name in ("cxxqt-display", "qtbridge-display")
    ]
    if not all(p.is_file() for p in binaries):
        parser.error("build both Qt display binaries first")
    manifest, manifest_hash = candidate.load_manifest(audio.core.DEFAULT_FIXTURES, portable=args.portable, is_core=True)
    if args.virtual_device:
        from scripts import migration_qt_live as live

        cases, runner = live.cases(), live.run_display
    else:
        cases, runner = manifest["tones"] if args.all_inputs else manifest["tones"][:1], run_display
    languages = args.language or (("en",) if args.virtual_device else LANGUAGES)
    args.output.mkdir(parents=True)
    runs = []
    for repeat in range(args.repeat):
        for language in languages:
            for case in cases:
                name = case["id"] if args.virtual_device else case["spec"]["id"]
                for binary in binaries:
                    run = runner(
                        binary,
                        env,
                        args.output / f"{repeat}-{language}-{name}-{binary.stem}",
                        case,
                        args.timeout,
                        language=language,
                        trigger=True,
                    )
                    runs.append(run)
                    print(
                        f"{binary.name} {language} {name}: {'PASS' if run['passed'] else 'FAIL'} {run['reason'] or ''}",
                        flush=True,
                    )
                    if not run["passed"]:
                        print(run["output"], flush=True)
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
                "qt_live",
                "qt_workspace",
                "qt_probe",
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
    report = {
        "schema_version": 1,
        "task": "MIG-007-A-trigger-delivery",
        "passed": all(r["passed"] for r in runs),
        "mode": "portable" if args.portable else "pinned-reference",
        "measurement_kind": "BlackHole_correctness_only" if args.virtual_device else "saved_input_correctness_only",
        "host": {"os": platform.system(), "release": platform.release(), "machine": platform.machine()},
        "qt_version": version,
        "fixture_manifest_sha256": manifest_hash,
        "source_sha256": {str(p.relative_to(ROOT)): sha256(p) for p in sorted(paths)},
        "runner_sha256": {str(p.relative_to(ROOT)): sha256(p) for p in helpers},
        "runs": runs,
        "limitations": [
            "manual sample events, no detector, arming or physical clock mapping",
            "one queued operation and one shared held capture",
            "short correctness checks, no load/long-duration/other-OS performance acceptance",
            "no product calibration/save compatibility or adoption decision",
        ],
    }
    fft.write_json(args.output / "report.json", report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
