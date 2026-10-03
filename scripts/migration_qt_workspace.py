"""MIG-007-A: detached view lifecycle and canonical translations in both Qt hosts.

Use immutable saved input, independent fixture comparisons and three real PNGs
per run. No device, implicit build, fixture update, or adoption decision.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import migration_core_reference as core  # noqa: E402
from scripts import migration_fft_candidate as candidate  # noqa: E402
from scripts import migration_fft_reference as fft  # noqa: E402
from scripts.migration_qt_display import inspect_png, qt_environment, run_display  # noqa: E402
from scripts.migration_qt_probe import sha256  # noqa: E402

LANGUAGES = ("en", "de", "es", "fr", "ja", "ko", "pt", "ru", "zh")
PREFIX = "migration.display."
LIFECYCLE = (
    "views_preserved",
    "tokens_preserved",
    "close_released",
    "other_continued",
    "last_close_stopped",
    "reopened_docked",
    "recreated_detached",
    "shutdown_detached",
)


def validate_workspace(output, language, image):
    records = re.findall(r"DISPLAY_WORKSPACE (.+)", output)
    if len(records) != 1 or f"DISPLAY_LANGUAGE {language}\n" not in output:
        raise fft.ReferenceError("missing or repeated workspace/language evidence")
    record = json.loads(records[0])
    catalog = {
        k: v
        for k, v in json.loads((ROOT / f"src/assets/lang/{language}.json").read_text()).items()
        if k.startswith(PREFIX)
    }
    if record["language"] != language or record["catalog"] != catalog:
        raise fft.ReferenceError("embedded translation catalog mismatch")
    if any(record.get(key) is not True for key in LIFECYCLE):
        raise fft.ReferenceError("incomplete detached lifecycle")
    for kind in ("main", "spectrum", "spectrogram"):
        pane = record[kind]
        minimum, size = pane["minimum"], pane["size"]
        if len(minimum) != 2 or len(size) != 2 or any(type(v) is not int or v <= 0 for v in minimum + size):
            raise fft.ReferenceError("invalid layout dimensions")
        if minimum[0] > 1180 or minimum[1] > 690 or any(a > b for a, b in zip(minimum, size, strict=True)):
            raise fft.ReferenceError("translated layout exceeds limit or actual size")
        title = "title" if kind == "main" else kind
        if pane["title"] != catalog[PREFIX + title]:
            raise fft.ReferenceError("translated window title mismatch")
        if kind != "main":
            expected_labels = {
                "heading": catalog[PREFIX + kind],
                "reset": catalog[PREFIX + "reset_zoom"],
                "detach": catalog[PREFIX + "dock"],
                "save": catalog[PREFIX + "save_image"],
            }
            if pane["labels"] != expected_labels or pane["buttons_fit"] is not True:
                raise fft.ReferenceError("translated control labels or clipping mismatch")
            pane["image"] = inspect_png(
                Path(str(image) + f".{kind}.png"), size=size, kind=kind, regions=pane["regions"]
            )
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qt-prefix", type=Path, required=True)
    parser.add_argument("--target-dir", type=Path, default=ROOT / "native/target/debug")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--language", choices=LANGUAGES, action="append")
    parser.add_argument("--all-inputs", action="store_true", help="all four 4/8ch f32/f64 fixtures")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--portable", action="store_true")
    args = parser.parse_args()
    if args.output.exists() or args.repeat < 1 or args.timeout <= 0:
        parser.error("new output directory and positive timeout/repeat required")
    env, version = qt_environment(args.qt_prefix)
    binaries = [
        args.target_dir.resolve() / (name + (".exe" if os.name == "nt" else ""))
        for name in ("cxxqt-display", "qtbridge-display")
    ]
    if not all(p.is_file() for p in binaries):
        parser.error("build both display hosts first")
    manifest, manifest_hash = candidate.load_manifest(core.DEFAULT_FIXTURES, portable=args.portable, is_core=True)
    cases = (
        manifest["tones"]
        if args.all_inputs
        else [
            case
            for case in manifest["tones"]
            if case["arrays"]["input"]["shape"][1] == 8 and case["spec"]["dtype"] == "<f8"
        ]
    )
    if not cases:
        parser.error("largest 8ch f64 fixture missing")
    languages = args.language or LANGUAGES
    args.output.mkdir(parents=True)
    runs = []
    for repeat in range(args.repeat):
        for language in languages:
            for case in cases:
                for binary in binaries:
                    directory = args.output / f"{repeat}-{language}-{case['spec']['id']}-{binary.stem}"
                    run = run_display(binary, env, directory, case, args.timeout, language=language, workspace=True)
                    runs.append(run)
                    print(
                        f"{language} {binary.stem} {case['spec']['id']}: {'PASS' if run['passed'] else 'FAIL'} {run['reason'] or ''}",
                        flush=True,
                    )
                    if not run["passed"]:
                        print(run["output"], flush=True)
    paths = [
        p
        for p in (ROOT / "native").rglob("*")
        if p.is_file() and "target" not in p.parts and p.suffix in (".rs", ".qml", ".toml", ".lock")
    ]
    paths += list((ROOT / "src/assets/lang").glob("*.json"))
    report = {
        "schema_version": 1,
        "task": "MIG-007-A-windows-i18n",
        "passed": all(r["passed"] for r in runs),
        "mode": "portable" if args.portable else "pinned-reference",
        "languages": list(languages),
        "measurement_kind": "saved_input_correctness_and_layout_only",
        "qt_version": version,
        "host": {"os": platform.system(), "release": platform.release(), "machine": platform.machine()},
        "fixture_manifest_sha256": manifest_hash,
        "runner_sha256": {p.name: sha256(p) for p in (Path(__file__), ROOT / "scripts/migration_qt_display.py")},
        "source_sha256": {str(p.relative_to(ROOT)): sha256(p) for p in sorted(paths)},
        "runs": runs,
        "limitations": [
            "offscreen/software/Basic; no physical window manager or other OS evaluation",
            "no trigger/calibration/product save UI or long duration performance",
            "language chosen at startup; no runtime language switch or package validation",
        ],
    }
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
