"""Exercise desktop action dispatch with a fake Cargo; never start a GUI or audio."""

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parent.parent
ENVIRONMENT = ROOT / ".codex/environments/environment.toml"


class DesktopActionsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="measurelab-actions-")
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name) / "project with spaces 日本語"
        self.scripts = self.project / "scripts"
        self.scripts.mkdir(parents=True)
        for name in ("debug.sh", "cargo.sh", "debug.ps1", "cargo.ps1", "pwsh.cmd"):
            shutil.copy2(ROOT / "scripts" / name, self.scripts / name)
        self.capture = self.project / "cargo-arguments.json"
        self.fake_bin = self.project / "fake-bin"
        self.fake_bin.mkdir()
        recorder = self.fake_bin / "record.py"
        recorder.write_text(
            "import json, os, pathlib, sys\n"
            "pathlib.Path(os.environ['MEASURELAB_TEST_CAPTURE']).write_text(\n"
            "    json.dumps({'args': sys.argv[1:], 'cwd': os.getcwd(),\n"
            "                'backtrace': os.environ.get('RUST_BACKTRACE')}), encoding='utf-8')\n"
            "sys.exit(int(os.environ.get('MEASURELAB_TEST_CARGO_EXIT', '0')))\n",
            encoding="utf-8",
        )
        if os.name == "nt":
            cargo = self.fake_bin / "cargo.cmd"
            cargo.write_text(
                '@echo off\n"%MEASURELAB_TEST_PYTHON%" "%~dp0record.py" %*\nexit /b %errorlevel%\n',
                encoding="ascii",
            )
        else:
            cargo = self.fake_bin / "cargo"
            cargo.write_text(
                f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(recorder))} "$@"\n',
                encoding="utf-8",
            )
            cargo.chmod(0o755)
        self.environment = os.environ.copy()
        self.environment["PATH"] = str(self.fake_bin) + os.pathsep + self.environment.get("PATH", "")
        self.environment["MEASURELAB_TEST_CAPTURE"] = str(self.capture)
        self.environment["MEASURELAB_TEST_PYTHON"] = sys.executable
        self.environment.pop("RUST_BACKTRACE", None)
        self.platform = "win32" if os.name == "nt" else "darwin"

    def run_launcher(self, *arguments, cargo=False):
        name = "cargo" if cargo else "debug"
        if os.name == "nt":
            command = [str(self.scripts / "pwsh.cmd"), "-File", str(self.scripts / f"{name}.ps1"), *arguments]
        else:
            command = ["bash", str(self.scripts / f"{name}.sh"), *arguments]
        return subprocess.run(  # noqa: S603 - fixed copied scripts and fake Cargo in an owned temporary project
            command,
            check=False,
            cwd=self.temporary.name,
            env=self.environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )

    def record(self):
        return json.loads(self.capture.read_text(encoding="utf-8"))

    def test_saved_actions_are_os_specific_and_setup_is_opt_in(self):
        configuration = tomllib.loads(ENVIRONMENT.read_text(encoding="utf-8"))
        self.assertEqual(configuration["version"], 1)
        self.assertEqual(configuration["setup"], {"script": ""})
        actions = configuration["actions"]
        self.assertEqual({action["platform"] for action in actions}, {"darwin", "win32"})
        names = [
            {action["name"] for action in actions if action["platform"] == platform} for platform in ("darwin", "win32")
        ]
        self.assertEqual(names[0], names[1])
        for platform in ("darwin", "win32"):
            selected = [action for action in actions if action["platform"] == platform]
            self.assertEqual(len(selected), len(names[0]))
        for action in actions:
            if action["platform"] == "darwin":
                self.assertNotIn(".ps1", action["command"])
                self.assertNotIn(".cmd", action["command"])
            else:
                self.assertTrue(action["command"].startswith("./scripts/pwsh.cmd -File ./scripts/"))

    def test_every_configured_command_dispatches_without_starting_an_app(self):
        configuration = tomllib.loads(ENVIRONMENT.read_text(encoding="utf-8"))
        expectations = {
            "GUI 起動": ["run", "--locked", "--profile", "dev-fast", "--", "--compact"],
            "CLI 起動確認": ["run", "--locked", "--profile", "dev-fast", "--", "--help"],
            "GPU 描画確認": ["run", "--locked", "--profile", "dev-fast", "--", "--gpu-smoke"],
            "コアテスト": ["test", "--locked", "--no-default-features"],
            "全 Rust テスト": ["test", "--locked", "--all-targets", "--all-features"],
            "Rust 静的検査": ["clippy", "--locked", "--all-targets", "--all-features", "--", "-D", "warnings"],
        }
        for action in configuration["actions"]:
            if action["platform"] != self.platform:
                continue
            with self.subTest(action=action["name"]):
                self.capture.unlink(missing_ok=True)
                command = (
                    [shutil.which("pwsh"), "-NoLogo", "-NoProfile", "-Command", action["command"]]
                    if os.name == "nt"
                    else ["bash", "-c", action["command"]]
                )
                result = subprocess.run(  # noqa: S603 - trusted repository action dispatched only to fake Cargo
                    command,
                    check=False,
                    cwd=self.project,
                    env=self.environment,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.record()["args"], expectations[action["name"]])

    def test_profiles_explicit_qa_and_argument_boundaries(self):
        cases = [
            ([], ["run", "--locked", "--profile", "dev-fast", "--"]),
            (["--release", "--compact"], ["run", "--locked", "--profile", "release", "--", "--compact"]),
            (["--full-debug", "--demo"], ["run", "--locked", "--profile", "dev", "--features", "qa", "--", "--demo"]),
            (["--ui-smoke"], ["run", "--locked", "--profile", "dev-fast", "--features", "qa", "--", "--ui-smoke"]),
            (
                ["--", "--release", "device with spaces 日本語"],
                ["run", "--locked", "--profile", "dev-fast", "--", "--release", "device with spaces 日本語"],
            ),
            (["--"], ["run", "--locked", "--profile", "dev-fast", "--"]),
        ]
        for arguments, expected in cases:
            with self.subTest(arguments=arguments):
                result = self.run_launcher(*arguments)
                self.assertEqual(result.returncode, 0, result.stderr)
                record = self.record()
                self.assertEqual(record["args"], expected)
                self.assertEqual(Path(record["cwd"]).resolve(), self.project.resolve())
                self.assertEqual(record["backtrace"], "1")

    def test_help_does_not_build_and_existing_backtrace_is_preserved(self):
        result = self.run_launcher("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Usage:", result.stdout)
        self.assertFalse(self.capture.exists())
        self.environment["RUST_BACKTRACE"] = "full"
        result = self.run_launcher("--compact")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.record()["backtrace"], "full")

    def test_failed_cargo_exit_reaches_the_caller(self):
        self.environment["MEASURELAB_TEST_CARGO_EXIT"] = "17"
        for cargo in (False, True):
            with self.subTest(cargo=cargo):
                result = self.run_launcher("--version", cargo=cargo)
                self.assertEqual(result.returncode, 17, result.stderr)


if __name__ == "__main__":
    unittest.main()
