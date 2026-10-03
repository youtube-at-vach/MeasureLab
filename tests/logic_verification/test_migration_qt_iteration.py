"""Benchmark reports must retain failures and reject developer-SDK package fallback."""

import os
from pathlib import Path
import sys

import pytest

from scripts.migration_qt_iteration import (
    ADAPTERS,
    COUNTS,
    PASS,
    TEARDOWN,
    execute,
    linux_package_passed,
    loaded_linux_paths,
    package_environment,
    package_passed,
    probe_passed,
    summary,
)


def successful(output=""):
    return {
        "exit_code": 0,
        "reason": None,
        "ready_seconds": 0.1,
        "output": f"PROBE_READY\n{PASS}\n{TEARDOWN}\n{output}",
    }


@pytest.mark.parametrize(
    "bad", ["PROBE_FAIL broken", "TypeError: broken", "ReferenceError: stale", "failed to load QML"]
)
def test_clean_exit_with_error_is_not_accepted(bad):
    assert not probe_passed(successful(bad))


def test_exit_ready_and_teardown_are_all_required():
    for key, value in [("exit_code", 1), ("reason", "timeout"), ("ready_seconds", None), ("output", "PROBE_READY")]:
        assert not probe_passed(successful() | {key: value})


def test_ready_is_timestamped_before_completion(tmp_path):
    result = execute(
        [sys.executable, "-u", "-c", "import time; print('PROBE_READY'); time.sleep(.2)"], tmp_path, dict(os.environ), 2
    )
    assert result["exit_code"] == 0
    assert result["ready_seconds"] < result["duration_seconds"] - 0.1


def test_timeout_is_preserved_with_partial_output(tmp_path):
    result = execute(
        [sys.executable, "-u", "-c", "import time; print('PROBE_READY'); time.sleep(10)"],
        tmp_path,
        dict(os.environ),
        0.2,
    )
    assert result["exit_code"] is None
    assert result["reason"] == "timeout"
    assert "PROBE_READY" in result["output"]


@pytest.mark.parametrize(
    "foreign", ["/developer/qt/lib/QtGui.framework/QtGui", "/developer/qt/plugins/libqoffscreen.dylib"]
)
def test_package_rejects_any_loaded_qt_outside_bundle(foreign):
    app = Path("/relocated/Probe.app")
    output = (
        f"PROBE_QML {app}/Contents/Resources/Main.qml\n"
        f"dyld[12]: <UUID> {app}/Contents/Frameworks/QtCore.framework/QtCore\n"
    )
    assert package_passed(successful(output), app)
    assert package_passed(successful(output + "dyld[12]: <UUID> /usr/lib/system/libquarantine.dylib\n"), app)
    assert not package_passed(successful(output + f"dyld[12]: <UUID> {foreign}\n"), app)


def test_package_requires_library_trace_and_bundle_qml():
    app = Path("/relocated/Probe.app")
    assert not package_passed(successful(f"PROBE_QML {app}/Contents/Resources/Main.qml"), app)
    assert not package_passed(successful(f"dyld[1]: <UUID> {app}/Contents/Frameworks/QtCore.framework/QtCore"), app)


def test_linux_package_requires_actual_qt_plugin_and_resource_paths(tmp_path):
    app = tmp_path / "evaluation"
    output = (
        f"PROBE_QML {app}/share/measurelab-evaluation/Main.qml\n"
        f"  12: calling init: {app}/lib/libQt6Core.so.6\n"
        f"  12: calling init: {app}/bin/../plugins/platforms/libqoffscreen.so\n"
        "  12: calling init: /lib/x86_64-linux-gnu/libc.so.6\n"
    )
    assert linux_package_passed(successful(output), app)
    for foreign in (
        "/developer/libQt6Gui.so.6",
        "/usr/lib/libQt6Gui.so.6",
        "/developer/libcustomplugin.so",
        "/usr/lib/qt6/qml/QtQml/Models/libmodelsplugin.so",
    ):
        assert not linux_package_passed(successful(output + f"  12: calling init: {foreign}\n"), app)
    assert not linux_package_passed(successful(output.replace("libqoffscreen.so", "other.so")), app)
    assert not linux_package_passed(successful(output.replace("libQt6Core.so.6", "other.so")), app)
    assert not linux_package_passed(successful(output.replace("share/measurelab-evaluation", "developer")), app)


def test_linux_library_search_attempts_are_not_loaded_library_evidence():
    output = "12: trying file=/developer/libQt6Core.so.6\n12: calling init: /package/lib/libQt6Core.so.6\n"
    assert loaded_linux_paths(output) == ["/package/lib/libQt6Core.so.6"]
    assert not linux_package_passed(successful(output), Path("/package"))


def test_package_environment_removes_inherited_sdk(monkeypatch, tmp_path):
    monkeypatch.setenv("DYLD_FRAMEWORK_PATH", "/developer/lib")
    monkeypatch.setenv("QML_IMPORT_PATH", "/developer/qml")
    monkeypatch.setenv("MEASURELAB_PROBE_QML", "/developer/Main.qml")
    env = package_environment(tmp_path)
    assert "DYLD_FRAMEWORK_PATH" not in env
    assert "QML_IMPORT_PATH" not in env
    assert "MEASURELAB_PROBE_QML" not in env
    assert env["PATH"] == "/usr/bin:/bin:/usr/sbin:/sbin"
    assert env["HOME"] == str(tmp_path / "home")


def test_summary_excludes_warmup_and_does_not_hide_failures():
    runs = [
        {"adapter": adapter, "path": path, "warmup": False, "passed": True, "duration_seconds": float(i)}
        for adapter in ADAPTERS
        for path, count in COUNTS.items()
        for i in range(1, count + 1)
    ]
    runs.append({"adapter": ADAPTERS[0], "path": "no_op", "warmup": True, "passed": True, "duration_seconds": 900})
    result = summary(runs)[ADAPTERS[0]]["no_op"]
    assert result["median_seconds"] == 3
    assert result["samples"] == 5
    assert result["complete"]
    runs[0]["passed"] = False
    assert not summary(runs)[ADAPTERS[0]]["clean"]["complete"]


def test_smoke_sample_cannot_satisfy_protocol_counts():
    result = summary(
        [{"adapter": ADAPTERS[0], "path": "clean", "warmup": False, "passed": True, "duration_seconds": 1}]
    )
    assert result[ADAPTERS[0]]["clean"]["all_passed"]
    assert not result[ADAPTERS[0]]["clean"]["complete"]
    assert not result[ADAPTERS[1]]["clean"]["all_passed"]


def test_failed_edit_restores_copy_and_preserves_checkout(monkeypatch, tmp_path):
    from scripts import migration_qt_iteration as runner

    qml = tmp_path / "native/qml/Main.qml"
    qml.parent.mkdir(parents=True)
    qml.write_text(runner.LABEL)
    (tmp_path / "native/rust-toolchain.toml").write_text('[toolchain]\nchannel="1.98.1"\n')
    target = tmp_path / "native/target/existing-output"
    target.parent.mkdir()
    target.write_text("preserve")
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "read_command", lambda command, **kwargs: "test-git-metadata")
    benchmark = runner.Benchmark(tmp_path / "sdk", tmp_path / "report.json", False)
    monkeypatch.setattr(benchmark, "save", lambda: None)

    def fail(*args):
        raise RuntimeError("injected compiler failure")

    monkeypatch.setattr(benchmark, "cargo_step", fail)
    with pytest.raises(RuntimeError, match="injected compiler failure"):
        benchmark.sample(ADAPTERS[0], "qml_edit", 1)
    assert qml.read_text() == runner.LABEL
    assert (benchmark.scratch / "native/qml/Main.qml").read_text() == runner.LABEL
    assert target.read_text() == "preserve"
    assert not (benchmark.scratch / "native/target").exists()
    assert not benchmark.runs[0]["passed"]
