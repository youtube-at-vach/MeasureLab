"""Regression checks for the CI decisions that skip expensive jobs."""

import subprocess
import sys
import unittest
from pathlib import Path

from ci_changes import classify


class ChangesTests(unittest.TestCase):
    def assert_selected(self, paths, *checks):
        self.assertEqual({check for check, enabled in classify(paths).items() if enabled}, set(checks))

    def test_rust_sources_and_benches_require_rust_checks(self):
        for path in ["src/lib.rs", "tests/launch_options.rs", "benches/common/mod.rs"]:
            with self.subTest(path=path):
                self.assert_selected([path], "rust", "msrv", "i18n")

    def test_build_and_dependency_changes_select_all_packages(self):
        for path in ["Cargo.toml", "Cargo.lock", ".cargo/config.toml", "rust-toolchain.toml", "build.rs"]:
            with self.subTest(path=path):
                self.assert_selected([path], "rust", "msrv", "windows_package", "macos_package", "linux_package")
        self.assert_selected(["scripts/ci_artifacts.py"], "windows_package", "macos_package", "linux_package")

    def test_platform_specific_package_inputs_select_only_the_affected_package(self):
        self.assert_selected(["packaging/windows/MeasureLab.iss", "scripts/windows_shell_link.ps1"], "windows_package")
        self.assert_selected([".github/workflows/build_macos.yml", "scripts/bundle-macos.sh"], "macos_package")
        self.assert_selected(["scripts/test_linux_package.py", "packaging/linux/README.txt"], "linux_package")

    def test_ci_policy_changes_require_every_check(self):
        for path in [".github/workflows/ci.yml", "scripts/ci_changes.py", "scripts/test_ci_changes.py"]:
            self.assertTrue(all(classify([path]).values()))

    def test_runner_and_dev_action_tests_follow_their_inputs(self):
        self.assert_selected(["scripts/qa_gui_redesign.py", "scripts/profile-stage2.sh"], "qa")
        self.assert_selected(["scripts/test_qa_spectrogram.py"], "qa")
        self.assert_selected([".codex/environments/environment.toml", "scripts/debug.sh"], "dev_actions")
        self.assert_selected(["scripts/setup_dev_env.sh"], "dev_actions")

    def test_manual_site_and_build_inputs_require_web_build(self):
        for path in [
            "docs/index.md",
            "docs-rust/index.en.md",
            "download-site/package-lock.json",
            "mkdocs-rust.yml",
            "requirements-docs.txt",
            "version.json",
            "rust-release.json",
            "scripts/build_pages.py",
        ]:
            with self.subTest(path=path):
                self.assert_selected([path], "web")

    def test_contributor_documents_only_need_static_checks(self):
        self.assert_selected(
            [
                "guide/CURRENT_DIRECTION.md",
                "README.md",
                ".github/assets/readme/rust-workspace.png",
                "misc/extract_changelog.py",
            ]
        )

    def test_catalogs_metadata_tools_and_gui_calls_require_i18n_checks(self):
        for path in ["locales/common/ja.yml", "i18n/source-hashes.json", "i18n/translation-task.json"]:
            with self.subTest(path=path):
                self.assert_selected([path], "rust", "i18n")
        for path in ["scripts/test_i18n.py", "scripts/translate.py"]:
            with self.subTest(path=path):
                self.assert_selected([path], "i18n")
        self.assertTrue(classify(["src/i18n.rs"])["i18n"])
        self.assert_selected(["scripts/i18n.py"], "i18n", "qa")
        self.assert_selected(["requirements-i18n.txt"], "web", "i18n", "qa")

    def test_unknown_inputs_fail_safe_and_mixed_changes_are_combined(self):
        self.assertTrue(all(classify(["new-build-input.json"]).values()))
        self.assert_selected(["src/lib.rs", "docs/index.md"], "rust", "msrv", "web", "i18n")

    def test_deleted_files_are_classified_by_path_and_empty_diff_is_safe(self):
        self.assertTrue(classify(["src/deleted.rs"])["rust"])
        self.assert_selected([])

    def test_cli_handles_nul_paths_and_full_or_pages_override(self):
        script = str(Path(__file__).with_name("ci_changes.py"))
        for args, paths, expected in [
            ([], b"docs/page with\nnewline.md\0", {"web"}),
            (["--all"], b"", set(classify([]))),
            (["--web"], b"README.md\0", {"web"}),
        ]:
            with self.subTest(args=args):
                result = subprocess.run(  # noqa: S603 - fixed local script and literal arguments
                    [sys.executable, script, *args], input=paths, capture_output=True, check=True
                )
                flags = dict(line.split("=") for line in result.stdout.decode().splitlines())
                self.assertEqual(flags, {check: str(check in expected).lower() for check in classify([])})


if __name__ == "__main__":
    unittest.main()
