"""MIG-007-A: saved acquisition bytes -> shared FFT -> both Qt line/heatmap adapters.

No implicit build, fixture regeneration, audio device, or PyQt import. The native
worker records full results; the runner checks them against independent fixtures.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import re
import struct
import subprocess
import sys
import time
import tomllib
import zlib

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import migration_audio_graph as audio  # noqa: E402
from scripts import migration_core_reference as core  # noqa: E402
from scripts import migration_fft_candidate as candidate  # noqa: E402
from scripts import migration_fft_reference as fft  # noqa: E402
from scripts.migration_qt_probe import sha256  # noqa: E402

PASS = "DISPLAY_PASS shared cursor zoom immutable slow_gui cancel failure stale views session recreate image shutdown"


def plot_regions(output):
    records = re.findall(r"DISPLAY_PLOT_REGIONS (.+)", output)
    if len(records) != 1:
        raise fft.ReferenceError("missing or repeated rendered plot regions")
    return json.loads(records[0])


def inspect_png(path, *, size=(1000, 640), kind="both", regions=None):
    """Check PNG integrity and visible plot pixels without loading a GUI runtime."""
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise fft.ReferenceError("invalid PNG signature")
    pos, compressed, header = 8, bytearray(), None
    while pos < len(data):
        chunk_size = struct.unpack_from(">I", data, pos)[0]
        chunk_kind, payload = data[pos + 4 : pos + 8], data[pos + 8 : pos + 8 + chunk_size]
        crc = struct.unpack_from(">I", data, pos + 8 + chunk_size)[0]
        if zlib.crc32(chunk_kind + payload) != crc:
            raise fft.ReferenceError("PNG CRC mismatch")
        if chunk_kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", payload)
        elif chunk_kind == b"IDAT":
            compressed.extend(payload)
        pos += 12 + chunk_size
    if header is None:
        raise fft.ReferenceError("missing PNG header")
    width, height, bits, color, _, _, interlace = header
    if (width, height) != tuple(size) or bits != 8 or color not in (2, 6) or interlace != 0:
        raise fft.ReferenceError(f"unexpected evaluation image format: {header}")
    bpp = 3 if color == 2 else 4
    packed = zlib.decompress(compressed)
    stride = width * bpp
    if len(packed) != (stride + 1) * height:
        raise fft.ReferenceError("PNG pixel shape mismatch")
    previous = bytearray(stride)
    pixels = []
    for y in range(height):
        offset = y * (stride + 1)
        method = packed[offset]
        row = bytearray(packed[offset + 1 : offset + stride + 1])
        for x in range(stride):
            left = row[x - bpp] if x >= bpp else 0
            up = previous[x]
            corner = previous[x - bpp] if x >= bpp else 0
            if method == 1:
                predictor = left
            elif method == 2:
                predictor = up
            elif method == 3:
                predictor = (left + up) // 2
            elif method == 4:
                base = left + up - corner
                distances = [abs(base - v) for v in (left, up, corner)]
                predictor = (left, up, corner)[distances.index(min(distances))]
            elif method == 0:
                predictor = 0
            else:
                raise fft.ReferenceError("unknown PNG filter")
            row[x] = (row[x] + predictor) % 256
        pixels.append(np.frombuffer(row, dtype=np.uint8).reshape(width, bpp)[:, :3].astype(int))
        previous = row
    rgb = np.stack(pixels)
    line, heat = rgb[215:510, 68:468], rgb[215:530, 545:974]
    if kind != "both":
        line = heat = rgb[60 : height - 90, 52 : width - 12]
    if regions is not None:

        def crop(name):
            region = regions[name]
            if len(region) != 4 or any(type(v) is not int for v in region):
                raise fft.ReferenceError("invalid plot region")
            x, y, w, h = region
            if min(x, y) < 0 or min(w, h) <= 0 or x + w > width or y + h > height:
                raise fft.ReferenceError("plot region outside image")
            return rgb[y : y + h, x : x + w]

        if kind == "both":
            line, heat = crop("spectrum"), crop("spectrogram")
            a, b = regions["spectrum"], regions["spectrogram"]
            if a[0] + a[2] > b[0] and b[0] + b[2] > a[0]:
                raise fft.ReferenceError("overlapping spectrum and spectrogram regions")
        else:
            line = heat = crop(kind)
    cyan = int(np.count_nonzero((line[:, :, 1] - line[:, :, 0] > 60) & (line[:, :, 2] > 100)))
    colored = int(np.count_nonzero((np.ptp(heat, axis=2) > 50) & (np.max(heat, axis=2) > 90)))
    if (kind in ("both", "spectrum") and cyan < 20) or (kind in ("both", "spectrogram") and colored < 20):
        raise fft.ReferenceError("PNG missing rendered spectrum or heatmap")
    return {
        "width": width,
        "height": height,
        "cyan_line_pixels": cyan,
        "heatmap_pixels": colored,
        "sha256": sha256(path),
    }


def validate_evidence(directory, case, *, count=3, request=None):
    paths = sorted(directory.glob("generation-*.json"))
    if len(paths) != count:
        raise fft.ReferenceError(f"expected {count} recorded running generations, got {len(paths)}")
    n = case["spec"]["n"]
    channels = case["arrays"]["input"]["shape"][1]
    source = core.DEFAULT_FIXTURES / case["spec"]["id"]
    precision = "f32" if case["spec"]["dtype"] == "<f4" else "f64"
    observed = []
    generations = set()
    for path in paths:
        document = json.loads(path.read_bytes())
        generation = document["source"]["generation"]
        generations.add(generation)
        expected = audio.expected_source(request or audio.request_for(case))
        expected["generation"] = expected["timebase"]["generation"] = generation
        if (
            document["source"] != expected
            or document["interval"] != [0, n]
            or document["validity"]
            or document["error"]
        ):
            raise fft.ReferenceError("recorded source/interval/validity mismatch")
        if document["axis"]["unit"] != "Hz" or document["columns"]["peak_fs"]["shape"] != [n // 2 + 1, channels]:
            raise fft.ReferenceError("recorded axis/shape mismatch")
        fft.compare(
            np.asarray(document["axis"]["corrected"]),
            fft.read_array(source, case["arrays"]["theory.frequency_hz"]),
            fft.TOLERANCES["window"],
            "display frequency axis",
        )
        values = np.asarray(document["columns"]["peak_fs"]["values"]).reshape(n // 2 + 1, channels)
        comparisons = {
            origin: fft.compare(
                values,
                fft.read_array(source, case["arrays"][f"{origin}.peak_fs"])[
                    :, request["format"]["input_ports"] if request else list(range(channels))
                ],
                fft.TOLERANCES[precision],
                f"display {origin} peak",
            )
            for origin in ("theory", "current")
        }
        if request and request.get("calibration"):
            from scripts.migration_qt_calibration import validate_result, validate_exchange

            samples = fft.read_array(source, case["arrays"]["input"])[..., request["format"]["input_ports"]]
            bound = {**request, "format": {**request["format"], "generation": generation}}
            comparisons.update(validate_result(document, bound, samples, case))
            validate_exchange(path)
        elif any(v is not None for v in document["columns"]["rms_v"]["values"]) or any(
            r != "uncalibrated" for r in document["columns"]["rms_v"]["reasons"]
        ):
            raise fft.ReferenceError("uncalibrated voltage shown as numeric")
        observed.append(
            {"file": path.name, "sha256": sha256(path), "generation": generation, "comparisons": comparisons}
        )
    if len(generations) != count:
        raise fft.ReferenceError("repeated generation in evidence")
    return observed


def run_display(
    binary,
    env,
    directory,
    case,
    timeout,
    *,
    language="en",
    workspace=False,
    trigger=False,
    calibration=False,
    calibration_edit=False,
):
    directory.mkdir(parents=True, exist_ok=False)
    evidence = directory / "results"
    evidence.mkdir()
    request = audio.request_for(case)
    source = core.DEFAULT_FIXTURES / case["spec"]["id"]
    core.load_tone(core.DEFAULT_FIXTURES, case)
    core.checked_file(source, case["arrays"]["input"])
    body = {k: request[k] for k in ("format", "precision", "n", "window")}
    body.update(input=str(source / case["arrays"]["input"]["file"]), evidence=str(evidence.resolve()))
    if calibration:
        from scripts.migration_qt_calibration import diagnostic_profiles

        body["format"]["input_ports"].reverse()
        body["calibration"] = diagnostic_profiles(body)
    request_path = directory / "request.json"
    request_path.write_text(json.dumps(body) + "\n")
    child_env = {**env, "MEASURELAB_DISPLAY_REQUEST": str(request_path.resolve())}
    image = directory.resolve() / "display.png"
    command = [str(binary), "--self-test", "--snapshot", str(image), "--language", language]
    if workspace:
        command.append("--workspace-test")
    if trigger:
        command.append("--trigger-test")
    if calibration:
        command += ["--calibration-test", "1"]
    if calibration_edit:
        command.append("--calibration-edit-test")
    started = time.monotonic()
    try:
        result = subprocess.run(  # noqa: S603 - explicit local evaluation binary
            command, cwd=ROOT, env=child_env, capture_output=True, text=True, timeout=timeout, check=False
        )
        code, output = result.returncode, result.stdout + result.stderr
        reason = None
    except subprocess.TimeoutExpired as exc:
        code = None
        output = "".join(
            v.decode(errors="replace") if isinstance(v, bytes) else v or "" for v in (exc.stdout, exc.stderr)
        )
        reason = "timeout"
    errors = (
        "DISPLAY_FAIL",
        "TypeError:",
        "ReferenceError:",
        "QQmlApplicationEngine failed",
        "Cannot assign",
        "is not a function",
        "Binding loop",
        "Required property",
        "Unable to assign",
        "QString::arg: Argument missing",
    )
    passed = (
        code == 0
        and all(
            m in output
            for m in (
                "DISPLAY_READY",
                "DISPLAY_CALIBRATION_EDIT_PASS" if calibration_edit else "DISPLAY_TRIGGER_PASS" if trigger else PASS,
                "DISPLAY_IMAGE_OK",
                "DISPLAY_TEARDOWN workers=0 models=0",
            )
        )
        and not any(e in output for e in errors)
    )
    details = {}
    if passed:
        try:
            if calibration_edit:
                from scripts.migration_qt_calibration_edit import validate_run

                details["edit"] = validate_run(output, evidence, body, language, case)
                if not image.with_suffix(".png.editor.png").is_file():
                    raise fft.ReferenceError("missing calibration editor image")
            if workspace:
                from scripts.migration_qt_workspace import validate_workspace

                details["workspace"] = validate_workspace(output, language, image)
            if trigger:
                from scripts.migration_qt_trigger import validate_ui, validate_captures

                details["trigger"] = validate_ui(output, language)
                details["captures"] = validate_captures(evidence, body, case)
                if calibration:
                    from scripts.migration_qt_calibration import validate_ui

                    details["calibration"] = validate_ui(details["trigger"], evidence, language)
            size = details.get("edit", {}).get("size") or details.get("trigger", {}).get(
                "size", details.get("workspace", {}).get("main", {}).get("size", (1000, 640))
            )
            details.update(
                image=inspect_png(image, size=size, regions=plot_regions(output)),
                evidence=validate_evidence(
                    evidence, case, count=2 if trigger or calibration_edit else 4 if workspace else 3, request=body
                ),
            )
        except (OSError, ValueError, KeyError, struct.error, zlib.error, fft.ReferenceError) as exc:
            passed, reason = False, str(exc)
    return {
        "binary": binary.name,
        "case": case["spec"]["id"],
        "command": command,
        "request_sha256": sha256(request_path),
        "binary_sha256": sha256(binary),
        "duration_seconds": time.monotonic() - started,
        "exit_code": code,
        "passed": passed,
        "reason": reason if reason else (None if passed else "exit or lifecycle mismatch"),
        "output": output,
        **details,
    }


def projection_for(document):
    """Observed full result -> display boundary, no calibration or numeric recalculation."""
    count = sum(bool(c["profile"] and c["profile"]["is_calibrated"]) for c in document["calibration"])
    return {
        "schema_version": 1,
        "result_id": document["capture"]["result_id"],
        "source": document["source"],
        "interval": document["interval"],
        "frequency_hz": document["axis"]["corrected"],
        "peak_fs": document["columns"]["peak_fs"],
        "validity": document["validity"],
        "error": document["error"],
        "clock_origin": "unknown",
        "calibration": "uncalibrated"
        if count == 0
        else "calibrated"
        if count == len(document["calibration"])
        else "partial",
        "channel_calibration": document["calibration"],
        "rms_v": document["columns"]["rms_v"],
        "dbv": document["columns"]["dbv"],
        "capture": document["capture"],
        "raw_result_id": document["raw_result_id"],
    }


def qt_environment(prefix):
    """Use only the selected SDK for native Qt children; keep Python audio separate."""
    prefix = prefix.resolve()
    env = {
        **os.environ,
        "QMAKE": str(prefix / "bin/qmake"),
        "QT_QPA_PLATFORM": "offscreen",
        "QT_QUICK_BACKEND": "software",
        "QT_QUICK_CONTROLS_STYLE": "Basic",
        "QT_PLUGIN_PATH": str(prefix / "plugins"),
        "QML_IMPORT_PATH": str(prefix / "qml"),
        "QML2_IMPORT_PATH": str(prefix / "qml"),
        "MEASURELAB_DISPLAY_QML": str(ROOT / "native/qml/Display.qml"),
    }
    env["DYLD_FRAMEWORK_PATH" if sys.platform == "darwin" else "LD_LIBRARY_PATH"] = str(prefix / "lib")
    version = subprocess.check_output([env["QMAKE"], "-query", "QT_VERSION"], env=env, text=True).strip()  # noqa: S603 - selected SDK
    if version != tomllib.loads((ROOT / "native/qt-sdk.toml").read_text())["version"]:
        raise ValueError("Qt SDK version mismatch")
    return env, version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qt-prefix", type=Path, required=True)
    parser.add_argument("--target-dir", type=Path, default=ROOT / "native/target/debug")
    parser.add_argument(
        "--output", type=Path, required=True, help="new run directory; never overwrite existing results"
    )
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--portable", action="store_true")
    args = parser.parse_args()
    if args.timeout <= 0 or args.repeat < 1 or args.output.exists():
        parser.error("positive timeout/repeat and a new output directory are required")
    env, version = qt_environment(args.qt_prefix)
    binaries = [
        args.target_dir.resolve() / (name + (".exe" if os.name == "nt" else ""))
        for name in ("cxxqt-display", "qtbridge-display")
    ]
    if not all(p.is_file() for p in binaries):
        parser.error("build both display binaries first")
    manifest, manifest_hash = candidate.load_manifest(core.DEFAULT_FIXTURES, portable=args.portable, is_core=True)
    args.output.mkdir(parents=True)
    runs = [
        run_display(binary, env, args.output / f"{repeat}-{case['spec']['id']}-{binary.stem}", case, args.timeout)
        for repeat in range(args.repeat)
        for case in manifest["tones"]
        for binary in binaries
    ]
    paths = [
        p
        for p in (ROOT / "native").rglob("*")
        if p.is_file() and "target" not in p.parts and p.suffix in (".rs", ".qml", ".toml", ".lock")
    ]
    report = {
        "schema_version": 1,
        "task": "MIG-007-A-display",
        "passed": all(r["passed"] for r in runs),
        "mode": "portable" if args.portable else "pinned-reference",
        "measurement_kind": "saved_input_correctness_only",
        "host": {"os": platform.system(), "release": platform.release(), "machine": platform.machine()},
        "qt_version": version,
        "fixture_manifest_sha256": manifest_hash,
        "runner_sha256": sha256(Path(__file__)),
        "source_sha256": {str(p.relative_to(ROOT)): sha256(p) for p in sorted(paths)},
        "runs": runs,
        "limitations": [
            "saved input replay; no live audio device",
            "not rendering performance or other-OS validation",
            "no trigger UI or nine-language QML translation validation",
            "Canvas/software raster is an evaluation candidate; Qt adapter choice remains undecided",
        ],
    }
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    for run in runs:
        print(f"{run['binary']} {run['case']}: {'PASS' if run['passed'] else 'FAIL'} {run['reason'] or ''}")
        if not run["passed"]:
            print(run["output"])
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
