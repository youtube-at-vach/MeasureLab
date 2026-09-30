#!/usr/bin/env python3
"""Run both already-built MIG-004-A executables with the same QML lifecycle test.

No PyQt import, fixture regeneration, installation, or implicit build. Records
diagnostic wall time only; this is not the repeated performance protocol.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import tomllib

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_probe(binary: Path, env: dict[str, str], timeout: float) -> dict:
    start = time.monotonic()
    try:
        result = subprocess.run(  # noqa: S603 - explicit local evaluation executable, no shell
            [str(binary), "--self-test"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        code = result.returncode
        output = result.stdout + result.stderr
        reason = None
    except subprocess.TimeoutExpired as exc:
        code = None
        output = "".join(
            value.decode(errors="replace") if isinstance(value, bytes) else value or ""
            for value in (exc.stdout, exc.stderr)
        )
        reason = "timeout"
    required = (
        "PROBE_READY",
        "PROBE_PASS cancel failure stop model slow_gui stale recreate subscriptions window_recreate shutdown",
        "PROBE_TEARDOWN workers=0 models=0",
    )
    errors = ("PROBE_FAIL", "TypeError:", "ReferenceError:", "QQmlApplicationEngine failed")
    passed = code == 0 and all(marker in output for marker in required) and not any(error in output for error in errors)
    return {
        "binary": binary.name,
        "command": [str(binary).replace(str(ROOT), "<repo>"), "--self-test"],
        "binary_sha256": sha256(binary),
        "duration_seconds": time.monotonic() - start,
        "exit_code": code,
        "passed": passed,
        "reason": reason if reason else (None if passed else "exit status or lifecycle marker mismatch"),
        "output": output.replace(str(ROOT), "<repo>"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--qt-prefix", type=Path, required=True, help="Qt development SDK directory containing bin/qmake"
    )
    parser.add_argument("--target-dir", type=Path, default=NATIVE / "target/debug")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--repeat", type=int, default=1, help="repeat correctness checks, not performance samples")
    args = parser.parse_args()
    if args.repeat < 1 or args.timeout <= 0:
        parser.error("repeat and timeout must be positive")
    prefix = args.qt_prefix.resolve()
    qmake = prefix / "bin/qmake"
    env = dict(os.environ)
    # Avoid resolving plugins/frameworks from a Python wheel or another SDK.
    env.update(
        QMAKE=str(qmake),
        QT_QPA_PLATFORM="offscreen",
        QT_QUICK_BACKEND="software",
        QT_QUICK_CONTROLS_STYLE="Basic",
        QT_PLUGIN_PATH=str(prefix / "plugins"),
        QML_IMPORT_PATH=str(prefix / "qml"),
        QML2_IMPORT_PATH=str(prefix / "qml"),
        MEASURELAB_PROBE_QML=str(NATIVE / "qml/Main.qml"),
    )
    env["DYLD_FRAMEWORK_PATH" if sys.platform == "darwin" else "LD_LIBRARY_PATH"] = str(prefix / "lib")
    actual = subprocess.check_output(  # noqa: S603 - explicitly selected SDK executable
        [str(qmake), "-query", "QT_VERSION"], env=env, text=True
    ).strip()
    expected = tomllib.loads((NATIVE / "qt-sdk.toml").read_text())["version"]
    if actual != expected:
        parser.error(f"Qt SDK mismatch: {actual} != {expected}")
    binaries = [args.target_dir.resolve() / name for name in ("cxxqt-probe", "qtbridge-probe")]
    if not all(path.is_file() for path in binaries):
        parser.error("build both native executables first (cargo build --locked)")
    results = [run_probe(binary, env, args.timeout) for _ in range(args.repeat) for binary in binaries]
    source_paths = sorted(
        path
        for path in NATIVE.rglob("*")
        if path.is_file() and "target" not in path.parts and path.suffix in {".rs", ".qml", ".toml", ".lock"}
    )
    report = {
        "schema_version": 1,
        "task": "MIG-004-A",
        "measurement_kind": "correctness_smoke_only",
        "host": {"os": platform.system(), "release": platform.release(), "machine": platform.machine()},
        "source": {
            "base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),  # noqa: S607 - fixed read-only command
            "sha256": {str(path.relative_to(ROOT)): sha256(path) for path in source_paths},
            "runner_sha256": sha256(Path(__file__)),
        },
        "qt_version": actual,
        "environment": {
            key: env[key].replace(str(ROOT), "<repo>")
            for key in (
                "QT_QPA_PLATFORM",
                "QT_QUICK_BACKEND",
                "QT_QUICK_CONTROLS_STYLE",
                "QT_PLUGIN_PATH",
                "QML_IMPORT_PATH",
            )
        },
        "runs": results,
        "passed": all(result["passed"] for result in results),
        "budget_verdict": "not_measured",
        "limitations": [
            "synthetic worker, no audio or analysis graph",
            "AC07 demand tokens use a synthetic worker; Analysis Graph node ownership remains untested",
            "not a packaging, rendering performance, or other-OS result",
        ],
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    for result in results:
        print(f"{result['binary']}: {'PASS' if result['passed'] else 'FAIL'} ({result['duration_seconds']:.3f}s)")
        if not result["passed"]:
            print(result["output"])
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
