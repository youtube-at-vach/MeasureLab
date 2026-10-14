"""Run the GUI redesign's internal acceptance cases, retaining each screenshot."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parent.parent
PREFIX = "MEASURELAB_UI_SMOKE_"


def cases():
    for instrument in ("scope", "spectrum", "spectrogram", "xy", "lockin", "comparison", "generator"):
        yield f"{instrument}-wide", False, {"VIEW": instrument, "IDLE": "1"}
        yield f"{instrument}-compact", True, {"VIEW": instrument, "IDLE": "1", "ZOOM": "1.25"}
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
    yield "held-save", False, {"STAGE3F": "1"}
    yield "held-replay", True, {"STAGE3F": "1", "REPLAY": "1", "COMPARE": "1"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "target/release/measurelab")
    parser.add_argument("--output", type=Path, default=ROOT / "dist/gui-redesign-qa")
    parser.add_argument("--case", action="append", help="Run only the named case (repeatable)")
    args = parser.parse_args()
    binary = args.binary.resolve()
    output = args.output.resolve()
    selected = [case for case in cases() if args.case is None or case[0] in args.case]
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
    manifest = {
        "revision": subprocess.check_output([git, "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),  # noqa: S603 - resolved Git with fixed arguments
        "changes": subprocess.check_output([git, "status", "--short"], cwd=ROOT, text=True),  # noqa: S603 - resolved Git with fixed arguments
        "binary": str(binary),
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "source_patch": "source.patch",
        "source_patch_sha256": hashlib.sha256(patch).hexdigest(),
        "qa_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scope": "Internal GUI QA; external audio paths and native DPI changes require separate acceptance.",
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
            passed = result.returncode == 0 and screenshot.is_file() and "GUI navigation OK:" in log
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
                "environment": {PREFIX + key: value for key, value in options.items()},
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
    print(f"GUI QA cases completed. Inspect the screenshots separately: {output}")


if __name__ == "__main__":
    main()
