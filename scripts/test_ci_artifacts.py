"""Check downloadable artifact contents and reject incomplete or mismatched builds."""

import json
import os
import tempfile
import tomllib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import ci_artifacts as artifacts
import linux_package


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="MeasureLab artifact 検証 ")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.version = tomllib.loads((artifacts.ROOT / "Cargo.toml").read_text())["package"]["version"]
        self.sha = "fixture-source"

    def fixture(self, platform):
        extension, archive, target, _ = artifacts.PLATFORMS[platform]
        assets = self.work / platform
        assets.mkdir()
        base = f"MeasureLab-v{self.version}-{platform}"
        (assets / (base + extension)).write_bytes(b"native package fixture")
        if archive:
            (assets / (base + archive)).write_bytes(b"alternate archive fixture")
        info = {
            "version": self.version,
            "source_sha": self.sha,
            "source_dirty": False,
            "target": target,
            "profile": "release",
            "features": ["desktop"],
            "crt_static": True,
            "executable_sha256": "fixture-hash",
            "payload_sha256": {"usr/bin/measurelab": "fixture-hash"},
            "glibc_required": "2.35",
        }
        manifest = assets / (base + "-build-info.json")
        manifest.write_text(json.dumps(info), encoding="utf-8")
        self.checksums(assets, platform)
        return assets, base, manifest, info

    def checksums(self, assets, platform):
        checksum_name = f"SHA256SUMS-{platform}.txt"
        (assets / checksum_name).write_text(
            "".join(
                f"{artifacts.digest(path)}  {path.name}\n"
                for path in sorted(assets.iterdir())
                if path.name != checksum_name
            ),
            encoding="ascii",
        )

    def test_all_platforms_stage_exactly_one_native_package_and_three_support_files(self):
        for platform, (extension, _, _, os_name) in artifacts.PLATFORMS.items():
            with self.subTest(platform=platform):
                assets, base, _, _ = self.fixture(platform)
                output = artifacts.prepare(assets, platform, self.sha)
                expected = {base + extension, base + "-build-info.json", "README.txt"}
                checksum_name = f"SHA256SUMS-{platform}.txt"
                self.assertEqual({p.name for p in output.iterdir()}, expected | {checksum_name})
                entries = (output / checksum_name).read_text().splitlines()
                self.assertEqual(len(entries), len(expected))
                for entry in entries:
                    checksum, name = entry.split("  ", 1)
                    self.assertIn(name, expected)
                    self.assertEqual(artifacts.digest(output / name), checksum)
                self.assertEqual(
                    (output / "README.txt").read_bytes(),
                    (artifacts.ROOT / "packaging" / os_name / "README.txt").read_bytes(),
                )
                # The release directory is retained intact for existing release consumers.
                self.assertEqual(len(list(assets.iterdir())), 3 if os_name == "macos" else 4)

    def test_missing_empty_corrupted_symlink_and_stale_assets_fail(self):
        assets, base, _, _ = self.fixture("windows-x64")
        installer = assets / (base + "-setup.exe")
        original = installer.read_bytes()
        for contents in (b"", b"corrupted"):
            with self.subTest(contents=contents):
                installer.write_bytes(contents)
                with self.assertRaises(ValueError):
                    artifacts.prepare(assets, "windows-x64", self.sha)
        installer.unlink()
        with self.assertRaisesRegex(ValueError, "asset set"):
            artifacts.prepare(assets, "windows-x64", self.sha)
        target = self.work / "installer"
        target.write_bytes(original)
        installer.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "non-regular"):
            artifacts.prepare(assets, "windows-x64", self.sha)
        installer.unlink()
        installer.write_bytes(original)
        (assets / "intermediate.pdb").touch()
        with self.assertRaisesRegex(ValueError, "asset set"):
            artifacts.prepare(assets, "windows-x64", self.sha)

    def test_checksums_reject_missing_duplicate_and_path_escape_entries(self):
        assets, _, _, _ = self.fixture("macos-arm64")
        checksums = assets / "SHA256SUMS-macos-arm64.txt"
        correct = checksums.read_text()
        for text in ("", correct + correct, correct.replace("MeasureLab-", "../MeasureLab-")):
            with self.subTest(text=text):
                checksums.write_text(text)
                with self.assertRaises(ValueError):
                    artifacts.prepare(assets, "macos-arm64", self.sha)

    def test_mismatched_source_dirty_qa_target_and_dynamic_crt_fail_even_with_valid_checksums(self):
        platform = "windows-x64"
        assets, _, manifest, info = self.fixture(platform)
        for key, value in (
            ("version", "9.99.99"),
            ("source_sha", "another-source"),
            ("source_dirty", True),
            ("target", "x86_64-pc-windows-gnu"),
            ("profile", "dev-fast"),
            ("features", ["desktop", "qa"]),
            ("crt_static", False),
        ):
            with self.subTest(key=key):
                manifest.write_text(json.dumps({**info, key: value}))
                self.checksums(assets, platform)
                with self.assertRaisesRegex(ValueError, "build identity"):
                    artifacts.prepare(assets, platform, self.sha)

    def test_linux_download_verification_accepts_native_artifact_without_tar(self):
        assets, _, _, _ = self.fixture("linux-x86_64")
        output = artifacts.prepare(assets, "linux-x86_64", self.sha)
        args = linux_package.argparse.Namespace(
            assets=output,
            source_sha=self.sha,
            require_clean=True,
            max_glibc="2.35",
            appimage_only=True,
            runtime=False,
            gpu=False,
        )
        linux_package.verify(args)
        readme = output / "README.txt"
        readme.write_text("changed instructions")
        self.checksums(output, "linux-x86_64")
        with self.assertRaisesRegex(ValueError, "README mismatch"):
            linux_package.verify(args)

    def test_summary_links_download_and_explains_linux_executable_permission(self):
        report = self.work / "summary.md"
        with patch.dict(os.environ, GITHUB_STEP_SUMMARY=str(report), GITHUB_SHA=self.sha):
            artifacts.summary("linux-x86_64", "https://github.com/example/artifact")
        text = report.read_text()
        for expected in ("https://github.com/example/artifact", "chmod +x", "--appimage-extract-and-run", self.sha):
            self.assertIn(expected, text)

    def test_linux_native_runtime_checks_payload_normal_options_and_gpu_without_tar(self):
        assets, _, manifest, info = self.fixture("linux-x86_64")
        binary = self.work / "measurelab"
        binary.write_bytes(b"executable fixture")
        info.update(
            executable_sha256=artifacts.digest(binary),
            payload_sha256={"usr/bin/measurelab": artifacts.digest(binary)},
            needed_libraries=["libc.so.6"],
        )
        manifest.write_text(json.dumps(info))
        self.checksums(assets, "linux-x86_64")
        output = artifacts.prepare(assets, "linux-x86_64", self.sha)
        args = SimpleNamespace(
            assets=output,
            source_sha=self.sha,
            require_clean=True,
            max_glibc="2.35",
            appimage_only=True,
            runtime=True,
            gpu=True,
        )

        def run(command, **kwargs):
            if "--appimage-extract" in command:
                extracted = Path(kwargs["cwd"]) / "squashfs-root"
                (extracted / "usr/bin").mkdir(parents=True)
                (extracted / "usr/bin/measurelab").write_bytes(binary.read_bytes())
                (extracted / "build-info.json").write_text(json.dumps(info))
            qa = command[-1] in {
                "--demo",
                "--ui-smoke",
                "--lockin-smoke",
                "--physical-lockin-smoke",
                "--multichannel-smoke",
            }
            return SimpleNamespace(
                returncode=int(qa), stdout="MeasureLab", stderr="requires --features qa" if qa else ""
            )

        with (
            patch.object(linux_package, "run", side_effect=run) as process,
            patch.object(
                linux_package,
                "audit_binary",
                return_value={
                    "glibc_required": "2.35",
                    "needed_libraries": info["needed_libraries"],
                },
            ),
        ):
            linux_package.verify(args)
        commands = [call.args[0] for call in process.call_args_list]
        self.assertTrue(any("--appimage-extract-and-run" in cmd and "--help" in cmd for cmd in commands))
        self.assertTrue(any("--gpu-smoke" in cmd for cmd in commands))


if __name__ == "__main__":
    unittest.main()
