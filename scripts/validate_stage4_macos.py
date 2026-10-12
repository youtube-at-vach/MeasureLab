#!/usr/bin/env python3
"""Run sequential macOS integration QA against one prebuilt release binary."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release/measurelab")
    parser.add_argument("--seconds", type=int, default=600)
    parser.add_argument("--physical", action="store_true", help="Drive UAC-232 L/R loops at <=0.1 FS peak")
    parser.add_argument("--suite", choices=["ui", "load", "physical"], default="ui")
    parser.add_argument("--case", action="append", help="Run only named cases; repeat to select several")
    args = parser.parse_args()
    if platform.system() != "Darwin":
        parser.error("This acceptance suite is macOS-only; other OS verification is deferred")
    if not 30 <= args.seconds <= 3600:
        parser.error("--seconds must be 30..3600 (600 for long-term acceptance)")
    if args.suite == "physical" and not args.physical:
        parser.error("The physical suite requires --physical and connected L/L, R/R loops")
    binary = args.binary.resolve()
    out = ROOT / "dist/stage4-macos-qa" / time.strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True)
    git = shutil.which("git")
    if git is None:
        parser.error("git is required to identify the tested source")
    revision = subprocess.check_output([git, "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()  # noqa: S603 - resolved git, fixed arguments
    diff = subprocess.check_output([git, "diff", "HEAD"], cwd=ROOT)  # noqa: S603 - resolved git, fixed arguments
    manifest = {
        "revision": revision,
        "diff_sha256": hashlib.sha256(diff).hexdigest(),
        "source_sha256": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / "src").rglob("*"))
            if p.is_file()
        },
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "os": platform.platform(),
        "suite": args.suite,
        "seconds": args.seconds,
        "physical": args.physical,
        "runs": [],
    }
    caffeinate = shutil.which("caffeinate")
    if caffeinate is None:
        parser.error("caffeinate is required for visible macOS GUI verification")
    awake = subprocess.Popen([caffeinate, "-diu", "-w", str(os.getpid())])  # noqa: S603 - resolved macOS command, own PID
    manifest["keep_awake"] = "caffeinate -diu, scoped to this runner process"
    env = {k: v for k, v in os.environ.items() if not k.startswith("MEASURELAB_")}
    env["MEASURELAB_QA_BINARY"] = str(binary)
    jobs = []
    if args.suite == "ui":
        for source, value in [("STAGE3F", "1"), ("BLACKHOLE", "BlackHole 2ch"), ("BLACKHOLE", "BlackHole 16ch")]:
            for replay in [False, True]:
                case = {f"MEASURELAB_UI_SMOKE_{source}": value, "MEASURELAB_UI_SMOKE_COMPARE": "1"}
                if replay:
                    case["MEASURELAB_UI_SMOKE_REPLAY"] = "1"
                jobs.append(
                    (
                        f"reuse-{source.lower()}-{value.replace(' ', '-')}-{int(replay)}",
                        case,
                        [str(binary), "--ui-smoke"] + (["--compact"] if replay else []),
                    )
                )
        for mode in [
            "polar",
            "cartesian",
            "all",
            "pair",
            "settling",
            "ref-loss",
            "held-edit",
            "live-edit",
            "source-change",
        ]:
            jobs.append(
                (f"lockin-{mode}", {"MEASURELAB_UI_SMOKE_LOCKIN": mode}, [str(binary), "--ui-smoke", "--compact"])
            )
        for device in ["BlackHole 2ch", "BlackHole 16ch"]:
            jobs.append(
                (
                    "single-" + device.replace(" ", "-"),
                    {
                        "MEASURELAB_UI_SMOKE_BLACKHOLE": device,
                        "MEASURELAB_UI_SMOKE_EXTERNAL_SINGLE": "1",
                    },
                    [str(binary), "--ui-smoke", "--compact"],
                )
            )
        jobs.append(("gpu", {}, [str(binary), "--gpu-smoke"]))
    elif args.suite == "load":
        for device, rate, mode, precision, psd in [
            ("BlackHole 2ch", 48000, "continuous", "f64", False),
            ("BlackHole 16ch", 96000, "continuous", "f64", True),
            ("BlackHole 2ch", 48000, "latest", "f32", True),
        ]:
            name = f"load-{device.replace(' ', '-')}-{rate}-{mode}-{precision}"
            case = {
                "MEASURELAB_PROFILE_SECONDS": str(args.seconds),
                "MEASURELAB_PROFILE_DEVICE": device,
                "MEASURELAB_PROFILE_SAMPLE_RATE": str(rate),
                "MEASURELAB_PROFILE_CHANNEL": "16" if "16ch" in device else "2",
                "MEASURELAB_PROFILE_FFT_SIZE": "524288",
                "MEASURELAB_PROFILE_STFT_SIZE": "8192",
                "MEASURELAB_PROFILE_SPECTRUM_MODE": mode,
                "MEASURELAB_PROFILE_FFT_PRECISION": precision,
                "MEASURELAB_PROFILE_KNOWN_OUTPUT": "1",
                "MEASURELAB_PROFILE_UI_STALL": "1",
                "MEASURELAB_PROFILE_KEEP_AWAKE": "1",
                "MEASURELAB_PROFILE_EXPORT": str(out / f"{name}.json"),
            }
            if psd:
                case["MEASURELAB_SPECTRUM_PSD"] = "1"
            jobs.append((name, case, [str(ROOT / "scripts/profile-stage2.sh"), out.name + "-" + name]))
    else:
        for replay in [False, True]:
            case = {"MEASURELAB_UI_SMOKE_PHYSICAL": "ZOOM UAC-232", "MEASURELAB_UI_SMOKE_COMPARE": "1"}
            if replay:
                case["MEASURELAB_UI_SMOKE_REPLAY"] = "1"
            jobs.append(
                (f"physical-reuse-{int(replay)}", case, [str(binary), "--ui-smoke"] + (["--compact"] if replay else []))
            )
        jobs.append(
            (
                "physical-single",
                {"MEASURELAB_UI_SMOKE_PHYSICAL": "ZOOM UAC-232", "MEASURELAB_UI_SMOKE_EXTERNAL_SINGLE": "1"},
                [str(binary), "--ui-smoke", "--compact"],
            )
        )
        case = {
            "MEASURELAB_PROFILE_SECONDS": str(args.seconds),
            "MEASURELAB_PROFILE_DEVICE": "ZOOM UAC-232",
            "MEASURELAB_PROFILE_SAMPLE_RATE": "48000",
            "MEASURELAB_PROFILE_PHYSICAL_OUTPUT": "1",
            "MEASURELAB_PROFILE_FFT_SIZE": "524288",
            "MEASURELAB_PROFILE_STFT_SIZE": "8192",
            "MEASURELAB_PROFILE_SPECTRUM_MODE": "continuous",
            "MEASURELAB_PROFILE_UI_STALL": "1",
            "MEASURELAB_PROFILE_KEEP_AWAKE": "1",
            "MEASURELAB_PROFILE_EXPORT": str(out / "physical-load.json"),
        }
        jobs.append(("physical-load", case, [str(ROOT / "scripts/profile-stage2.sh"), out.name + "-physical-load"]))
    if args.case:
        unknown = set(args.case) - {name for name, _, _ in jobs}
        if unknown:
            parser.error(f"Unknown cases: {sorted(unknown)}")
        jobs = [job for job in jobs if job[0] in args.case]
    for name, case, command in jobs:
        print(f"{name}: starting", flush=True)
        started = time.monotonic()
        with (out / f"{name}.log").open("w") as log:
            result = subprocess.run(  # noqa: S603 - fixed QA commands; no shell
                command, cwd=ROOT, env=env | case, stdout=log, stderr=subprocess.STDOUT, check=False
            )
        exit_code = result.returncode
        if "MEASURELAB_PROFILE_SECONDS" in case and exit_code == 0:
            profile_log = ROOT / "dist/stage2-qa" / f"{command[-1]}.log"
            if "UI QA profile complete:" not in profile_log.read_text():
                exit_code = 1
                print(f"{name}: incomplete profile; no finite-result completion marker", flush=True)
        manifest["runs"].append(
            {
                "name": name,
                "environment": case,
                "command": command,
                "process_exit_code": result.returncode,
                "exit_code": exit_code,
                "elapsed_seconds": time.monotonic() - started,
            }
        )
        if exit_code == 0 and "--ui-smoke" in command:
            shutil.copyfile(ROOT / "dist/ui-smoke.png", out / f"{name}.png")
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"{name}: exit {exit_code}; {out / (name + '.log')}", flush=True)
        if exit_code:
            raise SystemExit(exit_code)
    awake.terminate()
    awake.wait(timeout=5)
    print(f"Evidence: {out}", flush=True)


if __name__ == "__main__":
    main()
