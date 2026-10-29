"""Compare Spectrogram/Cepstrogram Live/stress on selected routes, serially."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import time

ROOT = Path(__file__).resolve().parent.parent
PREFIX = "MEASURELAB_PROFILE_"
STFT_SIZES = (1024, 2048, 4096, 8192, 16384, 32768)

# Interaction gates, fixed before measuring. The intentional one-second UI
# suspension is included in max interval, but never treated as an ordinary lag.
UI_P95_MS = 100.0
UI_MAX_INTERVAL_MS = 2000.0
STRESS_EXTRA_MS = 16.7
RESPONSE_P95_MS = 500.0
LIMITS = {
    "ui_p95_ms": UI_P95_MS,
    "ui_max_interval_ms": UI_MAX_INTERVAL_MS,
    "stress_extra_ms": STRESS_EXTRA_MS,
    "response_p95_ms": RESPONSE_P95_MS,
    "minimum_ui_frames_per_second": 10,
    "minimum_stress_steps_per_second": 5,
    "maximum_duration_overrun_seconds": 5,
}


def routes(devices, basic=False):
    for overlap in ("50", "75", "87.5"):
        yield (
            f"demo-{overlap.replace('.', '_')}",
            {
                "DEMO_BIN_TONE": "1",
                "STFT_OVERLAP": overlap,
            },
            ["--demo"],
        )
    yield (
        "software",
        {"SOFTWARE_LOOPBACK": "1", "SAMPLE_RATE": "192000", "CHANNEL": "2", "STFT_OVERLAP": "87.5"},
        [],
    )
    yield "generator", {"GENERATOR_INTERNAL": "1", "SAMPLE_RATE": "192000", "STFT_OVERLAP": "87.5"}, []
    for device in devices:
        physical = device == "ZOOM UAC-232"
        yield (
            device.lower().replace(" ", "-"),
            {
                "DEVICE": device,
                # Basic physical acceptance uses the normal 48 kHz condition;
                # extended acceptance also exercises the device's 192 kHz rate.
                "SAMPLE_RATE": "48000" if device == "BlackHole 2ch" or (physical and basic) else "192000",
                "CHANNEL": "16" if device == "BlackHole 16ch" else "1",
                "PHYSICAL_OUTPUT" if physical else "KNOWN_OUTPUT": "1",
                "STFT_OVERLAP": "75" if device == "BlackHole 2ch" else "87.5",
            },
            [],
        )


def profile_cases(selected, analysis, sizes=(), sample_rate=None):
    """Keep each Live baseline adjacent to stress, with identical mode conditions."""
    analyses = ("spectrogram", "cepstrogram") if analysis == "both" else (analysis,)
    for route, options, app_args in selected:
        for size in sizes or (None,):
            pair = route + (f"-n{size}" if size is not None else "")
            for kind in analyses:
                name = f"{pair}-{kind}" if analysis == "both" else pair
                for mode in ("live", "stress"):
                    case_options = {
                        "SPECTROGRAM": mode,
                        "SPECTRUM_MODE": "continuous",
                        "UI_STALL": "1",
                        "KEEP_AWAKE": "1",
                        "FOREGROUND": "1",
                    } | options
                    if sample_rate is not None:
                        case_options["SAMPLE_RATE"] = str(sample_rate)
                    case_options["FFT_SIZE"] = "32768" if case_options.get("SAMPLE_RATE") == "192000" else "8192"
                    if size is not None:
                        case_options["STFT_SIZE"] = str(size)
                    if kind == "cepstrogram":
                        case_options["CEPSTROGRAM"] = "1"
                    yield {
                        "name": f"{name}-{mode}",
                        "analysis": kind,
                        "mode": mode,
                        "comparison_key": f"{pair}-{mode}",
                        "baseline_key": name,
                        "environment": case_options,
                        "app_args": app_args,
                    }


def metrics(log):
    def number(pattern):
        match = re.search(pattern, log)
        if match is None:
            raise ValueError(f"Missing QA metric: {pattern}")
        return float(match[1])

    return {
        "ui_p95_ms": number(r"UI profile: .*?frame interval p95 ([\d.]+) ms"),
        "ui_frames": number(r"UI profile: (\d+) frames"),
        "ui_seconds": number(r"UI profile: .*?over ([\d.]+) s"),
        "ui_max_interval_ms": number(r"UI profile: .*?max ([\d.]+) ms"),
        "response_p95_ms": number(r"Spectrogram response: .*?p95 ([\d.]+) ms"),
        "response_max_ms": number(r"Spectrogram response: .*?max ([\d.]+) ms"),
        "responses": number(r"Spectrogram response: (\d+) applied"),
        "display_steps": number(r"Spectrogram (?:live|stress) QA OK: (\d+) display steps"),
        "gpu_uploaded_bytes": number(r"Spectrogram GPU payload: .*?, (\d+) uploaded bytes"),
        "peak_frame_mib": number(r"MiB retained / ([\d.]+) MiB peak frames"),
        "screenshots": len(re.findall(r"UI screenshot: dist/ui-smoke\.png", log)),
        "surface_skips": number(r"QA skipped surface acquisitions after warm-up: (\d+)"),
        "input_dropped": number(r"UI profile: .*?input dropped (\d+)"),
        "stft_rows": number(r"STFT profile: .*?rows (\d+)"),
        "stft_input_dropped": number(r"STFT profile: .*?input dropped (\d+)"),
        "stft_result_dropped": number(r"STFT profile: .*?result dropped (\d+)"),
        "storage_dropped": number(r"STFT history profile: .*?, (\d+) storage dropped"),
        "stft_cpu_ms": number(r"STFT profile: .*?worker CPU ([\d.]+) ms total"),
        "cepstrum_cpu_ms": number(r"Cepstrum extra log/inverse CPU: ([\d.]+) ms total"),
        "collector_cpu_ms": number(r"STFT history profile: .*?collector CPU ([\d.]+) ms total"),
        "preparation_mean_ms": number(r"Spectrogram preparation: .*?/ ([\d.]+) ms mean"),
        "preparation_max_ms": number(r"Spectrogram preparation: .*?/ ([\d.]+) ms max"),
        "sample_rate": number(r"STFT profile: (\d+) Hz"),
        "input_channels": number(r"STFT profile: .*?Hz, (\d+) ch"),
        "stft_size": number(r"STFT profile: .*?, (\d+)-point"),
        "channel": number(r"STFT profile: .*?CH (\d+)"),
        "hop": number(r"(?:Spectrogram|Cepstrogram) numerical QA OK: .*?hop (\d+)"),
    }


def assess(log, mode, seconds, returncode, baseline, screenshots=False, analysis="spectrogram", environment=None):
    if analysis not in ("spectrogram", "cepstrogram"):
        raise ValueError(f"Unknown analysis: {analysis}")
    numerical_marker = "Cepstrogram numerical QA OK:" if analysis == "cepstrogram" else "Spectrogram numerical QA OK:"
    if (
        returncode != 0
        or "UI screenshot failed:" in log
        or not all(
            marker in log
            for marker in (
                f"Spectrogram {mode} QA OK:",
                numerical_marker,
                "UI stall OK:",
                "UI QA profile complete: finite result audited and input stopped",
                "QA skipped surface acquisitions after warm-up:",
            )
        )
    ):
        return False, {}
    values = metrics(log)
    numerical = re.search(rf"{numerical_marker} (\d+) Hz, CH (\d+), N (\d+), hop (\d+),", log)
    if numerical is None:
        return False, values
    passed = (
        values["ui_p95_ms"] <= UI_P95_MS
        and values["ui_max_interval_ms"] <= UI_MAX_INTERVAL_MS
        and seconds <= values["ui_seconds"] <= seconds + LIMITS["maximum_duration_overrun_seconds"]
        and values["ui_frames"] >= seconds * LIMITS["minimum_ui_frames_per_second"]
        and values["response_p95_ms"] <= RESPONSE_P95_MS
        and values["responses"] >= max(1, values["display_steps"] // 20)
        and values["stft_rows"] >= 3
        and all(
            values[key] == 0
            for key in (
                "input_dropped",
                "stft_input_dropped",
                "stft_result_dropped",
                "storage_dropped",
                "surface_skips",
            )
        )
        and (analysis == "cepstrogram" or values["cepstrum_cpu_ms"] == 0)
        and tuple(map(int, numerical.groups()))
        == tuple(values[key] for key in ("sample_rate", "channel", "stft_size", "hop"))
    )
    if mode == "stress":
        passed = (
            passed
            and values["display_steps"] >= seconds * LIMITS["minimum_stress_steps_per_second"]
            and baseline is not None
            and values["ui_p95_ms"] <= baseline["ui_p95_ms"] + STRESS_EXTRA_MS
        )
    if screenshots:
        passed = passed and values["screenshots"] >= seconds // 2
    if environment is not None:
        size = int(environment.get("STFT_SIZE", min(int(environment.get("FFT_SIZE", "8192")), 32768)))
        hop = size // {"50": 2, "75": 4, "87.5": 8}[environment.get("STFT_OVERLAP", "75")]
        passed = passed and (
            values["sample_rate"] == int(environment.get("SAMPLE_RATE", "48000"))
            and values["stft_size"] == size
            and values["channel"] == int(environment.get("CHANNEL", "1"))
            and values["hop"] == hop
            and values["input_channels"] == (16 if environment.get("DEVICE") == "BlackHole 16ch" else 2)
        )
        if "KNOWN_OUTPUT" in environment or "PHYSICAL_OUTPUT" in environment:
            audits = re.findall(r"QA output audit: attachment notifications (\d+), measured notifications (\d+)", log)
            passed = passed and (
                len(audits) >= 2
                and all(int(measured) == 0 for _, measured in audits)
                and "QA output nominal rate restored to " in log
                and ("KNOWN_OUTPUT" not in environment or "Known Spectrum OK:" in log)
            )
            if audits:
                values["output_attachment_notifications"] = int(audits[-1][0])
                values["output_measured_notifications"] = int(audits[-1][1])
    return passed, values


def comparisons(cases):
    """Report paired costs; passing one analysis never accepts the other."""
    groups = {}
    for case in cases:
        if "comparison_key" in case:
            groups.setdefault(case["comparison_key"], {})[case["analysis"]] = case
    result = []
    for name, pair in groups.items():
        if set(pair) != {"spectrogram", "cepstrogram"}:
            continue
        a, b = (pair[kind] for kind in ("spectrogram", "cepstrogram"))
        delta = {}
        if a["metrics"] and b["metrics"] and a["metrics"]["stft_rows"] > 0 and b["metrics"]["stft_rows"] > 0:
            for key in (
                "ui_p95_ms",
                "ui_max_interval_ms",
                "response_p95_ms",
                "response_max_ms",
                "peak_frame_mib",
                "preparation_mean_ms",
                "preparation_max_ms",
                "peak_rss_mib",
            ):
                if key in a["metrics"] and key in b["metrics"]:
                    delta[key] = b["metrics"][key] - a["metrics"][key]
            for key in ("stft_cpu_ms", "cepstrum_cpu_ms", "collector_cpu_ms"):
                delta[key.removesuffix("_ms") + "_ms_per_row"] = (
                    b["metrics"][key] / b["metrics"]["stft_rows"] - a["metrics"][key] / a["metrics"]["stft_rows"]
                )
        result.append(
            {
                "name": name,
                "spectrogram": a["name"],
                "cepstrogram": b["name"],
                "passed": a["passed"] and b["passed"],
                "cepstrogram_minus_spectrogram": delta,
            }
        )
    return result


def peak_rss(path):
    """The sampler reports KiB; keep missing or corrupt measurements visible."""
    if not path.is_file():
        raise ValueError(f"Missing RSS samples: {path}")
    try:
        samples = [float(line.split(",")[1]) for line in path.read_text().splitlines()[1:] if line.strip()]
    except (IndexError, ValueError) as error:
        raise ValueError(f"Invalid RSS samples: {path}") from error
    # ps can observe a terminating process after it has released its memory.
    if not samples or any(not (0 <= value < float("inf")) for value in samples) or max(samples) == 0:
        raise ValueError(f"Invalid RSS samples: {path}")
    return max(samples) / 1024.0


def manifest_passed(document):
    """Accept complete planned cells, never a short run or duplicate substitute."""
    cases = document["cases"]
    minimum_seconds = 20 if document.get("acceptance_scope") == "basic" else 120
    if not (
        cases
        and len(cases) == document["planned_cases"]
        and len({case["name"] for case in cases}) == len(cases)
        and document["duration_seconds"] >= minimum_seconds
        and document["acceptance_duration"]
        and all(case["passed"] for case in cases)
    ):
        return False
    # Older manifests did not persist the planned cells. Preserve their audit
    # entry point, while checking exact coverage for newly recorded runs.
    if "plan" in document:
        fields = ("name", "analysis", "mode", "comparison_key", "baseline_key", "environment", "app_args")
        return len(document["plan"]) == len(cases) and all(
            all(case.get(key) == planned.get(key) for key in fields)
            for case, planned in zip(cases, document["plan"], strict=True)
        )
    return True


def audit_manifest(path):
    original = json.loads(path.read_text())
    document = original | {
        "original_manifest": path.name,
        "assessor_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "limits": LIMITS,
        "cases": [],
    }
    baselines = {}
    for case in original["cases"]:
        route, mode = case["name"].rsplit("-", 1)
        log = (path.parent / case["log"]).read_text()
        try:
            passed, values = assess(
                log,
                mode,
                original["duration_seconds"],
                case["returncode"],
                baselines.get(route),
                original.get("repeated_screenshots", False),
                analysis=case.get("analysis", original.get("analysis", "spectrogram")),
                environment=case.get("environment"),
            )
            rss_value = peak_rss(path.parent / f"{case['name']}-rss.csv")
            if values:
                values["peak_rss_mib"] = rss_value
            error = None
        except ValueError as exception:
            passed, values, error = False, {}, str(exception)
        if mode == "live":
            baselines[route] = values if passed else None
        document["cases"].append(
            case | {"original_passed": case["passed"], "passed": passed, "metrics": values, "assessment_error": error}
        )
        print(f"{'PASS' if passed else 'FAIL'} {case['name']}: {values}")
    target = path.with_stem(path.stem + "-audited")
    document["comparisons"] = comparisons(document["cases"])
    document["passed"] = manifest_passed(document)
    target.write_text(json.dumps(document, indent=2) + "\n")
    return document["passed"]


def run_profile(command, env, timeout):
    # Timeout also stops the application's audio output, not just the sampler.
    with subprocess.Popen(  # noqa: S603 - explicit local QA script, no shell
        command,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    ) as process:
        try:
            log, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                log, _ = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                log, _ = process.communicate()
            return subprocess.CompletedProcess(command, 124, log + "\nQA timed out; process group stopped\n")
        return subprocess.CompletedProcess(command, process.returncode, log)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", choices=["spectrogram", "cepstrogram", "both"], default="spectrogram")
    parser.add_argument("--stft-size", type=int, action="append", choices=STFT_SIZES, help="Repeat for a size matrix")
    parser.add_argument(
        "--sample-rate", type=int, choices=[44100, 48000, 96000, 192000], help="Override every route's Fs"
    )
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release/measurelab")
    parser.add_argument("--output", type=Path, default=ROOT / "dist/spectrogram-s6")
    parser.add_argument(
        "--basic", action="store_true", help="Use 20-second MVP acceptance, with physical I/O at 48 kHz"
    )
    parser.add_argument("--seconds", type=int, help="Duration per case (default: 120 seconds, or 20 with --basic)")
    parser.add_argument(
        "--screenshots", action="store_true", help="Repeat GPU readback and PNG writing during each case"
    )
    parser.add_argument("--physical-connection", help="Record the actual UAC-232 cabling and attenuation")
    parser.add_argument("--route", action="append", help="Run only named routes (repeatable)")
    parser.add_argument(
        "--audit", type=Path, help="Reassess a saved manifest and logs with current gates; no audio is started"
    )
    parser.add_argument(
        "--device",
        action="append",
        default=[],
        choices=["BlackHole 2ch", "BlackHole 16ch", "ZOOM UAC-232"],
        help="Opt in to device output; UAC-232 needs both output/input loop paths, <=0.1 FS peak, no DC",
    )
    args = parser.parse_args()
    if args.audit:
        raise SystemExit(0 if audit_manifest(args.audit.resolve()) else 1)
    if args.seconds is None:
        args.seconds = 20 if args.basic else 120
    if args.seconds < 20:
        parser.error("At least 20 seconds is required for complete stress cycles")
    if args.seconds > 3600:
        parser.error("At most 3600 seconds is supported by the application profile")
    binary = args.binary.resolve()
    if not binary.is_file():
        parser.error("Build a release QA binary first")
    git = shutil.which("git")
    if git is None:
        parser.error("Git is required for source identification")
    selected = [
        route
        for route in routes(dict.fromkeys(args.device), args.basic)
        if args.route is None or route[0] in args.route
    ]
    if args.route and set(args.route) - {route[0] for route in selected}:
        parser.error("Unknown route (devices must also be explicitly selected with --device)")
    output = args.output.resolve()
    if (output / "manifest.json").exists():
        parser.error("Output already contains a manifest; choose a new directory to preserve previous results")
    output.mkdir(parents=True, exist_ok=True)
    planned = list(profile_cases(selected, args.analysis, tuple(dict.fromkeys(args.stft_size or ())), args.sample_rate))
    for case in planned:
        case["environment"] |= {"SECONDS": str(args.seconds)}
        if args.screenshots:
            case["environment"]["SCREENSHOT"] = "repeat"
    patch = subprocess.check_output([git, "diff", "--binary", "HEAD"], cwd=ROOT)  # noqa: S603 - resolved Git, fixed arguments
    untracked = subprocess.check_output(  # noqa: S603 - resolved Git, fixed arguments
        [git, "ls-files", "--others", "--exclude-standard", "-z"], cwd=ROOT
    )
    for name in filter(None, untracked.decode().split("\0")):
        added = subprocess.run(  # noqa: S603 - Git compares a workspace path without a shell
            [git, "diff", "--no-index", "--binary", "--", "/dev/null", name],
            cwd=ROOT,
            capture_output=True,
            check=False,
        )
        if added.returncode != 1:
            raise RuntimeError(f"Cannot capture untracked source: {name}")
        patch += added.stdout
    (output / "source.patch").write_bytes(patch)
    manifest = {
        "analysis": args.analysis,
        "revision": subprocess.check_output([git, "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),  # noqa: S603
        "binary": str(binary),
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "source_patch_sha256": hashlib.sha256(patch).hexdigest(),
        "source_sha256": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((ROOT / "src").rglob("*.rs"))
        },
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "os": platform.platform(),
        "duration_seconds": args.seconds,
        "repeated_screenshots": args.screenshots,
        "acceptance_scope": "basic" if args.basic else "extended",
        "acceptance_duration": args.seconds >= (20 if args.basic else 120),
        "physical_connection": args.physical_connection,
        "limits": LIMITS,
        "planned_cases": len(planned),
        "plan": planned,
        "passed": False,
        "comparisons": [],
        "scope": "Automated input/FFT/history/display comparison; manual normal-build operations and native monitor DPI remain separate.",
        "cases": [],
    }
    env = {key: value for key, value in os.environ.items() if not key.startswith("MEASURELAB_")}
    failures = []
    baselines = {}
    for case in planned:
        name, mode = case["name"], case["mode"]
        case_options = case["environment"]
        case_env = env | {PREFIX + key: value for key, value in case_options.items()}
        started = time.monotonic()
        command = [str(ROOT / "scripts/profile-stage2.sh"), name, *case["app_args"]]
        case_env["MEASURELAB_QA_BINARY"] = str(binary)
        oracles = (
            [ROOT / f"dist/stage4-macos-qa/physical-gui-oracle{suffix}.json" for suffix in ("", ".failure")]
            if "PHYSICAL_OUTPUT" in case_options
            else []
        )
        for oracle in oracles:
            oracle.unlink(missing_ok=True)
        try:
            result = run_profile(command, case_env, args.seconds + 90)
            log = result.stdout
            passed, values = assess(
                log,
                mode,
                args.seconds,
                result.returncode,
                baselines.get(case["baseline_key"]),
                args.screenshots,
                analysis=case["analysis"],
                environment=case_options,
            )
            rss = ROOT / f"dist/stage2-qa/{name}-rss.csv"
            rss_value = peak_rss(rss)
            if values:
                values["peak_rss_mib"] = rss_value
            if mode == "live":
                baselines[case["baseline_key"]] = values if passed else None
            returncode = result.returncode
        except ValueError as error:
            log += f"\n{error}\n"
            values, passed, returncode = {}, False, result.returncode
        (output / f"{name}.log").write_text(log, encoding="utf-8")
        rss = ROOT / f"dist/stage2-qa/{name}-rss.csv"
        if rss.is_file():
            shutil.copy2(rss, output / rss.name)
        for oracle in oracles:
            if oracle.is_file():
                shutil.copy2(oracle, output / f"{name}-{oracle.name}")
        manifest["cases"].append(
            case
            | {
                "command": command,
                "seconds": round(time.monotonic() - started, 3),
                "returncode": returncode,
                "passed": passed,
                "metrics": values,
                "log": f"{name}.log",
            }
        )
        manifest["comparisons"] = comparisons(manifest["cases"])
        manifest["passed"] = manifest_passed(manifest)
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"{'PASS' if passed else 'FAIL'} {name}: {values}", flush=True)
        if not passed:
            failures.append(name)
    if failures:
        raise SystemExit(f"Spectrogram QA failed: {', '.join(failures)}; see {output}")
    if not manifest_passed(manifest):
        raise SystemExit(f"Spectrogram QA did not complete the acceptance duration or planned cases; see {output}")
    print(f"Spectrogram comparison complete: {output}")


if __name__ == "__main__":
    main()
