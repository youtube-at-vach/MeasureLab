"""MIG-007-A: exact BlackHole input -> shared FFT -> both native Qt adapters.

Device I/O requires --virtual-device. No implicit build, fixture update, default
device selection or product GUI import. This is short correctness validation.
"""

from __future__ import annotations

import argparse
from importlib import metadata
import json
from pathlib import Path
import platform
import struct
import subprocess
import sys
import time
import zlib

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import migration_audio_graph as audio  # noqa: E402
from scripts import migration_audio_virtual as virtual  # noqa: E402
from scripts import migration_fft_reference as fft  # noqa: E402
from scripts.migration_qt_display import PASS, inspect_png, plot_regions, qt_environment  # noqa: E402
from scripts.migration_qt_probe import sha256  # noqa: E402

N, RATE = 1024, 48000
BINS = [37, 71, 113, 173, 251, 331, 419, 509]
TOLERANCES = {"f32": dict(fft.TOLERANCES["f32"]), "tone_abs": 1e-6}


def cases():
    return [
        {"id": "2-to-2", "device": "BlackHole 2ch", "ports": [1, 0]},
        {"id": "4-from-16", "device": "BlackHole 16ch", "ports": [15, 13, 11, 9]},
        {"id": "8-from-16", "device": "BlackHole 16ch", "ports": [15, 13, 11, 9, 7, 5, 3, 1]},
    ]


def request_for(case, evidence):
    count = virtual.DEVICES[case["device"]]
    return {
        "format": {
            "stream_id": f"live.{case['id']}.input",
            "generation": 0,
            "timebase_id": f"live.{case['id']}.clock",
            "clock_domain": f"cpal.device:{case['device']}",
            "rate": [RATE, 1],
            "input_ids": [f"input.logical.{ch}" for ch in range(len(case["ports"]))],
            "input_ports": case["ports"],
            "output_ids": [],
            "output_ports": [],
        },
        "precision": "F32",
        "n": N,
        "window": "Boxcar",
        "input": None,
        "live": {"device": case["device"], "device_channels": count},
        "evidence": str(evidence.resolve()),
    }


def stimulus(case):
    count = virtual.DEVICES[case["device"]]
    phase = np.arange(N) * (2 * np.pi / N)
    # Distractor tones on unselected ports make accidental binding visible.
    values = np.repeat((0.002 * np.cos(17 * phase))[:, None], count, axis=1).astype("<f4")
    for ch, port in enumerate(case["ports"]):
        values[:, port] = (ch + 1) / 512 * np.cos(BINS[ch] * phase)
    return values


def validate_evidence(directory, request, *, count=3):
    """Require actual captured bytes and independent FFT, plus completed stream cleanup."""
    paths = sorted(directory.glob("generation-*.json"))
    if len(paths) != count or len(list(directory.glob("live-*.json"))) != count:
        raise fft.ReferenceError(f"expected {count} live generations with closed-stream evidence")
    channels = len(request["format"]["input_ids"])
    observed, generations = [], set()
    for path in paths:
        document = json.loads(path.read_bytes())
        generation = document["source"]["generation"]
        if type(generation) is not int or generation <= 0 or generation in generations:
            raise fft.ReferenceError("repeated or invalid live generation")
        generations.add(generation)
        expected = audio.expected_source(request)
        expected["generation"] = expected["timebase"]["generation"] = generation
        interval = document["interval"]
        if (
            document["schema_version"] != 1
            or document["source"] != expected
            or document["validity"]
            or document["error"]
            or interval != [0, N]
        ):
            raise fft.ReferenceError("live source, interval or validity mismatch")
        raw_path, metrics_path = directory / f"input-{generation}.f32", directory / f"live-{generation}.json"
        values = np.frombuffer(raw_path.read_bytes(), dtype="<f4")
        if values.size != N * channels or not np.all(np.isfinite(values)):
            raise fft.ReferenceError("live input bytes shape/nonfinite")
        values = values.reshape(N, channels).astype(np.float64)
        spectrum = np.abs(np.fft.rfft(values, axis=0)) * (2 / N)
        spectrum[[0, -1]] *= 0.5
        axis = np.arange(N // 2 + 1) * RATE / N
        actual = document["columns"]["peak_fs"]
        if actual["shape"] != list(spectrum.shape) or document["axis"]["unit"] != "Hz":
            raise fft.ReferenceError("live peak shape or axis unit")
        peak = np.asarray(actual["values"], dtype=float).reshape(spectrum.shape)
        if not np.all(np.isfinite(peak)) or not np.array_equal(document["axis"]["corrected"], axis):
            raise fft.ReferenceError("live FFT differs from captured-byte oracle")
        fft.compare(peak, spectrum, TOLERANCES["f32"], "live captured-byte FFT")
        tones = spectrum[BINS[:channels], np.arange(channels)]
        if not np.array_equal(spectrum.argmax(axis=0), BINS[:channels]) or not np.allclose(
            tones, np.arange(1, channels + 1) / 512, rtol=0, atol=TOLERANCES["tone_abs"]
        ):
            raise fft.ReferenceError("live physical port binding or tone mismatch")
        if request.get("calibration"):
            from scripts.migration_qt_calibration import validate_result, validate_exchange

            bound = {**request, "format": {**request["format"], "generation": generation}}
            validate_result(document, bound, values)
            validate_exchange(path)
        else:
            voltage = document["columns"]["rms_v"]
            if voltage["values"] != [None] * channels or voltage["reasons"] != ["uncalibrated"] * channels:
                raise fft.ReferenceError("live uncalibrated voltage is numeric")
        metrics = json.loads(metrics_path.read_bytes())
        expected_format = {**request["format"], "generation": generation}
        if (
            metrics["schema_version"] != 1
            or metrics["generation"] != generation
            or metrics["format"] != expected_format
            or metrics["device"] != request["live"]["device"]
            or not metrics["reclaimed"]
            or metrics["error"] is not None
            or metrics["input"]["closed"] is not True
            or metrics["input"]["callbacks"] <= 0
            or any(metrics["input"][key] != 0 for key in ("errors", "xruns", "rejected"))
            or metrics["fft_evaluations"] < 1
            or metrics["captured_frames"] < N
            or metrics["input"]["frames"] < metrics["captured_frames"]
            or metrics["queue"]["channels"] != request["live"]["device_channels"]
            or metrics["queue"]["capacity_frames"] != 8192
            or metrics["queue"]["max_depth_frames"] > 8192
            or not isinstance(metrics["stop_ms"], (int, float))
            or not np.isfinite(metrics["stop_ms"])
            or metrics["stop_ms"] < 0
        ):
            raise fft.ReferenceError("live capture/stream cleanup metrics mismatch")
        observed.append(
            {
                "generation": generation,
                "result_sha256": sha256(path),
                "input_sha256": sha256(raw_path),
                "metrics_sha256": sha256(metrics_path),
                "max_peak_abs_error": float(np.max(np.abs(peak - spectrum))),
                "metrics": metrics,
            }
        )
    return observed


def run_display(binary, env, directory, case, timeout, *, trigger=False, language="en", calibration=False):
    import sounddevice as sd

    directory.mkdir(parents=True, exist_ok=False)
    evidence = directory / "results"
    evidence.mkdir()
    request = request_for(case, evidence)
    if calibration:
        from scripts.migration_qt_calibration import diagnostic_profiles

        request["calibration"] = diagnostic_profiles(request)
    request_path = directory / "request.json"
    request_path.write_text(json.dumps(request) + "\n")
    period = stimulus(case)
    period.tofile(directory / "stimulus.f32")
    tiled = np.tile(period, (16, 1))
    cursor, statuses, blocks = 0, [], set()

    def callback(outdata, frames, times, status):
        nonlocal cursor
        if frames > len(tiled) - N:
            raise sd.CallbackAbort
        offset = cursor % N
        outdata[:] = tiled[offset : offset + frames]
        cursor += frames
        blocks.add(frames)
        if status:
            statuses.append(str(status))

    command = [str(binary), "--self-test", "--live-input", "--snapshot", str(directory.resolve() / "display.png")]
    if trigger:
        command += ["--trigger-test", "--language", language]
    if calibration:
        command += ["--calibration-test", "1"]
    started, code, output, reason, details = time.monotonic(), None, "", None, {}
    try:
        index = virtual.exact_device(case["device"])
        settings = sd.CoreAudioSettings(change_device_parameters=True, fail_if_conversion_required=True)
        with sd.OutputStream(
            device=index,
            samplerate=RATE,
            blocksize=256,
            channels=period.shape[1],
            dtype="float32",
            callback=callback,
            extra_settings=settings,
        ) as stream:
            time.sleep(0.25)
            result = subprocess.run(  # noqa: S603 - selected local binary
                command,
                cwd=ROOT,
                env={**env, "MEASURELAB_DISPLAY_REQUEST": str(request_path.resolve())},
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            code, output = result.returncode, result.stdout + result.stderr
            if not stream.active or statuses:
                raise fft.ReferenceError("stimulus stream stopped or reported an error")
        if (
            code != 0
            or not all(
                marker in output
                for marker in (
                    "DISPLAY_READY",
                    "DISPLAY_TRIGGER_PASS" if trigger else PASS,
                    "DISPLAY_IMAGE_OK",
                    "DISPLAY_TEARDOWN workers=0 models=0",
                )
            )
            or any(
                marker in output
                for marker in (
                    "DISPLAY_FAIL",
                    "TypeError:",
                    "ReferenceError:",
                    "QQmlApplicationEngine failed",
                    "Cannot assign",
                    "is not a function",
                    "Binding loop",
                )
            )
        ):
            raise fft.ReferenceError("live Qt lifecycle/exit mismatch")
        if trigger:
            from scripts.migration_qt_trigger import validate_ui, validate_captures

            details["trigger"] = validate_ui(output, language)
            details["captures"] = validate_captures(evidence, request)
            if calibration:
                from scripts.migration_qt_calibration import validate_ui as validate_calibration_ui

                details["calibration"] = validate_calibration_ui(details["trigger"], evidence, language)
        details.update(
            image=inspect_png(
                directory / "display.png",
                size=details.get("trigger", {}).get("size", (1000, 640)),
                regions=plot_regions(output),
            ),
            evidence=validate_evidence(evidence, request, count=2 if trigger else 3),
        )
    except subprocess.TimeoutExpired as exc:
        output = "".join(
            v.decode(errors="replace") if isinstance(v, bytes) else v or "" for v in (exc.stdout, exc.stderr)
        )
        reason = "timeout"
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        struct.error,
        zlib.error,
        fft.ReferenceError,
        sd.PortAudioError,
    ) as exc:
        reason = str(exc)
    return {
        "case": case["id"],
        "binary": binary.name,
        "command": command,
        "passed": reason is None,
        "reason": reason,
        "exit_code": code,
        "output": output,
        "duration_seconds": time.monotonic() - started,
        "binary_sha256": sha256(binary),
        "request_sha256": sha256(request_path),
        "stimulus": {
            "sha256": sha256(directory / "stimulus.f32"),
            "frames_submitted": cursor,
            "block_frames": sorted(blocks),
            "statuses": statuses,
        },
        **details,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--virtual-device", action="store_true")
    parser.add_argument("--qt-prefix", type=Path, required=True)
    parser.add_argument("--target-dir", type=Path, default=ROOT / "native/target/debug")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--case", choices=[c["id"] for c in cases()])
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    if not args.virtual_device or sys.platform != "darwin":
        parser.error("explicit --virtual-device on macOS is required for BlackHole I/O")
    if args.output.exists() or args.repeat < 1 or not np.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("new output directory and positive repeat/timeout required")
    env, version = qt_environment(args.qt_prefix)
    binaries = [args.target_dir.resolve() / name for name in ("cxxqt-display", "qtbridge-display")]
    if not all(p.is_file() for p in binaries):
        parser.error("build both display binaries first")
    args.output.mkdir(parents=True)
    runs = []
    for repeat in range(args.repeat):
        for case in cases():
            if args.case and case["id"] != args.case:
                continue
            for binary in binaries:
                run = run_display(binary, env, args.output / f"{repeat}-{case['id']}-{binary.name}", case, args.timeout)
                runs.append(run)
                print(
                    f"{binary.name} {case['id']}: {'PASS' if run['passed'] else 'FAIL'} {run['reason'] or ''}",
                    flush=True,
                )
    sources = [
        p
        for p in (ROOT / "native").rglob("*")
        if p.is_file() and "target" not in p.parts and p.suffix in (".rs", ".qml", ".toml", ".lock")
    ]
    report = {
        "schema_version": 1,
        "task": "MIG-007-A-live",
        "passed": all(r["passed"] for r in runs),
        "host": {
            "os": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "macos": platform.mac_ver()[0],
        },
        "qt_version": version,
        "python_version": platform.python_version(),
        "versions": {name: metadata.version(name) for name in ("numpy", "sounddevice")},
        "runner_sha256": sha256(Path(__file__)),
        "helpers_sha256": {
            str(p.relative_to(ROOT)): sha256(p)
            for p in [
                *(Path(module.__file__) for module in (audio, virtual, fft)),
                ROOT / "scripts/migration_qt_display.py",
                ROOT / "scripts/migration_qt_probe.py",
            ]
        },
        "source_sha256": {str(p.relative_to(ROOT)): sha256(p) for p in sorted(sources)},
        "tolerances": TOLERANCES,
        "runs": runs,
        "limitations": [
            "BlackHole correctness only; no physical ADC/DAC or absolute latency",
            "no trigger/calibration/save UI, nine-language QML, all-tap or product adapter validation",
            "short input.raw scheduler; no reconnect recovery or ten-minute performance acceptance",
        ],
    }
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
