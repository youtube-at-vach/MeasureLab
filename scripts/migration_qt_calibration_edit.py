"""Qt profile edits during acquisition, immutable held results and independent bytes oracle.

Diagnostic gains only. No implicit build, expected arrays sent to Qt, fixture
regeneration, or product persistence. BlackHole is explicitly opt-in.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import platform
import re
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import migration_qt_calibration as calibration  # noqa: E402
from scripts import migration_qt_trigger as qt_trigger  # noqa: E402
from scripts.migration_qt_display import projection_for, qt_environment, run_display  # noqa: E402
from scripts.migration_qt_probe import sha256  # noqa: E402

audio, candidate, fft, trigger = calibration.audio, calibration.candidate, calibration.fft, calibration.trigger
LANGUAGES = calibration.LANGUAGES


def exact_qml(actual, expected, context):
    """JS JSON spells integral floats as integers. Normalize only expected float
    fields; preserve integer identity/position/revision types and exact values.
    """

    def normalize(value, reference):
        if type(reference) is float and type(value) in (int, float):
            return float(value)
        if isinstance(value, dict) and isinstance(reference, dict):
            return {k: normalize(v, reference.get(k)) for k, v in value.items()}
        if isinstance(value, list) and isinstance(reference, list) and len(value) == len(reference):
            return [normalize(v, r) for v, r in zip(value, reference, strict=True)]
        return value

    trigger.exact(normalize(actual, expected), expected, context)


def edited_profiles(request):
    """Independent expected ID replacements, unrelated to Qt's draft or receipts."""
    profiles = deepcopy(request["calibration"])
    first, last = request["format"]["input_ids"][0], request["format"]["input_ids"][-1]
    states = {"initial": deepcopy(profiles)}
    for name, channel, revision, factor, enabled in (
        ("edited", first, "edited.c0", 3.5, True),
        ("disabled", first, "disabled.c0", 3.5, False),
        ("added", last, "added.last", 5.0, True),
    ):
        index = request["format"]["input_ids"].index(channel)
        profiles = [p for p in profiles if p["channel_id"] != channel]
        profiles.append(
            {
                "channel_id": channel,
                "revision": revision,
                "v_per_fs": factor,
                "is_calibrated": enabled,
                "device_binding": {
                    "device": (request.get("live") or {}).get("device", "saved:" + request["format"]["stream_id"]),
                    "port": request["format"]["input_ports"][index],
                },
            }
        )
        states[name] = deepcopy(profiles)
    return states


def validate_ui(output, language):
    records = re.findall(r"DISPLAY_CALIBRATION_EDIT (.+)", output)
    if len(records) != 1 or f"DISPLAY_LANGUAGE {language}\n" not in output:
        raise fft.ReferenceError("missing calibration edit/language evidence")
    record = audio.core.read_json(records[0].encode())
    if any(record.get(k) is not True for k in ("shared_raw", "hold_immutable", "detached_hold", "restart", "recreate")):
        raise fft.ReferenceError("incomplete calibration edit lifecycle")
    if type(record.get("blocked_gui_fft")) is not int or record["blocked_gui_fft"] < 2:
        raise fft.ReferenceError("calibration edit blocked acquisition")
    editor = record["editor"]
    if editor["labels_fit"] is not True:
        raise fft.ReferenceError("clipped calibration editor labels")
    catalog = json.loads((ROOT / f"src/assets/lang/{language}.json").read_text())
    suffixes = {
        "title": "edit",
        "channel": "channel",
        "factor": "factor",
        "revision": "revision",
        "calibrated": "enabled",
        "apply": "apply",
        "close": "close",
        "note": "note",
        "status": "rejected",
    }
    trigger.exact(
        editor["labels"],
        {k: catalog["migration.display.calibration_" + v] for k, v in suffixes.items()},
        "translated calibration editor labels",
    )
    for size in (record["minimum"], record["size"], editor["size"]):
        if len(size) != 2 or any(type(v) not in (int, float) or not np.isfinite(v) or v <= 0 for v in size):
            raise fft.ReferenceError("invalid calibration UI geometry")
    for size in (record["minimum"], editor["size"]):
        if size[0] > 1180 or size[1] > 690:
            raise fft.ReferenceError("calibration UI size exceeds limit")
    if any(a > b for a, b in zip(record["minimum"], record["size"], strict=True)):
        raise fft.ReferenceError("calibration window smaller than its minimum")
    return record


def samples_for(path, request, case=None, *, start=0):
    n, channels = request["n"], len(request["format"]["input_ids"])
    dtype = "<f4" if request["precision"] == "F32" else "<f8"
    if case:
        source = audio.core.DEFAULT_FIXTURES / case["spec"]["id"]
        raw = audio.core.checked_file(source, case["arrays"]["input"])
        expected = np.roll(
            np.frombuffer(raw, dtype=dtype).reshape(n, channels)[:, request["format"]["input_ports"]],
            -start % n,
            axis=0,
        )
        if path is None:
            return expected
        if path.read_bytes() != expected.tobytes():
            raise fft.ReferenceError("calibration retained bytes differ from original input")
    if path is None:
        raise fft.ReferenceError("missing live calibration bytes")
    values = np.frombuffer(path.read_bytes(), dtype=dtype)
    if values.size != n * channels or not np.all(np.isfinite(values)):
        raise fft.ReferenceError("calibration bytes shape/nonfinite")
    samples = values.reshape(n, channels)
    if not case:
        from scripts.migration_qt_live import BINS

        peaks = np.abs(np.fft.rfft(samples.astype(float), axis=0)) * 2 / n
        if not np.array_equal(peaks.argmax(axis=0), BINS[:channels]) or not np.allclose(
            peaks[BINS[:channels], np.arange(channels)], np.arange(1, channels + 1) / 512, rtol=0, atol=1e-6
        ):
            raise fft.ReferenceError("calibration live tone/port mismatch")
    return samples


def validate_configurations(record, directory, request):
    generation = record["initial"]["generation"]
    bound = {**request, "format": {**request["format"], "generation": generation}}
    expected_profiles = edited_profiles(request)
    channels = [
        {
            "channel_id": c,
            "device_binding": {
                "device": (request.get("live") or {}).get("device", "saved:" + request["format"]["stream_id"]),
                "port": p,
            },
        }
        for c, p in zip(request["format"]["input_ids"], request["format"]["input_ports"], strict=True)
    ]
    for key, revision, status, profile_key in (
        ("initial", 0, "ready", "initial"),
        ("edited", 1, "applied", "edited"),
        ("rejected", 2, "rejected", "edited"),
        ("disabled", 3, "applied", "disabled"),
        ("added", 4, "applied", "added"),
    ):
        expected = {
            "schema_version": 1,
            "generation": generation,
            "revision": revision,
            "status": status,
            "reason": "display_calibration_binding" if status == "rejected" else None,
            "channels": channels,
            "profiles": expected_profiles[profile_key],
        }
        exact_qml(record[key], expected, "calibration applied configuration")
        if revision:
            path = directory / f"calibration-{generation}-{revision}.json"
            trigger.exact(audio.core.read_json(path.read_bytes()), expected, "owner edit receipt")
    if len(list(directory.glob(f"calibration-{generation}-*.json"))) != 7:
        raise fft.ReferenceError("missing or unexpected calibration edit evidence")
    return bound, expected_profiles


def validate_run(output, directory, request, language, case=None):
    record = validate_ui(output, language)
    bound, expected_profiles = validate_configurations(record, directory, request)
    generation = bound["format"]["generation"]
    comparisons = []
    for revision, state in ((1, "edited"), (3, "disabled"), (4, "added")):
        path = directory / f"calibration-{generation}-{revision}.result.json"
        document = audio.core.read_json(path.read_bytes())
        config = {**bound, "calibration": expected_profiles[state]}
        raw = path.with_suffix(".f32") if request.get("live") else None
        # Live files use the edit stem without the .result suffix.
        if raw:
            raw = directory / f"calibration-{generation}-{revision}.f32"
        values = samples_for(raw, config, case, start=document["interval"][0])
        comparisons.append(calibration.validate_result(document, config, values, case))
        calibration.validate_exchange(path)
    receipts = []
    for revision, state, field in (
        (1, "initial", "first"),
        (2, "edited", "updated"),
        (3, "disabled", "disabled_capture"),
        (4, "added", "added_capture"),
    ):
        stem = directory / f"trigger-{generation}-{revision}-complete"
        receipt = audio.core.read_json(stem.with_suffix(".json").read_bytes())
        config = {**bound, "calibration": expected_profiles[state]}
        qt_trigger.validate_receipt(receipt, config)
        exact_qml(record[field], receipt, "Qt trigger receipt matches owner evidence")
        document = audio.core.read_json(stem.with_suffix(".result.json").read_bytes())
        values = samples_for(stem.with_suffix(".bin"), config, case, start=receipt["history"]["interval"][0])
        rid = receipt["frame"]["raw_result_id"]
        read = {
            "history": receipt["history"],
            "raw_result_id": {"graph": rid[0], "serial": rid[1]},
            "result_id": receipt["frame"]["result_id"],
            "event": receipt["request"]["event"],
        }
        comparisons.append(calibration.validate_result(document, config, values, case, read=read))
        calibration.validate_exchange(stem.with_suffix(".result.json"))
        trigger.exact(receipt["frame"], projection_for(document), "edited trigger projection matches full result")
        receipts.append(receipt)
    first, updated = receipts[:2]
    if (
        first["frame"]["raw_result_id"] != updated["frame"]["raw_result_id"]
        or first["history"]["interval"] != updated["history"]["interval"]
        or first["trigger_evaluations"] != updated["trigger_evaluations"]
        or updated["fft_origin"] not in ("continuous-cache", "trigger-cache")
        or first["frame"]["peak_fs"] != updated["frame"]["peak_fs"]
    ):
        raise fft.ReferenceError("profile edit changed shared raw FFT")
    record["comparisons"] = comparisons
    return record


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
        parser.error("build both Qt displays first")
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
                        calibration=True,
                        calibration_edit=True,
                    )
                    runs.append(run)
                    print(
                        f"{binary.name} {language} {name}: {'PASS' if run['passed'] else 'FAIL'} {run['reason'] or ''}",
                        flush=True,
                    )
                    if not run["passed"]:
                        print(
                            "\n".join(
                                line for line in run["output"].splitlines() if "DISPLAY_CALIBRATION_EDIT {" not in line
                            )[-5000:],
                            flush=True,
                        )
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
                "qt_calibration",
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
            "task": "MIG-007-A-calibration-edit",
            "passed": all(r["passed"] for r in runs),
            "mode": "portable" if args.portable else "pinned-reference",
            "qt_version": version,
            "measurement_kind": "BlackHole_correctness_only" if args.virtual_device else "saved_input_correctness_only",
            "host": {"os": platform.system(), "release": platform.release(), "machine": platform.machine()},
            "fixture_manifest_sha256": manifest_hash,
            "source_sha256": {str(p.relative_to(ROOT)): sha256(p) for p in sorted(source)},
            "runner_sha256": {str(p.relative_to(ROOT)): sha256(p) for p in helpers},
            "runs": runs,
            "files_sha256": {
                str(p.relative_to(args.output)): sha256(p) for p in sorted(args.output.rglob("*")) if p.is_file()
            },
            "limitations": [
                "diagnostic factors, no physical calibration",
                "session edits reset on restart",
                "no product persistence/compatibility/async export",
                "no adoption/performance/other-OS acceptance",
            ],
        },
    )
    return 0 if all(r["passed"] for r in runs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
