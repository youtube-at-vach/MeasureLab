"""Regression checks for the CI decisions that skip expensive jobs."""

import subprocess
import sys
import unittest
from pathlib import Path

from ci_changes import classify


class ChangesTests(unittest.TestCase):
    def test_rust_sources_and_benches_require_rust_checks(self):
        for path in ["src/lib.rs", "tests/launch_options.rs", "benches/common/mod.rs"]:
            with self.subTest(path=path):
                self.assertEqual(classify([path]), dict(rust=True, msrv=True, web=False, i18n=True))
        self.assertEqual(classify(["scripts/bundle-macos.sh"]), dict(rust=True, msrv=False, web=False, i18n=False))

    def test_dependency_and_workflow_changes_require_every_check(self):
        for path in [
            "Cargo.toml",
            "Cargo.lock",
            ".cargo/config.toml",
            "rust-toolchain.toml",
            ".github/workflows/ci.yml",
            "scripts/ci_changes.py",
            "scripts/test_ci_changes.py",
        ]:
            with self.subTest(path=path):
                self.assertTrue(all(classify([path]).values()))

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
                self.assertEqual(classify([path]), dict(rust=False, msrv=False, web=True, i18n=False))

    def test_contributor_documents_only_need_static_checks(self):
        self.assertEqual(
            classify(["guide/rust/PLAN.md", "README.md", "misc/extract_changelog.py"]),
            dict(rust=False, msrv=False, web=False, i18n=False),
        )

    def test_catalogs_metadata_tools_and_gui_calls_require_i18n_checks(self):
        for path in ["locales/common/ja.yml", "i18n/source-hashes.json", "i18n/translation-task.json"]:
            with self.subTest(path=path):
                self.assertEqual(classify([path]), dict(rust=True, msrv=False, web=False, i18n=True))
        for path in ["scripts/i18n.py", "scripts/test_i18n.py"]:
            with self.subTest(path=path):
                self.assertEqual(classify([path]), dict(rust=False, msrv=False, web=False, i18n=True))
        self.assertTrue(classify(["src/i18n.rs"])["i18n"])
        self.assertEqual(classify(["requirements-i18n.txt"]), dict(rust=False, msrv=False, web=True, i18n=True))

    def test_unknown_inputs_fail_safe_and_mixed_changes_are_combined(self):
        self.assertTrue(all(classify(["new-build-input.json"]).values()))
        self.assertEqual(
            classify(["src/lib.rs", "docs/index.md"]),
            dict(rust=True, msrv=True, web=True, i18n=True),
        )

    def test_deleted_files_are_classified_by_path_and_empty_diff_is_safe(self):
        self.assertTrue(classify(["src/deleted.rs"])["rust"])
        self.assertEqual(classify([]), dict(rust=False, msrv=False, web=False, i18n=False))

    def test_cli_handles_nul_paths_and_full_or_pages_override(self):
        script = str(Path(__file__).with_name("ci_changes.py"))
        for args, paths, expected in [
            ([], b"docs/page with\nnewline.md\0", "rust=false\nmsrv=false\nweb=true\ni18n=false\n"),
            (["--all"], b"", "rust=true\nmsrv=true\nweb=true\ni18n=true\n"),
            (["--web"], b"README.md\0", "rust=false\nmsrv=false\nweb=true\ni18n=false\n"),
        ]:
            with self.subTest(args=args):
                result = subprocess.run(  # noqa: S603 - fixed local script and literal arguments
                    [sys.executable, script, *args], input=paths, capture_output=True, check=True
                )
                # Python writes native CRLF on Windows; the output fields are identical.
                self.assertEqual(result.stdout.decode().replace("\r\n", "\n"), expected)


if __name__ == "__main__":
    unittest.main()
