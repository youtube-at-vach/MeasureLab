"""ID calibration of actual acquisition/trigger results through both Qt displays.

Diagnostic coefficients exercise the boundary; they are not physical calibration.
Independent NumPy checks use saved/captured bytes, with no expected arrays sent to Qt.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import csv
import io
import json
import os
from pathlib import Path
import platform
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import migration_audio_graph as audio  # noqa: E402
from scripts import migration_fft_candidate as candidate  # noqa: E402
from scripts import migration_fft_oracle as oracle  # noqa: E402
from scripts import migration_fft_reference as fft  # noqa: E402
from scripts import migration_trigger_candidate as trigger  # noqa: E402
from scripts.migration_qt_display import qt_environment, run_display  # noqa: E402
from scripts.migration_qt_probe import sha256  # noqa: E402
from scripts.migration_qt_workspace import LANGUAGES  # noqa: E402


def diagnostic_profiles(request):
    """Reversed profile order, distinct gains, disabled profile and missing profile."""
    fmt = request["format"]
    ids = fmt["input_ids"]
    device = request["live"]["device"] if request.get("live") else "saved:" + fmt["stream_id"]
    # Even 2ch uses one calibrated channel and one absent profile.
    return [
        {
            "channel_id": ids[i],
            "revision": f"diag.c{i}",
            "device_binding": {"device": device, "port": fmt["input_ports"][i]},
            "is_calibrated": len(ids) == 2 or i != len(ids) - 2,
            "v_per_fs": 2 + i / 4,
        }
        for i in reversed(range(len(ids) - 1))
    ]


def expected_calibration(request, interval):
    profiles = {
        p["channel_id"]: deepcopy({k: v for k, v in p.items() if k != "channel_id"}) for p in request["calibration"]
    }
    if len(profiles) != len(request["calibration"]):
        raise fft.ReferenceError("duplicate calibration ChannelId")
    return [
        {
            "channel_id": channel,
            "profile": {**profiles[channel], "applied_interval": interval} if channel in profiles else None,
            "application": "after_analysis",
        }
        for channel in request["format"]["input_ids"]
    ]


def validate_result(document, request, samples, case=None, *, read=None):
    """Verify all relative arrays first, then absolute values from the original bytes."""
    rid = document["raw_result_id"]
    if not isinstance(rid, list) or len(rid) != 2 or any(type(v) is not int or v <= 0 for v in rid):
        raise fft.ReferenceError("invalid calibration raw result ID")
    if read is None:
        if document["capture"]["result_id"] != f"{rid[0]}:{rid[1]}":
            raise fft.ReferenceError("invalid continuous calibrated result ID")
        read = {
            "history": {"interval": document["interval"]},
            "raw_result_id": {"graph": rid[0], "serial": rid[1]},
            "result_id": document["capture"]["result_id"],
            "event": None,
        }
    case = case or {"spec": {"rate_hz": 48000, "window": "boxcar"}}
    profiles = expected_calibration(request, document["interval"])
    trigger.exact(document["calibration"], profiles, "session calibration identity/binding/revision/interval")
    # The existing uncalibrated oracle still checks every relative column and all
    # provenance. Only the independently verified calibration/absolute columns
    # are normalized to its uncalibrated baseline; tolerances are unchanged.
    baseline = deepcopy(document)
    baseline["calibration"] = [
        {"channel_id": c, "profile": None, "application": "after_analysis"} for c in request["format"]["input_ids"]
    ]
    absolute_names = ("rms_v", "dbv", "psd_v2_hz", "spl")
    for name in absolute_names:
        column = baseline["columns"][name]
        count = int(np.prod(column["shape"]))
        column["values"], column["reasons"] = [None] * count, ["uncalibrated"] * count
    comparisons = trigger.validate_document(baseline, read, request, case, samples, alignment=0)
    n = request["n"]
    window = oracle.window_values(n, case["spec"]["window"])
    transformed = np.fft.rfft(samples.astype(float) * window[:, None], axis=0) / n
    quantities = oracle.quantities(transformed, window, samples, case["spec"]["rate_hz"])
    channels = len(profiles)
    calibrated = np.asarray([bool(p["profile"] and p["profile"]["is_calibrated"]) for p in profiles])
    factors = np.asarray([p["profile"]["v_per_fs"] if p["profile"] else 1.0 for p in profiles])
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        voltage = quantities["rms_fs"] * factors
        absolute = {
            "rms_v": voltage,
            "dbv": 20 * np.log10(voltage),
            "psd_v2_hz": quantities["psd_fs2_hz"] * factors**2,
            "spl": np.full(channels, np.nan),
        }
    tolerance = fft.TOLERANCES["f32" if request["precision"] == "F32" else "f64"]
    for name, values in absolute.items():
        column = document["columns"][name]
        valid, expected, reasons = [], [], []
        for i, value in enumerate(values.ravel()):
            reason = None
            if name == "spl" or not calibrated[i % channels]:
                reason = "uncalibrated"
            elif name == "dbv" and voltage[i] <= 0:
                reason = "nonpositive"
            elif not np.isfinite(value):
                reason = "nonfinite"
            reasons.append(reason)
            expected.append(None if reason else float(value))
            valid.append(reason is None)
        trigger.exact(column["reasons"], reasons, f"calibrated {name} reasons")
        if len(column["values"]) != len(expected) or any(
            (a is None) != (b is None) or a is not None and (type(a) not in (int, float) or not np.isfinite(a))
            for a, b in zip(column["values"], expected, strict=True)
        ):
            raise fft.ReferenceError("calibrated null/value mismatch")
        if any(valid):
            comparisons[name] = fft.compare(
                np.asarray(column["values"], dtype=float)[valid],
                np.asarray(expected, dtype=float)[valid],
                tolerance,
                f"calibrated {name}",
            )
    return comparisons


def validate_exchange(path):
    """Independent CSV parser requires every value and metadata to match JSON exactly."""
    document = audio.core.read_json(path.read_bytes())
    rows = list(csv.reader(io.StringIO(path.with_suffix(".csv").read_text(), newline=""), strict=True))
    if (
        len(rows) < 3
        or len(rows[0]) != 2
        or rows[0][0] != "# MIG-006-E exchange v1"
        or rows[1] != ["metric", "index", "value", "reason"]
    ):
        raise fft.ReferenceError("calibration CSV schema mismatch")
    reread = audio.core.read_json(rows[0][1])
    for column in reread["columns"].values():
        if column["values"] or column["reasons"]:
            raise fft.ReferenceError("calibration CSV metadata contains payload")
    for row in rows[2:]:
        if len(row) != 4 or row[0] not in reread["columns"]:
            raise fft.ReferenceError("calibration CSV row mismatch")
        column = reread["columns"][row[0]]
        if row[1] != str(len(column["values"])):
            raise fft.ReferenceError("calibration CSV order mismatch")
        value, reason = float(row[2]) if row[2] else None, row[3] or None
        if (value is None) != (reason is not None) or value is not None and not np.isfinite(value):
            raise fft.ReferenceError("calibration CSV null/reason mismatch")
        column["values"].append(value)
        column["reasons"].append(reason)
    trigger.exact(reread, document, "calibration CSV/JSON roundtrip")
    return {p.name: sha256(p) for p in (path, path.with_suffix(".csv"))}


def validate_ui(record, directory, language):
    observed = record.get("calibration")
    if not isinstance(observed, dict) or observed.get("labels_fit") is not True:
        raise fft.ReferenceError("missing calibration UI or clipped labels")
    results = [audio.core.read_json(p.read_bytes()) for p in directory.glob("trigger-*-complete.result.json")]
    matches = [d for d in results if d["capture"]["result_id"] == observed["result_id"]]
    if len(matches) != 1:
        raise fft.ReferenceError("calibration labels have no immutable result")
    document = matches[0]
    catalog = json.loads((ROOT / f"src/assets/lang/{language}.json").read_text())

    def substitute(key, *values):
        text = catalog["migration.display." + key]
        for i, value in enumerate(values, 1):
            text = text.replace(f"%{i}", str(value))
        return text

    for kind, index in (("spectrum", 0), ("spectrogram", len(document["calibration"]) - 1)):
        profile = document["calibration"][index]["profile"]
        voltage = document["columns"]["rms_v"]["values"][index]
        dbv = document["columns"]["dbv"]["values"][index]
        # QML's Number.toPrecision(8) and Python's .8g only differ for scientific
        # notation/trailing zero spelling. Compare numeric text separately.
        if voltage is None:
            trigger.exact(
                observed[kind],
                {"channel": index, "voltage": substitute("voltage_uncalibrated"), "profile": ""},
                "uncalibrated translated label",
            )
        else:
            pane = observed[kind]
            if pane["channel"] != index or profile is None:
                raise fft.ReferenceError("calibration displayed channel mismatch")
            import re

            for key, field, values in (
                ("voltage", "voltage", [voltage, dbv]),
                (
                    "calibration_profile",
                    "profile",
                    [profile["v_per_fs"], profile["revision"], profile["device_binding"]["port"]],
                ),
            ):
                template = re.escape(catalog["migration.display." + key])
                for i in range(1, len(values) + 1):
                    template = template.replace(f"%{i}", "(.+?)")
                match = re.fullmatch(template, pane[field])
                if not match:
                    raise fft.ReferenceError("calibration translated label mismatch")
                for actual, expected in zip(match.groups(), values, strict=True):
                    if isinstance(expected, str):
                        if actual != expected:
                            raise fft.ReferenceError("calibration displayed revision mismatch")
                    elif not np.isclose(float(actual), expected, rtol=5e-8, atol=1e-12):
                        raise fft.ReferenceError("calibration displayed value mismatch")
    return observed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qt-prefix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-dir", type=Path, default=ROOT / "native/target/debug")
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
        parser.error("BlackHole requires macOS")
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
                        calibration=True,
                    )
                    runs.append(run)
                    print(
                        f"{binary.name} {language} {name}: {'PASS' if run['passed'] else 'FAIL'} {run['reason'] or ''}",
                        flush=True,
                    )
                    if not run["passed"]:
                        print(run["output"], flush=True)
    source = [
        p
        for p in (ROOT / "native").rglob("*")
        if p.is_file() and "target" not in p.parts and p.suffix in (".rs", ".qml", ".toml", ".lock")
    ]
    source += sorted((ROOT / "src/assets/lang").glob("*.json"))
    helpers = [
        Path(__file__),
        *(
            ROOT / "scripts" / f"migration_{name}.py"
            for name in (
                "qt_display",
                "qt_trigger",
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
    fft.write_json(
        args.output / "report.json",
        {
            "schema_version": 1,
            "task": "MIG-007-A-calibration-input",
            "passed": all(r["passed"] for r in runs),
            "mode": "portable" if args.portable else "pinned-reference",
            "measurement_kind": "BlackHole_correctness_only" if args.virtual_device else "saved_input_correctness_only",
            "host": {"os": platform.system(), "release": platform.release(), "machine": platform.machine()},
            "qt_version": version,
            "fixture_manifest_sha256": manifest_hash,
            "source_sha256": {str(p.relative_to(ROOT)): sha256(p) for p in sorted(source)},
            "runner_sha256": {str(p.relative_to(ROOT)): sha256(p) for p in helpers},
            "runs": runs,
            "files_sha256": {
                str(p.relative_to(args.output)): sha256(p) for p in sorted(args.output.rglob("*")) if p.is_file()
            },
            "limitations": [
                "diagnostic factors, no physical calibration",
                "session input only, no Qt profile editing/apply",
                "v1 diagnostic exchange, no product save UI/compatibility/async worker",
                "no frequency/phase/SPL map or adoption/performance/other-OS acceptance",
            ],
        },
    )
    return 0 if all(r["passed"] for r in runs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
