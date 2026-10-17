"""Check macOS permissions, signed payload integrity and release identity failures."""

import copy
import json
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import macos_package as package


class MacosPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="MeasureLab 梱包 ")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.target = "x86_64-apple-darwin"
        self.value = package.version()
        self.bundle = self.work / "MeasureLab.app"
        self.binary = self.bundle / "Contents/MacOS/measurelab"
        self.binary.parent.mkdir(parents=True)
        self.binary.write_bytes(b"signed Mach-O fixture")
        self.binary.chmod(0o755)
        resources = self.bundle / "Contents/Resources"
        resources.mkdir()
        for name in ("MeasureLab.icns", "LICENSE", "README.txt"):
            (resources / name).write_bytes(name.encode())
        signature = self.bundle / "Contents/_CodeSignature/CodeResources"
        signature.parent.mkdir()
        signature.write_bytes(b"signed resource envelope fixture")
        self.info = {
            "version": self.value,
            "source_sha": "test-source-sha",
            "source_dirty": False,
            "target": self.target,
            "profile": "release",
            "features": ["desktop"],
            "minimum_macos": package.MINIMUM_MACOS,
            "signature": "adhoc",
            "notarized": False,
            "needed_libraries": ["/usr/lib/libSystem.B.dylib"],
        }
        (self.bundle / package.INFO_PATH).write_text(json.dumps(self.info))
        self.plist_path = self.bundle / "Contents/Info.plist"
        self.plist_path.write_bytes(plistlib.dumps(package.bundle_plist(self.value)))
        self.info["executable_sha256"] = package.digest(self.binary)
        self.info["payload_sha256"] = package.inventory(self.bundle)
        self.assets = self.work / "release"
        self.assets.mkdir()
        self.image_name, self.info_name, self.checksum_name = package.asset_names(self.value, self.target)
        (self.assets / self.image_name).write_bytes(b"DMG fixture; runtime checks run on macOS")
        self.write_assets(self.info)

    def write_assets(self, info):
        (self.assets / self.info_name).write_text(json.dumps(info))
        correct = "".join(
            f"{package.digest(self.assets / name)}  {name}\n" for name in (self.image_name, self.info_name)
        )
        (self.assets / self.checksum_name).write_text(correct)
        return correct

    def verify_assets(self, target=None):
        return package.verify_assets(self.assets, target or self.target, "test-source-sha", True)

    def test_microphone_purpose_and_audio_input_entitlement_survive_packaging(self):
        info = package.bundle_plist("0.10.0-rc.1")
        self.assertTrue(info["NSMicrophoneUsageDescription"].strip())
        self.assertEqual(info["CFBundleIdentifier"], "dev.measurelab.app")
        self.assertEqual(info["CFBundleShortVersionString"], "0.10.0")
        self.assertEqual(info["CFBundleVersion"], "0.10.0")
        self.assertEqual(info["LSMinimumSystemVersion"], package.MINIMUM_MACOS)
        with (package.ROOT / "packaging/macos/entitlements.plist").open("rb") as stream:
            self.assertEqual(plistlib.load(stream), {"com.apple.security.device.audio-input": True})
        # The old Python Remote Audio I/O and dynamic runtime exceptions are not
        # requirements of the Rust desktop executable.
        self.assertNotIn("NSLocalNetworkUsageDescription", info)

    def test_checksums_reject_corruption_stale_assets_duplicates_and_path_escape(self):
        self.verify_assets()
        checksum_path = self.assets / self.checksum_name
        correct = checksum_path.read_text()
        for contents in ("", correct + correct, correct.replace(self.image_name, "../escape.dmg")):
            with self.subTest(contents=contents):
                checksum_path.write_text(contents)
                with self.assertRaises(ValueError):
                    self.verify_assets()
        checksum_path.write_text(correct)
        (self.assets / self.image_name).write_bytes(b"corrupted image")
        with self.assertRaisesRegex(ValueError, "Invalid checksum"):
            self.verify_assets()
        (self.assets / "stale.dmg").touch()
        with self.assertRaisesRegex(ValueError, "asset set"):
            self.verify_assets()

    def test_wrong_source_architecture_qa_dirty_or_signing_identity_is_rejected(self):
        for key, value in (
            ("source_sha", "another-build"),
            ("target", "aarch64-apple-darwin"),
            ("features", ["desktop", "qa"]),
            ("profile", "dev-fast"),
            ("source_dirty", True),
            ("minimum_macos", "15.0"),
            ("signature", "unsigned"),
            ("notarized", True),
            ("executable_sha256", "wrong-digest"),
        ):
            with self.subTest(key=key):
                self.write_assets({**self.info, key: value})
                with self.assertRaisesRegex(ValueError, "build identity"):
                    self.verify_assets()
        self.write_assets(self.info)
        with self.assertRaisesRegex(ValueError, "asset set"):
            self.verify_assets("aarch64-apple-darwin")

    def test_signed_bundle_inventory_includes_signature_and_embedded_identity(self):
        self.assertIn(package.INFO_PATH, self.info["payload_sha256"])
        self.assertIn("Contents/_CodeSignature/CodeResources", self.info["payload_sha256"])
        for relative in self.info["payload_sha256"]:
            with self.subTest(path=relative):
                path = self.bundle / relative
                original = path.read_bytes()
                path.write_bytes(b"tampered")
                with self.assertRaises((ValueError, json.JSONDecodeError, plistlib.InvalidFileException)):
                    package.verify_bundle(self.bundle, self.info)
                path.write_bytes(original)
        (self.bundle / "unexpected-link").symlink_to(self.binary)
        with self.assertRaisesRegex(ValueError, "symlink"):
            package.inventory(self.bundle)

    def test_missing_permission_description_and_changed_bundle_identity_are_rejected(self):
        for key in ("NSMicrophoneUsageDescription", "CFBundleIdentifier", "LSMinimumSystemVersion"):
            with self.subTest(key=key):
                info = package.bundle_plist(self.value)
                del info[key]
                self.plist_path.write_bytes(plistlib.dumps(info))
                with self.assertRaisesRegex(ValueError, "metadata or microphone"):
                    package.verify_bundle(self.bundle, self.info)

    def test_signed_entitlement_and_hardened_runtime_are_verified(self):
        def result(args):
            if "--entitlements" in args:
                return subprocess.CompletedProcess(args, 0, plistlib.dumps(package.ENTITLEMENTS), b"")
            return subprocess.CompletedProcess(args, 0, b"", b"Signature=adhoc\nflags=0x10000(runtime)\n")

        with (
            patch.object(package, "run", side_effect=result),
            patch.object(package, "audit_binary", return_value={"needed_libraries": self.info["needed_libraries"]}),
            patch.object(package, "check_normal_options"),
        ):
            package.verify_bundle(self.bundle, self.info)
            wrong = subprocess.CompletedProcess([], 0, plistlib.dumps({}), b"")
            with patch.object(package, "run", side_effect=[result([]), result([]), wrong]):
                with self.assertRaisesRegex(ValueError, "entitlement"):
                    package.verify_bundle(self.bundle, self.info)
            unsigned = subprocess.CompletedProcess([], 0, b"", b"Signature=adhoc\nflags=0x0\n")
            with patch.object(package, "run", return_value=unsigned):
                with self.assertRaisesRegex(ValueError, "Hardened Runtime"):
                    package.verify_bundle(self.bundle, self.info)

    def test_binary_audit_rejects_wrong_arch_newer_macos_and_homebrew_dependencies(self):
        def audit(arch=b"x86_64\n", minimum=b"13.0", library=b"/usr/lib/libSystem.B.dylib"):
            results = [
                subprocess.CompletedProcess([], 0, arch, b""),
                subprocess.CompletedProcess([], 0, b"    minos " + minimum + b"\n", b""),
                subprocess.CompletedProcess(
                    [], 0, b"fixture:\n\t" + library + b" (compatibility version 1.0.0)\n", b""
                ),
            ]
            with patch.object(package, "run", side_effect=results):
                return package.audit_binary(self.binary, self.target)

        self.assertEqual(audit(), {"needed_libraries": ["/usr/lib/libSystem.B.dylib"]})
        self.assertEqual(audit(minimum=b"13.0.0"), audit())
        for kwargs in ({"arch": b"arm64\n"}, {"minimum": b"15.0"}, {"library": b"/opt/homebrew/lib/libfoo.dylib"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                audit(**kwargs)

    def test_missing_executable_permission_is_rejected_before_launch(self):
        self.binary.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "executable permission"):
            package.verify_bundle(self.bundle, copy.deepcopy(self.info))

    def test_dmg_create_retries_busy_failure_and_removes_partial_image(self):
        image = self.work / "retry.dmg"
        calls = []

        def create(args, **kwargs):
            calls.append(args)
            self.assertFalse(image.exists())
            if len(calls) == 1:
                image.write_bytes(b"incomplete image")
                return subprocess.CompletedProcess(args, 1, b"", b"hdiutil: create failed - Resource busy\n")
            image.write_bytes(b"complete image")
            return subprocess.CompletedProcess(args, 0, b"", b"")

        with patch.object(package, "run", side_effect=create), patch.object(package.time, "sleep") as sleep:
            package.create_dmg(self.work, image, self.value)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], calls[1])
        self.assertEqual(image.read_bytes(), b"complete image")
        sleep.assert_called_once_with(2)

    def test_dmg_create_stops_after_three_busy_failures(self):
        busy = subprocess.CompletedProcess([], 1, b"", b"hdiutil: create failed - Resource busy\n")
        with patch.object(package, "run", return_value=busy) as run, patch.object(package.time, "sleep") as sleep:
            with self.assertRaises(subprocess.CalledProcessError):
                package.create_dmg(self.work, self.work / "busy.dmg", self.value)
        self.assertEqual(run.call_count, 3)
        self.assertEqual([call.args for call in sleep.call_args_list], [(2,), (4,)])

    def test_dmg_create_does_not_retry_other_errors(self):
        failed = subprocess.CompletedProcess([], 1, b"", b"hdiutil: create failed - Permission denied\n")
        with patch.object(package, "run", return_value=failed) as run, patch.object(package.time, "sleep") as sleep:
            with self.assertRaises(subprocess.CalledProcessError):
                package.create_dmg(self.work, self.work / "denied.dmg", self.value)
        run.assert_called_once()
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
