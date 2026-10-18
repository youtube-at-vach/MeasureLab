"""Run the GUI redesign's internal acceptance cases, retaining each screenshot."""

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
PREFIX = "MEASURELAB_UI_SMOKE_"


def cases(devices=()):
    yield "widget-interactions", False, {"INTERACTIONS": "1", "IDLE": "1"}
    for instrument in ("scope", "spectrum", "spectrogram", "xy", "lockin", "comparison", "generator"):
        yield f"{instrument}-wide", False, {"VIEW": instrument, "IDLE": "1"}
        yield f"{instrument}-compact", True, {"VIEW": instrument, "IDLE": "1", "ZOOM": "1.25"}
    yield "scope-four-channel", False, {"VIEW": "scope", "SCOPE4": "1"}
    yield "spectrum-four-channel", False, {"VIEW": "spectrum", "SPECTRUM4": "1"}
    yield "spectrum-four-channel-compact", True, {"VIEW": "spectrum", "SPECTRUM4": "1", "ZOOM": "1.25"}
    yield "spectrum-details-compact", True, {"VIEW": "spectrum", "SPECTRUM4": "1", "DETAILS": "1", "ZOOM": "1.25"}
    for mode in ("1", "pair"):
        for compact in (False, True):
            name = "single" if mode == "1" else mode
            yield (
                f"spectrogram-display-{name}-{'compact' if compact else 'wide'}",
                compact,
                {"SPECTROGRAM_DISPLAY": mode, "VIEW": "spectrogram", "DETAILS": "1"}
                | ({"ZOOM": "1.25"} if compact else {}),
            )
    yield (
        "spectrogram-display-single-measurement-compact",
        True,
        {"SPECTROGRAM_DISPLAY": "1", "VIEW": "spectrogram", "ZOOM": "1.25"},
    )
    yield "spectrum-esd", False, {"VIEW": "spectrum", "ESD": "1"}
    yield "spectrum-esd-compact", True, {"VIEW": "spectrum", "ESD": "1", "DETAILS": "1", "ZOOM": "1.25"}
    yield "scope-details-compact", True, {"VIEW": "scope", "DETAILS": "1", "IDLE": "1", "ZOOM": "1.25"}
    yield "xy-details-compact", True, {"VIEW": "xy", "DETAILS": "1", "IDLE": "1", "ZOOM": "1.25"}
    yield "xy-trace-wide", False, {"VIEW": "xy", "CURSORS": "1", "CURSOR_VIEW": "trace", "XY_PHASE": "90"}
    yield "console-grid", False, {"VIEW": "console", "ZOOM": "0.75"}
    yield "console-tabs", True, {"VIEW": "console", "ZOOM": "1.25"}
    yield "console-empty", True, {"VIEW": "empty"}
    for layout in ("columns", "rows", "tabs"):
        yield f"pair-{layout}", False, {"VIEW": "pair", "LAYOUT": layout, "ZOOM": "0.75"}
    for tab in ("input", "output", "calibration"):
        yield f"io-{tab}", True, {"SETTINGS": tab, "IDLE": "1", "ZOOM": "1.25"}
    yield "selected-details", True, {"VIEW": "spectrum", "DETAILS": "1", "ZOOM": "1.25"}
    yield "generator-internal", False, {"GENERATOR": "scope"}
    yield "comparison-internal", True, {"COMPARISON": "pair"}
    yield "lockin-all", True, {"LOCKIN": "all"}
    yield "lockin-pair", False, {"LOCKIN": "pair"}
    yield "held-save", False, {"STAGE3F": "1", "INTERACTIONS": "1"}
    yield "held-replay", True, {"STAGE3F": "1", "REPLAY": "1", "COMPARE": "1"}
    for device in devices:
        name = device.lower().replace(" ", "-")
        yield f"generator-{name}", False, {"GENERATOR": "scope", "GENERATOR_DEVICE": device}
        source = "PHYSICAL" if device == "ZOOM UAC-232" else "BLACKHOLE"
        yield f"held-{name}-save", False, {source: device, "COMPARE": "1"}
        yield f"held-{name}-replay", True, {source: device, "REPLAY": "1", "COMPARE": "1"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release/measurelab")
    parser.add_argument("--output", type=Path, default=ROOT / "dist/gui-redesign-qa")
    parser.add_argument("--case", action="append", help="Run only the named case (repeatable)")
    parser.add_argument(
        "--assertions-only",
        action="store_true",
        help="Run state/numerical/bounds assertions without screenshots; visual acceptance remains pending",
    )
    parser.add_argument(
        "--device",
        action="append",
        default=[],
        choices=["BlackHole 2ch", "BlackHole 16ch", "ZOOM UAC-232"],
        help="Include external QA (repeatable); UAC-232 requires connected L/L, R/R TRS loops, <=0.1 FS peak",
    )
    args = parser.parse_args()
    binary = args.binary.resolve()
    output = args.output.resolve()
    selected = [case for case in cases(dict.fromkeys(args.device)) if args.case is None or case[0] in args.case]
    if args.case and set(args.case) - {case[0] for case in selected}:
        parser.error("Unknown case name")
    if not binary.is_file():
        parser.error(f"Build a QA binary first: {binary}")
    git = shutil.which("git")
    if git is None:
        parser.error("Git is required to identify the tested revision")
    output.mkdir(parents=True, exist_ok=True)
    patch = subprocess.check_output([git, "diff", "--binary"], cwd=ROOT)  # noqa: S603 - resolved Git with fixed arguments
    (output / "source.patch").write_bytes(patch)
    # Do not inherit another audio/profile QA configuration from the caller.
    env = {key: value for key, value in os.environ.items() if not key.startswith("MEASURELAB_")}
    if args.assertions_only:
        env[PREFIX + "ASSERTIONS_ONLY"] = "1"
    manifest = {
        "revision": subprocess.check_output([git, "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),  # noqa: S603 - resolved Git with fixed arguments
        "changes": subprocess.check_output([git, "status", "--short"], cwd=ROOT, text=True),  # noqa: S603 - resolved Git with fixed arguments
        "binary": str(binary),
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "source_patch": "source.patch",
        "source_patch_sha256": hashlib.sha256(patch).hexdigest(),
        "qa_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "source_sha256": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((ROOT / "src").rglob("*.rs"))
        },
        "os": platform.platform(),
        "devices": args.device,
        "screenshots_required": not args.assertions_only,
        "scope": "GUI events and internal/selected external QA; native monitor DPI and manual normal-build acceptance remain separate.",
        "cases": [],
    }
    failures = []
    for name, compact, options in selected:
        command = [str(binary), "--ui-smoke"] + (["--compact"] if compact else [])
        screenshot = ROOT / "dist/ui-smoke.png"
        screenshot.unlink(missing_ok=True)
        started = time.monotonic()
        try:
            result = subprocess.run(  # noqa: S603 - explicitly selected local QA binary; no shell
                command,
                cwd=ROOT,
                env=env | {PREFIX + key: value for key, value in options.items()},
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            log = result.stdout + result.stderr
            display_ok = "UI assertions only OK:" in log if args.assertions_only else screenshot.is_file()
            passed = result.returncode == 0 and display_ok and "GUI navigation OK:" in log
            if "INTERACTIONS" in options:
                passed = passed and "GUI interactions OK:" in log
            if "ESD" in options:
                passed = passed and "ESD UI OK:" in log
            if "SPECTROGRAM_DISPLAY" in options:
                passed = passed and "Spectrogram display UI OK:" in log
            returncode = result.returncode
        except subprocess.TimeoutExpired as error:
            log = f"GUI QA timed out: {error}"
            passed = False
            returncode = None
        (output / f"{name}.log").write_text(log, encoding="utf-8")
        if screenshot.is_file():
            shutil.copy2(screenshot, output / f"{name}.png")
        else:
            (output / f"{name}.png").unlink(missing_ok=True)
        manifest["cases"].append(
            {
                "name": name,
                "command": command,
                "environment": (
                    {PREFIX + key: value for key, value in options.items()}
                    | ({PREFIX + "ASSERTIONS_ONLY": "1"} if args.assertions_only else {})
                ),
                "passed": passed,
                "returncode": returncode,
                "seconds": round(time.monotonic() - started, 3),
                "log": f"{name}.log",
                "screenshot": f"{name}.png" if screenshot.is_file() else None,
            }
        )
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"{'PASS' if passed else 'FAIL'} {name}", flush=True)
        if not passed:
            failures.append(name)
    if failures:
        raise SystemExit(f"GUI QA failed: {', '.join(failures)}. See {output}")
    if args.assertions_only:
        print(f"GUI assertions completed; screenshot/visual acceptance remains pending: {output}")
    else:
        print(f"GUI QA cases completed. Inspect the screenshots separately: {output}")


if __name__ == "__main__":
    main()
