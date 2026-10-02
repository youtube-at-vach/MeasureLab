"""MIG-007-A-product-import: both Qt readers, original values and owned snapshots.

Saved input correctness only. No audio devices or implicit fixture regeneration.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from contextlib import ExitStack
import multiprocessing
from pathlib import Path
import json
import os
import platform
import re
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import migration_product_candidate as compatibility  # noqa: E402
from scripts import migration_product_exchange as product  # noqa: E402
from scripts import migration_qt_calibration as calibration  # noqa: E402
from scripts import migration_qt_calibration_edit as edit  # noqa: E402
from scripts.migration_qt_display import projection_for, qt_environment, run_display  # noqa: E402
from scripts.migration_qt_probe import sha256  # noqa: E402

fft, audio, trigger = calibration.fft, calibration.audio, calibration.trigger
LANGUAGES = calibration.LANGUAGES


def prepare_inputs(directory):
    from src.core.export.csv_exporter import CsvTraceExporter
    from src.core.export.trace import ExportTrace

    directory.mkdir()
    document = compatibility.legacy_document()
    product.save_json(directory / "legacy.json", document)
    product.save_csv_pair(directory / "legacy.csv", document)
    spec = product.csv_spec(document, layout="merged", delimiter="tab", utf8_bom=True)
    fft.write_json(directory / "merged.spec.json", spec)
    if not CsvTraceExporter().export_traces(
        str(directory / "merged.csv"), [ExportTrace.from_dict(t) for t in document["traces"]], spec["options"]
    ):
        raise fft.ReferenceError("actual merged CSV exporter failed")
    (directory / "broken.json").write_text('{"version":"1.0","traces":[')
    return {str(p): sha256(p) for p in directory.iterdir()}


def preview_for(imported):
    traces = imported.document["traces"]
    budget = min(256, max(2, 8192 // (3 * max(1, len(traces)))))
    previews = []
    for t in traces:
        n = len(t["x_data"])
        count = min(n, budget)
        indexes = [0 if count <= 1 else i * (n - 1) // (count - 1) for i in range(count)]
        axes = {
            key: None if t[key] is None else {k: v[:256] if isinstance(v, str) else v for k, v in t[key].items()}
            for key in ("x_axis", "y_axis", "y2_axis")
        }
        previews.append(
            {
                **{key: t[key][:256] for key in ("id", "name", "source_module", "timestamp")},
                **axes,
                "is_calibrated": t["calibration"]["is_calibrated"],
                "original_count": n,
                "rows": [
                    {
                        "index": i,
                        "x": t["x_data"][i],
                        "y": t["y_data"][i],
                        "y2": t["y2_data"][i] if t["y2_data"] is not None else None,
                    }
                    for i in indexes
                ],
            }
        )
    return {
        "has_snapshot": imported.snapshot is not None,
        "sample_relation": imported.sample_relation,
        "invalid_spans": len(imported.snapshot["validity"]) if imported.snapshot is not None else None,
        "error": imported.snapshot["error"] if imported.snapshot is not None else None,
        "traces": previews,
    }


def validate_preview(actual, imported):
    """Qt must keep decimal tokens verbatim, including negative zero."""
    from copy import deepcopy

    decoded = deepcopy(actual)
    for trace in decoded["traces"]:
        for row in trace["rows"]:
            for key in ("x", "y", "y2"):
                token = row[key]
                if token is None and key == "y2":
                    continue
                if (
                    not isinstance(token, str)
                    or re.fullmatch(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?", token) is None
                ):
                    raise fft.ReferenceError("numeric preview lost its original decimal token")
                row[key] = float(token)
    trigger.exact(decoded, preview_for(imported), "sampled original display values and signed zero")


def validate_ui(record, language):
    catalog = json.loads((ROOT / f"src/assets/lang/{language}.json").read_text())
    expected = {
        key: catalog["migration.display." + suffix]
        for key, suffix in {
            "title": "import_open",
            "path": "import_path",
            "spec": "import_spec",
            "trace": "import_trace",
            "note": "import_note",
            "read": "import_open",
            "cancel": "import_cancel",
            "close": "calibration_close",
            "status": "import_loaded",
            "provenance": "import_unknown",
            "relation": "import_original",
        }.items()
    }
    trigger.exact(record["dialog"]["labels"], expected, "translated import dialog")
    trigger.exact(
        record["states"],
        {key: catalog["migration.display.import_" + key] for key in ("failed", "rejected", "closed")},
        "translated reader outcome",
    )
    if (
        record["lifecycle"] is not True
        or record["dialog"]["labels_fit"] is not True
        or type(record["blocked_gui_fft"]) is not int
        or record["blocked_gui_fft"] < 2
    ):
        raise fft.ReferenceError("incomplete import lifecycle/UI or blocked acquisition")
    for size in (record["minimum"], record["size"], record["dialog"]["size"]):
        if len(size) != 2 or any(type(v) not in (int, float) or not 0 < v < float("inf") for v in size):
            raise fft.ReferenceError("invalid import geometry")
    if any(s[0] > 1180 or s[1] > 690 for s in (record["minimum"], record["dialog"]["size"])) or any(
        a > b for a, b in zip(record["minimum"], record["size"], strict=True)
    ):
        raise fft.ReferenceError("import UI exceeds size limit")


def validate_run(output, directory, imports, input_hashes, request, language, case):
    matches = re.findall(r"DISPLAY_IMPORT (.+)", output)
    if (
        len(matches) != 1
        or f"DISPLAY_LANGUAGE {language}\n" not in output
        or "DISPLAY_IMPORT_TEARDOWN sessions=0" not in output
    ):
        raise fft.ReferenceError("missing import lifecycle/language evidence")
    record = audio.core.read_json(matches[0].encode())
    validate_ui(record, language)
    if not (directory / "display.png.import.png").is_file():
        raise fft.ReferenceError("missing actual import dialog image")
    if any(sha256(Path(p)) != digest for p, digest in input_hashes.items()):
        raise fft.ReferenceError("import changed a source file or descriptor")
    retired = [audio.core.read_json(v.encode()) for v in re.findall(r"DISPLAY_IMPORT_RETIRED (.+)", output)]
    if len(retired) != 2 or any(r["error"] is not None for r in retired):
        raise fft.ReferenceError("reader retirement failure")
    old = next((r["receipts"] for r in retired if len(r["receipts"]) == 7), None)
    new = next((r["receipts"] for r in retired if len(r["receipts"]) == 1), None)
    if old is None or new is None:
        raise fft.ReferenceError("reader session/receipt count mismatch")
    edit.exact_qml(old, record["retiring"]["receipts"], "GUI/retired import receipts")
    receipts = old + new
    ids = [r["operation_id"] for r in receipts]
    if any(type(i) is not int or i <= 0 for i in ids) or ids != sorted(set(ids)):
        raise fft.ReferenceError("stale or duplicate import operation identity")
    if (
        record["retiring"]["closed"] is not True
        or record["retiring"]["preview"] is not None
        or record["teardown"]["latest"] != ids[-1]
    ):
        raise fft.ReferenceError("old request/close/recreation fence failed")
    names = [
        "legacy.json",
        "legacy.csv",
        "merged.csv",
        "broken.json",
        "snapshot.json",
        "snapshot.csv",
        "legacy.json",
        "legacy.json",
    ]
    formats = [
        "product_json",
        "product_csv",
        "csv_spec",
        "product_json",
        "product_json",
        "product_csv",
        "product_json",
        "product_json",
    ]
    successful = []
    for i, (r, name, fmt) in enumerate(zip(receipts, names, formats, strict=True)):
        state = r["status"]["state"]
        expected = "failed" if i == 3 else "loaded" if i < 6 else None
        if (
            r["path"] != str(imports / name)
            or r["format"] != fmt
            or state not in ((expected,) if expected else ("loaded", "cancelled"))
        ):
            raise fft.ReferenceError("import receipt/source/completion mismatch")
        if r["spec"] != (str(imports / "merged.spec.json") if fmt == "csv_spec" else None):
            raise fft.ReferenceError("implicit CSV descriptor")
        artifact = directory / "imported" / f"import-{r['operation_id']}.json"
        if (state == "loaded") != artifact.is_file():
            raise fft.ReferenceError("admission/receipt is not validated import completion")
        if state == "loaded":
            successful.append((i, r, artifact))
    trigger.exact(record["failure"], old[3], "actual failure receipt")
    codec = product.NativeCodec(
        directory.parent / "binaries" / ("result-candidate.exe" if os.name == "nt" else "result-candidate")
    )
    comparisons = []
    seen = {}
    for i, receipt, artifact in successful:
        path = Path(receipt["path"])
        imported = (
            product.import_json(product.read_file(path), codec)
            if receipt["format"] == "product_json"
            else product.import_csv(
                product.read_file(path), audio.core.read_json(product.read_file(Path(receipt["spec"])))
            )
            if receipt["format"] == "csv_spec"
            else product.load_csv_pair(path, codec)
        )
        loaded = audio.core.read_json(artifact.read_bytes())
        trigger.exact(
            loaded,
            {
                "document": imported.document,
                "snapshot": imported.snapshot,
                "acquisition": imported.acquisition,
                "sample_relation": imported.sample_relation,
            },
            "all original arrays/metadata/provenance",
        )
        if i < 6:
            entry = record["imports"][i if i < 3 else i - 1]
            edit.exact_qml(entry["receipt"], receipt, "presented operation identity")
            validate_preview(entry["preview"], imported)
        if imported.snapshot is not None:
            document = imported.snapshot
            edit.exact_qml(record["normal"], projection_for(document), "full imported original snapshot")
            if seen:
                trigger.exact(document, seen, "JSON/CSV complete snapshot identity")
            else:
                bound = {**request, "format": {**request["format"], "generation": document["source"]["generation"]}}
                samples = edit.samples_for(None, bound, case, start=document["interval"][0])
                comparisons.append(calibration.validate_result(document, bound, samples, case))
            seen = document
    expected_files = {p for _, _, p in successful}
    if set((directory / "imported").glob("*")) != expected_files:
        raise fft.ReferenceError("unexpected stale import artifact")
    record.update(retired=retired, comparisons=comparisons, input_sha256=input_hashes)
    return record


def exercise(arguments):
    binary, env, directory, case, timeout, language = arguments
    return run_display(binary, env, directory, case, timeout, language=language, calibration=True, importing=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qt-prefix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-dir", type=Path, default=ROOT / "native/target/debug")
    parser.add_argument("--language", choices=LANGUAGES, action="append")
    parser.add_argument("--all-inputs", action="store_true")
    parser.add_argument(
        "--jobs", type=int, choices=(1, 2), default=1, help="isolated correctness processes; not performance samples"
    )
    parser.add_argument("--portable", action="store_true")
    parser.add_argument("--timeout", type=float, default=150)
    args = parser.parse_args()
    if args.output.exists() or not 0 < args.timeout < float("inf"):
        parser.error("new output directory and positive finite timeout required")
    env, version = qt_environment(args.qt_prefix)
    names = ["cxxqt-display", "qtbridge-display", "result-candidate"]
    original = [args.target_dir.resolve() / (n + (".exe" if os.name == "nt" else "")) for n in names]
    if not all(p.is_file() for p in original):
        parser.error("build both Qt displays and result-candidate first")
    manifest, manifest_hash = calibration.candidate.load_manifest(
        audio.core.DEFAULT_FIXTURES, portable=args.portable, is_core=True
    )
    args.output.mkdir(parents=True)
    fixed = args.output.resolve() / "binaries"
    fixed.mkdir()
    for p in original:
        shutil.copy2(p, fixed / p.name)
    started = time.monotonic()
    work = [
        (
            fixed / (name + (".exe" if os.name == "nt" else "")),
            env,
            args.output / f"{language}-{case['spec']['id']}-{name}",
            case,
            args.timeout,
            language,
        )
        for language in args.language or LANGUAGES
        for case in (manifest["tones"] if args.all_inputs else manifest["tones"][:1])
        for name in names[:2]
    ]
    runs = []
    with ExitStack() as stack:
        pool = (
            stack.enter_context(
                ProcessPoolExecutor(max_workers=args.jobs, mp_context=multiprocessing.get_context("spawn"))
            )
            if args.jobs > 1
            else None
        )
        results = pool.map(exercise, work) if pool else map(exercise, work)
        for run in results:
            runs.append(run)
            print(
                f"{run['binary']} {run['case']}: {'PASS' if run['passed'] else 'FAIL'} {run['reason'] or ''}",
                flush=True,
            )
            if not run["passed"]:
                print(
                    "\n".join(line for line in run["output"].splitlines() if "DISPLAY_IMPORT {" not in line)[-5000:],
                    flush=True,
                )
    paths = [
        p
        for p in (ROOT / "native").rglob("*")
        if p.is_file() and "target" not in p.parts and p.suffix in (".rs", ".qml", ".toml", ".lock")
    ]
    paths += sorted((ROOT / "src/assets/lang").glob("*.json"))
    paths += [
        *sorted((ROOT / "scripts").glob("migration_*.py")),
        *sorted((ROOT / "src/core/export").glob("*.py")),
        ROOT / "src/core/localization.py",
        ROOT / "src/core/utils.py",
    ]
    fft.write_json(
        args.output / "report.json",
        {
            "schema_version": 1,
            "task": "MIG-007-A-product-import",
            "passed": all(r["passed"] for r in runs),
            "duration_seconds": time.monotonic() - started,
            "qt_version": version,
            "host": {"os": platform.system(), "release": platform.release(), "machine": platform.machine()},
            "measurement_kind": "saved_input_correctness_only",
            "execution_parallelism": args.jobs,
            "fixture_manifest_sha256": manifest_hash,
            "source_sha256": {str(p.relative_to(ROOT)): sha256(p) for p in sorted(paths)},
            "runs": runs,
            "files_sha256": {
                str(p.relative_to(args.output)): sha256(p) for p in sorted(args.output.rglob("*")) if p.is_file()
            },
            "limitations": [
                "sampled reference table; imported snapshot not connected to live line/heatmap",
                "two-job bound, no process byte/RSS budget",
                "no hardware, long-run/load, manual window manager or other-OS acceptance",
                "acquisition profile persistence pending",
            ],
        },
    )
    return 0 if all(r["passed"] for r in runs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
