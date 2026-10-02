#!/usr/bin/env python3
"""MIG-004-B: repeated development loops in an isolated copy, with no downloads.

Default counts follow MIG-002-v0.1. --smoke runs one sample per path and cannot
produce a budget verdict. macOS packaging is a relocated, ad-hoc signed local
bundle test. Linux packages carry Qt/QML/ICU and retain host system dependencies.
Neither is a clean OS or distribution result.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import signal
import statistics
import subprocess
import tarfile
import tempfile
import threading
import time
import tomllib

ROOT = Path(__file__).resolve().parents[1]
ADAPTERS = ("cxxqt-probe", "qtbridge-probe")
COUNTS = {"clean": 3, "no_op": 5, "qml_edit": 5, "package": 3}
LABEL = 'qsTr("Synthetic worker · no audio device")'
EDITED_LABEL = 'qsTr("Synthetic worker · iteration check")'
PASS = "PROBE_PASS cancel failure stop model slow_gui stale recreate subscriptions window_recreate shutdown"
TEARDOWN = "PROBE_TEARDOWN workers=0 models=0"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(
    command: list[str], cwd: Path, env: dict[str, str], timeout: float, ready_marker: str = "PROBE_READY"
) -> dict:
    """Timestamp the ready marker while draining output; retain failures and timeouts."""
    start = time.monotonic()
    lines: list[str] = []
    ready: list[float] = []
    process = subprocess.Popen(  # noqa: S603 - fixed executable argv, no shell
        command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True
    )

    def drain() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            lines.append(line)
            if ready_marker in line and not ready:
                ready.append(time.monotonic() - start)

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    reason = None
    try:
        code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        code = None
        reason = "timeout"
    reader.join(timeout=5)
    if reader.is_alive():
        reason = "output pipe did not close"
    else:
        assert process.stdout is not None
        process.stdout.close()
    return {
        "command": command,
        "duration_seconds": time.monotonic() - start,
        "ready_seconds": ready[0] if ready else None,
        "exit_code": code,
        "reason": reason,
        "output": "".join(lines),
    }


def probe_passed(step: dict) -> bool:
    output = step["output"]
    return (
        step["exit_code"] == 0
        and step["reason"] is None
        and step["ready_seconds"] is not None
        and PASS in output
        and TEARDOWN in output
        and not any(error in output for error in ("PROBE_FAIL", "TypeError:", "ReferenceError:", "failed to load"))
    )


def summary(runs: list[dict]) -> dict:
    result = {}
    for adapter in ADAPTERS:
        result[adapter] = {}
        for path, count in COUNTS.items():
            samples = [r for r in runs if r["adapter"] == adapter and r["path"] == path and not r["warmup"]]
            values = [r["duration_seconds"] for r in samples]
            result[adapter][path] = {
                "samples": len(samples),
                "required_samples": count,
                "all_passed": bool(samples) and all(r["passed"] for r in samples),
                "median_seconds": statistics.median(values) if values else None,
                "min_seconds": min(values) if values else None,
                "max_seconds": max(values) if values else None,
                "population_stdev_seconds": statistics.pstdev(values) if values else None,
                "complete": len(samples) == count and all(r["passed"] for r in samples),
            }
    return result


def build_environment(prefix: Path, scratch: Path) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("QT_", "QML", "DYLD_", "LD_", "CARGO_", "RUST", "MEASURELAB_PROBE"))
    }
    env.update(
        CARGO_HOME=str(ROOT / ".tools/cargo"),
        RUSTUP_HOME=str(ROOT / ".tools/rustup"),
        CARGO_BUILD_JOBS="4",
        CC="/usr/bin/clang" if platform.system() == "Darwin" else "/usr/bin/cc",
        CXX="/usr/bin/clang++" if platform.system() == "Darwin" else "/usr/bin/c++",
        QMAKE=str(prefix / "bin/qmake"),
        PATH=f"{ROOT}/.tools/cargo/bin:{ROOT}/.tools/build-venv/bin:{env.get('PATH', '')}",
        QT_QPA_PLATFORM="offscreen",
        QT_QUICK_BACKEND="software",
        QT_QUICK_CONTROLS_STYLE="Basic",
        QT_SCALE_FACTOR="1",
        QT_PLUGIN_PATH=str(prefix / "plugins"),
        QML_IMPORT_PATH=str(prefix / "qml"),
        QML2_IMPORT_PATH=str(prefix / "qml"),
        MEASURELAB_PROBE_QML=str(scratch / "native/qml/Main.qml"),
        XDG_CACHE_HOME=str(scratch / "qml-cache"),
        QML_DISK_CACHE_PATH=str(scratch / "qml-cache"),
        LC_ALL="en_US.UTF-8" if platform.system() == "Darwin" else "C.UTF-8",
    )
    if platform.system() == "Darwin":
        env["MACOSX_DEPLOYMENT_TARGET"] = "13.0"
    elif (ROOT / ".tools/system-lib").is_dir():
        env["LIBRARY_PATH"] = str(ROOT / ".tools/system-lib")
    env["DYLD_FRAMEWORK_PATH" if platform.system() == "Darwin" else "LD_LIBRARY_PATH"] = str(prefix / "lib")
    return env


def package_environment(destination: Path) -> dict[str, str]:
    # No developer PATH, Qt imports, DYLD overrides, Python runtime, or QML override.
    (destination / "home").mkdir(exist_ok=True)
    (destination / "cache").mkdir(exist_ok=True)
    return {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(destination / "home"),
        "XDG_CACHE_HOME": str(destination / "cache"),
        "QML_DISK_CACHE_PATH": str(destination / "cache"),
        "LC_ALL": "en_US.UTF-8" if platform.system() == "Darwin" else "C.UTF-8",
        "QT_QPA_PLATFORM": "offscreen",
        "QT_QUICK_BACKEND": "software",
        "QT_QUICK_CONTROLS_STYLE": "Basic",
        "QT_SCALE_FACTOR": "1",
        "DYLD_PRINT_LIBRARIES": "1",
        **({"LD_DEBUG": "libs"} if platform.system() == "Linux" else {}),
    }


def loaded_qt_paths(output: str) -> list[str]:
    return [
        line.split()[-1]
        for line in output.splitlines()
        if line.startswith("dyld[")
        and ("/Qt" in line or "libq" in line)
        and not line.split()[-1].startswith(("/usr/lib/", "/System/Library/"))
    ]


def loaded_linux_paths(output: str) -> list[str]:
    """Use actual glibc initialization records, never library search candidates."""
    return sorted(
        {line.split("calling init:", 1)[1].strip() for line in output.splitlines() if "calling init: /" in line}
    )


def linux_package_passed(step: dict, app: Path) -> bool:
    loaded = loaded_linux_paths(step["output"])
    qt = [
        path
        for path in loaded
        if Path(path).name.startswith(("libQt6", "libq", "libicu")) or "/qml/" in path or "/plugins/" in path
    ]
    return (
        probe_passed(step)
        and f"PROBE_QML {app}/share/measurelab-evaluation/Main.qml\n" in step["output"]
        and any(Path(path).name.startswith("libQt6Core.so") for path in qt)
        and any(Path(path).name == "libqoffscreen.so" for path in qt)
        and all(Path(path).resolve().is_relative_to(app.resolve()) for path in qt)
        and all(
            Path(path).resolve().is_relative_to(app.resolve()) or path.startswith(("/usr/lib/", "/lib/", "/lib64/"))
            for path in loaded
        )
    )


def host_metadata() -> dict:
    if platform.system() == "Darwin":
        return {
            "processor": read_command(["/usr/sbin/sysctl", "-n", "machdep.cpu.brand_string"]),
            "memory_bytes": read_command(["/usr/sbin/sysctl", "-n", "hw.memsize"]),
            "power": read_command(["/usr/bin/pmset", "-g", "batt"]),
        }
    cpu = Path("/proc/cpuinfo").read_text()
    memory = Path("/proc/meminfo").read_text()
    return {
        "processor": next(line.split(":", 1)[1].strip() for line in cpu.splitlines() if line.startswith("model name")),
        "memory_bytes": str(int(memory.split("MemTotal:", 1)[1].split()[0]) * 1024),
        "power": "not_measured",
        "distribution": platform.freedesktop_os_release(),
    }


def package_passed(step: dict, app: Path) -> bool:
    loaded = loaded_qt_paths(step["output"])
    return (
        probe_passed(step)
        and f"PROBE_QML {app}/Contents/Resources/Main.qml" in step["output"]
        and any("QtCore.framework" in path for path in loaded)
        and all(path.startswith(str(app) + "/") for path in loaded)
    )


class Benchmark:
    def __init__(self, prefix: Path, report: Path, smoke: bool):
        parent = ROOT / ".migration-local/qt-iteration"
        parent.mkdir(parents=True, exist_ok=True)
        self.scratch = Path(tempfile.mkdtemp(prefix="run-", dir=parent))
        shutil.copytree(ROOT / "native", self.scratch / "native", ignore=shutil.ignore_patterns("target"))
        self.prefix = prefix
        self.report_path = report
        self.log_dir = report.parent / f"{report.stem}-logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.env = build_environment(prefix, self.scratch)
        self.smoke = smoke
        self.version = tomllib.loads((ROOT / "native/rust-toolchain.toml").read_text())["toolchain"]["channel"]
        self.cargo = str(ROOT / ".tools/cargo/bin/cargo")
        self.runs: list[dict] = []
        self.reference_runs: list[dict] = []
        self.current_steps: list[dict] = []
        self.normalizations = [(str(self.scratch), "<scratch>"), (str(ROOT), "<repo>")]
        self.source_metadata = {
            "base_commit": read_command(["git", "rev-parse", "HEAD"]),
            "branch": read_command(["git", "branch", "--show-current"]),
            "dirty_diff_sha256": hashlib.sha256(
                read_command(["git", "diff", "--binary", "HEAD"], strip=False).encode()
            ).hexdigest(),
            "sha256": {
                str(path.relative_to(ROOT)): digest(path)
                for path in sorted((ROOT / "native").rglob("*"))
                if path.is_file() and "target" not in path.parts and path.suffix in {".rs", ".qml", ".toml", ".lock"}
            },
            "runner_sha256": digest(Path(__file__)),
        }

    def clean_text(self, value: str) -> str:
        for original, replacement in self.normalizations:
            value = value.replace(original, replacement)
        return value.replace(str(Path.home()), "<home>")

    def step(
        self,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
        ready_marker: str = "PROBE_READY",
        expected_exit_code: int = 0,
    ) -> dict:
        step = execute(command, cwd or self.scratch, env or self.env, 1200, ready_marker)
        index = sum(len(run["steps"]) for run in self.runs + self.reference_runs) + len(self.current_steps)
        log = self.log_dir / f"{index:03d}.log.gz"
        log.write_bytes(gzip.compress(self.clean_text(step["output"]).encode(), mtime=0))
        self.current_steps.append(
            {key: value for key, value in step.items() if key not in {"output", "command"}}
            | {
                "command": [self.clean_text(part) for part in command],
                "log": f"{self.log_dir.name}/{log.name}",
                "log_sha256": digest(log),
                "expected_exit_code": expected_exit_code,
            }
        )
        if step["exit_code"] != expected_exit_code or step["reason"]:
            raise RuntimeError(f"command failed: {command[0]} ({step['reason'] or step['exit_code']}); see {log}")
        return step

    def cargo_step(self, adapter: str, operation: str) -> dict:
        return self.step(
            [
                self.cargo,
                f"+{self.version}",
                operation,
                "--locked",
                "--offline",
                "--manifest-path",
                "native/Cargo.toml",
                "--target-dir",
                str(self.scratch / "targets" / adapter),
                "-p",
                adapter if operation == "build" else "probe-core",
                "-vv",
            ]
        )

    def reference(self, index: int) -> None:
        self.current_steps = []
        env = {
            key: value
            for key, value in self.env.items()
            if not key.startswith(("QT_", "QML", "DYLD_", "LD_", "MEASURELAB_PROBE"))
        }
        env.update(QT_QPA_PLATFORM="offscreen", QT_SCALE_FACTOR="1")
        marker = "[Self-Test] Application started successfully."
        step = {}
        reason = None
        passed = False
        try:
            step = self.step(
                [
                    str(ROOT / ".venv/bin/python"),
                    "scripts/migration_reference.py",
                    "--state-dir",
                    str(self.scratch / "python-state"),
                    "--self-test",
                ],
                env=env,
                cwd=ROOT,
                ready_marker=marker,
            )
            passed = step["ready_seconds"] is not None and "Traceback" not in step["output"]
        except (OSError, RuntimeError) as exc:
            reason = self.clean_text(str(exc))
        self.reference_runs.append(
            {
                "sample": index,
                "steps": self.current_steps,
                "passed": passed,
                "ready_seconds": step.get("ready_seconds"),
                "duration_seconds": step.get("duration_seconds"),
                "reason": reason,
                "workload": "unchanged whole Python application, offline self-test; not equivalent to small QML probe",
                "cache": "new process, existing Python bytecode and OS cache; same isolated state directory",
            }
        )
        print(
            f"Python whole-app startup {index}: {'PASS' if passed else 'FAIL'} ready={step.get('ready_seconds')}",
            flush=True,
        )
        self.save()
        if not passed:
            raise RuntimeError("Python reference readiness/self-test failed")

    def package(self, adapter: str, binary: Path, index: int) -> dict:
        if platform.system() == "Linux":
            return self.package_linux(adapter, binary, index)
        app = self.scratch / "packages" / f"{adapter}-{index}" / f"{adapter}.app"
        contents = app / "Contents"
        (contents / "MacOS").mkdir(parents=True)
        (contents / "Resources").mkdir()
        shutil.copy2(binary, contents / "MacOS" / adapter)
        shutil.copy2(self.scratch / "native/qml/Main.qml", contents / "Resources/Main.qml")
        with (contents / "Info.plist").open("wb") as handle:
            plistlib.dump(
                {
                    "CFBundleExecutable": adapter,
                    "CFBundleName": "MeasureLab Qt evaluation",
                    "CFBundleIdentifier": f"org.measurelab.evaluation.{adapter}",
                    "CFBundlePackageType": "APPL",
                    "CFBundleVersion": "0.1.0",
                    "LSMinimumSystemVersion": "13.0",
                },
                handle,
            )
        platforms = contents / "PlugIns/platforms"
        platforms.mkdir(parents=True)
        plugins = [platforms / name for name in ("libqcocoa.dylib", "libqoffscreen.dylib")]
        for plugin in plugins:
            shutil.copy2(self.prefix / "plugins/platforms" / plugin.name, plugin)
        self.step(
            [
                "/usr/bin/install_name_tool",
                "-add_rpath",
                "@executable_path/../Frameworks",
                str(contents / "MacOS" / adapter),
            ]
        )
        deployment = self.step(
            [
                str(self.prefix / "bin/macdeployqt"),
                str(app),
                f"-qmldir={contents / 'Resources'}",
                "-no-plugins",
                f"-libpath={self.prefix / 'lib'}",
                *[f"-executable={plugin}" for plugin in plugins],
                "-verbose=2",
            ]
        )
        if "ERROR:" in deployment["output"]:
            raise RuntimeError("macdeployqt reported dependency errors despite exit status zero")
        self.step(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)])
        archive = app.parent / "evaluation.zip"
        self.step(["/usr/bin/ditto", "-c", "-k", "--keepParent", str(app), str(archive)])
        relocated = self.scratch / "relocated" / f"{adapter}-{index}"
        relocated.mkdir(parents=True)
        self.step(["/usr/bin/ditto", "-x", "-k", str(archive), str(relocated)])
        relocated_app = relocated / app.name
        step = self.step(
            [str(relocated_app / "Contents/MacOS" / adapter), "--self-test"],
            env=package_environment(relocated),
            cwd=relocated,
        )
        if not package_passed(step, relocated_app):
            raise RuntimeError("relocated lifecycle/QML/loaded Qt paths check failed")
        return {
            "archive_bytes": archive.stat().st_size,
            "archive_sha256": digest(archive),
            "bundle_qml_sha256": digest(relocated_app / "Contents/Resources/Main.qml"),
            "relocated_app": self.clean_text(str(relocated_app)),
            "loaded_qt_paths": [self.clean_text(path) for path in loaded_qt_paths(step["output"])],
            "signing": "ad_hoc_verified",
            "clean_os": "not_tested",
        }

    def package_linux(self, adapter: str, binary: Path, index: int) -> dict:
        app = self.scratch / "packages" / f"{adapter}-{index}" / f"{adapter}-evaluation"
        (app / "bin").mkdir(parents=True)
        resource = app / "share/measurelab-evaluation/Main.qml"
        resource.parent.mkdir(parents=True)
        shutil.copy2(binary, app / "bin" / adapter)
        shutil.copy2(self.scratch / "native/qml/Main.qml", resource)
        (app / "bin/qt.conf").write_text("[Paths]\nPrefix=..\nLibraries=lib\nPlugins=plugins\nQmlImports=qml\n")
        for module in ("QtQml", "QtQuick"):
            shutil.copytree(self.prefix / "qml" / module, app / "qml" / module)
        platforms = app / "plugins/platforms"
        platforms.mkdir(parents=True)
        for name in ("libqoffscreen.so", "libqxcb.so"):
            shutil.copy2(self.prefix / "plugins/platforms" / name, platforms / name)
        (app / "lib").mkdir()
        system_dependencies = set()
        # ldd reports transitive dependencies too, including those of QML/platform plugins.
        for elf in [app / "bin" / adapter, *sorted(app.rglob("*.so"))]:
            dependencies = self.step(["/usr/bin/ldd", str(elf)])
            if "not found" in dependencies["output"]:
                raise RuntimeError(f"unresolved package dependency: {elf}")
            for line in dependencies["output"].splitlines():
                if "=> /" not in line:
                    continue
                path = Path(line.split("=>", 1)[1].strip().split()[0])
                if path.is_relative_to(self.prefix / "lib"):
                    destination = app / "lib" / path.name
                    if not destination.exists():
                        shutil.copy2(path, destination)
                elif path.is_relative_to(self.prefix):
                    raise RuntimeError(f"unexpected SDK dependency: {path}")
                else:
                    system_dependencies.add(str(path))
        launcher = app / "launch"
        launcher.write_text(
            "#!/bin/sh\nset -eu\n"
            'package_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
            'export LD_LIBRARY_PATH="$package_dir/lib"\n'
            f'exec "$package_dir/bin/{adapter}" "$@"\n'
        )
        launcher.chmod(0o755)
        archive = Path(shutil.make_archive(str(app.parent / "evaluation"), "gztar", app.parent, app.name))
        relocated = self.scratch / "relocated" / f"{adapter}-{index}"
        relocated.mkdir(parents=True)
        with tarfile.open(archive) as handle:
            handle.extractall(relocated, filter="data")
        relocated_app = relocated / app.name
        env = package_environment(relocated)
        step = self.step([str(relocated_app / "launch"), "--self-test"], env=env, cwd=relocated)
        if not linux_package_passed(step, relocated_app):
            raise RuntimeError("relocated lifecycle/QML/loaded Qt/ICU/plugin paths check failed")
        # A missing resource must not load the existing developer QML via a fallback.
        relocated_qml = relocated_app / "share/measurelab-evaluation/Main.qml"
        original = relocated_qml.read_bytes()
        try:
            relocated_qml.unlink()
            negative = self.step(
                [str(relocated_app / "launch"), "--self-test"], env=env, cwd=relocated, expected_exit_code=101
            )
            if "PROBE_QML" in negative["output"] or "QML file must exist" not in negative["output"]:
                raise RuntimeError("missing package QML was not rejected")
        finally:
            relocated_qml.write_bytes(original)
        # Keep the archive and verified extraction; discard the redundant staging tree.
        shutil.rmtree(app)
        return {
            "archive_bytes": archive.stat().st_size,
            "archive_sha256": digest(archive),
            "bundle_qml_sha256": digest(relocated_qml),
            "relocated_app": self.clean_text(str(relocated_app)),
            "loaded_libraries": [self.clean_text(path) for path in loaded_linux_paths(step["output"])],
            "system_dependencies": sorted(system_dependencies),
            "missing_qml_exit_code": negative["exit_code"],
            "signing": "not_applicable_local_linux_archive",
            "clean_os": "not_tested",
        }

    def sample(self, adapter: str, path: str, index: int, warmup: bool = False) -> None:
        self.current_steps = []
        target = self.scratch / "targets" / adapter
        qml = self.scratch / "native/qml/Main.qml"
        original = qml.read_bytes()
        if path == "clean" and target.exists():
            shutil.rmtree(target)  # only this invocation's private target directory
        if path == "qml_edit":
            if original.decode().count(LABEL) != 1:
                raise RuntimeError("expected exactly one fixed QML edit anchor")
            qml.write_text(original.decode().replace(LABEL, EDITED_LABEL))
        start = time.monotonic()
        metrics = {"qml_sha256": digest(qml)}
        passed = False
        reason = None
        try:
            binary = target / "debug" / adapter
            if path == "package":
                metrics.update(self.package(adapter, binary, index))
            else:
                build = self.cargo_step(adapter, "build")
                metrics["build_seconds"] = build["duration_seconds"]
                metrics["cargo_fresh"] = "Fresh " in build["output"] and "Compiling " not in build["output"]
                if path == "qml_edit" and not metrics["cargo_fresh"]:
                    raise RuntimeError("QML-only file edit unexpectedly recompiled native code")
                if path in {"clean", "no_op"}:
                    self.cargo_step(adapter, "test")
                probe_start = time.monotonic()
                probe = self.step([str(binary), "--self-test"])
                metrics["ready_from_command_start_seconds"] = probe_start - start + (probe["ready_seconds"] or 0)
                if not probe_passed(probe):
                    raise RuntimeError("probe lifecycle markers failed")
                metrics["binary_sha256"] = digest(binary)
            passed = True
        except (OSError, RuntimeError) as exc:
            reason = self.clean_text(str(exc))
        finally:
            duration = time.monotonic() - start
            if path == "qml_edit":
                qml.write_bytes(original)
            self.runs.append(
                {
                    "adapter": adapter,
                    "path": path,
                    "sample": index,
                    "warmup": warmup,
                    "start_condition": "fixed patch applied"
                    if path == "qml_edit"
                    else "command start; dependencies cached",
                    "end_condition": "ready + lifecycle/teardown validated"
                    + (" + core tests" if path in {"clean", "no_op"} else ""),
                    "duration_seconds": duration,
                    "passed": passed,
                    "reason": reason,
                    "metrics": metrics,
                    "steps": self.current_steps,
                }
            )
            print(
                f"{adapter} {path} {index}{' warmup' if warmup else ''}: {'PASS' if passed else 'FAIL'} {duration:.3f}s",
                flush=True,
            )
            self.save()
        if not passed:
            raise RuntimeError(reason)

    def save(self) -> None:
        aggregates = summary(self.runs)
        budgets = {}
        for adapter in ADAPTERS:
            budgets[adapter] = {}
            for path, limit in (("clean", 600), ("qml_edit", 10), ("package", 900)):
                measured = aggregates[adapter][path]
                complete = measured["complete"] and not self.smoke
                within = measured["median_seconds"] <= limit if complete else None
                budgets[adapter][path] = {
                    "absolute_floor_seconds": limit,
                    "within_absolute_floor": within,
                    "verdict": "within_absolute_floor"
                    if within
                    else "not_evaluated"
                    if not complete
                    else "over_absolute_floor",
                    "python_ratio": "not_evaluated_no_equivalent_workload" if path == "qml_edit" else "not_applicable",
                }
        report = {
            "schema_version": 1,
            "protocol": "MIG-002-v0.1",
            "task": "MIG-004-B",
            "measurement_kind": "smoke" if self.smoke else "development_iteration",
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "host": {
                "os": platform.platform(),
                "machine": platform.machine(),
                "cpu_parallelism": 4,
                **host_metadata(),
            },
            "source": self.source_metadata
            | {
                "qml_patch": {
                    "before": LABEL,
                    "after": EDITED_LABEL,
                    "sha256": hashlib.sha256((LABEL + "\n" + EDITED_LABEL).encode()).hexdigest(),
                },
            },
            "tools": {
                "rust": self.version,
                "qt": tomllib.loads((ROOT / "native/qt-sdk.toml").read_text())["version"],
                "compiler": read_command([self.env["CXX"], "--version"]),
                "apple_sdk": read_command(["/usr/bin/xcrun", "--show-sdk-version"])
                if platform.system() == "Darwin"
                else None,
            },
            "workload": {
                "kind": "004-A synthetic worker and same QML",
                "pixels": [560, 360],
                "scale": 1,
                "mode": "debug",
                "platform": "offscreen",
                "renderer": "software",
                "style": "Basic",
                "display_language": "English",
                "macos_deployment_target": self.env.get("MACOSX_DEPLOYMENT_TARGET"),
            },
            "cache": {
                "cargo_registry": "pre-fetched; --locked --offline",
                "clean": "entire per-adapter target removed before each sample",
                "no_op": "one excluded warmup per adapter then five samples",
                "qml": "external file; OS page cache uncontrolled; private warm disk cache",
                "package": "existing debug binary; separate bundle/archive/extraction per sample",
            },
            "environment": {
                key: self.clean_text(value)
                for key, value in self.env.items()
                if key
                in {
                    "CARGO_BUILD_JOBS",
                    "QMAKE",
                    "QT_QPA_PLATFORM",
                    "QT_QUICK_BACKEND",
                    "QT_QUICK_CONTROLS_STYLE",
                    "XDG_CACHE_HOME",
                    "QML_DISK_CACHE_PATH",
                    "MACOSX_DEPLOYMENT_TARGET",
                    "CC",
                    "CXX",
                }
            },
            "runs": self.runs,
            "python_reference_runs": self.reference_runs,
            "summary": aggregates,
            "budgets": budgets,
            "correctness": "passed"
            if self.runs and all(r["passed"] for r in self.runs + self.reference_runs)
            else "failed_or_not_run",
            "budget_verdict": "partial_absolute_only"
            if not self.smoke and all(v["complete"] for a in aggregates.values() for v in a.values())
            else "not_evaluated",
            "limitations": [
                f"{platform.system()}/{platform.machine()} host only; other OS/CPU not run",
                "no fresh OS, physical screen, Gatekeeper, notarization, or distribution",
                "debug bundle, not release runtime performance",
                "no equivalent Python display-edit baseline; ratio budget not evaluated",
                "no DSP/core-edit measurement until MIG-006-A; no audio/graph/10-minute runtime benchmark",
                "host system dependencies retained; no clean OS test",
                "cache and OS scheduling effects not controlled; no causal language-speed conclusion",
            ],
            "artifacts_directory": self.clean_text(str(self.scratch)),
        }
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        self.report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


def read_command(command: list[str], *, strip: bool = True) -> str:
    output = subprocess.check_output(command, cwd=ROOT, text=True, stderr=subprocess.PIPE)  # noqa: S603 - fixed read-only argv
    return output.strip() if strip else output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qt-prefix", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if platform.system() not in {"Darwin", "Linux"}:
        parser.error("this packaging protocol supports macOS and Linux only")
    prefix = args.qt_prefix.resolve()
    expected = tomllib.loads((ROOT / "native/qt-sdk.toml").read_text())["version"]
    if read_command([str(prefix / "bin/qmake"), "-query", "QT_VERSION"]) != expected:
        parser.error("Qt SDK version mismatch")
    benchmark = Benchmark(prefix, args.report.resolve(), args.smoke)
    print(f"Isolated artifacts: {benchmark.scratch}", flush=True)
    try:
        for path, count in COUNTS.items():
            if path == "no_op" and not args.smoke:
                for adapter in ADAPTERS:
                    benchmark.sample(adapter, path, 0, warmup=True)
            for index in range(1, (1 if args.smoke else count) + 1):
                for adapter in ADAPTERS:
                    benchmark.sample(adapter, path, index)
        for index in range(1, (1 if args.smoke else 3) + 1):
            benchmark.reference(index)
    except (OSError, RuntimeError) as exc:
        print(f"FAILED: {exc}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
