"""Exercise payload integrity, unsafe archives and the actual portable launcher."""

import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from linux_package import CHECKSUMS, create_appdir, digest, run, verify_checksums, verify_tar


class LinuxPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="MeasureLab 梱包 ")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.directory = self.work / "MeasureLab"
        self.info = {"version": "0.10.0", "source_sha": "test-fixture"}
        # Exercise the real launcher without requiring Rust, a GPU or an audio device.
        printer = self.work / "argument-printer"
        printer.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n")
        create_appdir(self.directory, printer, self.info)
        self.archive = self.work / "package.tar.gz"
        self.write_archive()

    def write_archive(self, extra=None):
        with tarfile.open(self.archive, "w:gz") as archive:
            archive.add(self.directory, arcname="MeasureLab")
            if extra:
                member, data = extra
                archive.addfile(member, io.BytesIO(data) if member.isfile() else None)

    def test_launcher_preserves_unicode_spaces_and_literal_arguments(self):
        result = run([self.directory / "AppRun", "日本語 file", "$(no-shell)", "--help"], cwd=self.work)
        self.assertEqual(result.stdout, "日本語 file\n$(no-shell)\n--help\n")
        verify_tar(self.archive, self.info)

    def test_tampered_or_missing_payload_is_rejected(self):
        binary = self.directory / "usr/bin/measurelab"
        binary.write_bytes(b"changed")
        self.write_archive()
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            verify_tar(self.archive, self.info)
        binary.unlink()
        self.write_archive()
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            verify_tar(self.archive, self.info)

    def test_archive_identity_and_executable_permissions_are_checked(self):
        info_path = self.directory / "build-info.json"
        original = info_path.read_text()
        info_path.write_text(json.dumps({**self.info, "source_sha": "another-build"}))
        self.write_archive()
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            verify_tar(self.archive, self.info)
        info_path.write_text(original)
        (self.directory / "AppRun").chmod(0o644)
        self.write_archive()
        with self.assertRaisesRegex(ValueError, "executable permission"):
            verify_tar(self.archive, self.info)

    def test_traversal_symlinks_and_duplicate_members_are_rejected(self):
        for name, kind in [
            ("../escape", tarfile.REGTYPE),
            ("/absolute", tarfile.REGTYPE),
            ("MeasureLab/link", tarfile.SYMTYPE),
            ("MeasureLab/usr/bin/measurelab", tarfile.REGTYPE),
        ]:
            with self.subTest(name=name):
                member = tarfile.TarInfo(name)
                member.type = kind
                member.linkname = "/etc/passwd" if kind == tarfile.SYMTYPE else ""
                self.write_archive((member, b""))
                with self.assertRaisesRegex(ValueError, "Unexpected archive member"):
                    verify_tar(self.archive, self.info)

    def test_checksums_require_exact_files_and_reject_duplicates_or_path_escape(self):
        assets = self.work / "release"
        assets.mkdir()
        payload = assets / "package.AppImage"
        payload.write_bytes(b"fixture")
        correct = f"{digest(payload)}  {payload.name}\n"
        checksum_path = assets / CHECKSUMS
        checksum_path.write_text(correct)
        verify_checksums(assets, {payload.name})
        for contents in (correct + correct, correct.replace(payload.name, "../escape"), ""):
            with self.subTest(contents=contents):
                checksum_path.write_text(contents)
                with self.assertRaises(ValueError):
                    verify_checksums(assets, {payload.name})
        checksum_path.write_text(correct)
        payload.write_bytes(b"corrupted")
        with self.assertRaisesRegex(ValueError, "Invalid checksum"):
            verify_checksums(assets, {payload.name})
        (assets / "stale.AppImage").touch()
        with self.assertRaisesRegex(ValueError, "asset set"):
            verify_checksums(assets, {payload.name})


if __name__ == "__main__":
    unittest.main()
