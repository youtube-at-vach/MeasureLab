"""Build and verify normal Rust macOS app bundles and architecture-specific DMGs."""

import argparse
import hashlib
import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {"x86_64-apple-darwin": "x86_64", "aarch64-apple-darwin": "arm64"}
MINIMUM_MACOS = "13.0"
IDENTIFIER = "dev.measurelab.app"
ENTITLEMENTS = {"com.apple.security.device.audio-input": True}
INFO_PATH = "Contents/Resources/build-info.json"


def run(args, *, env=None, check=True, timeout=120):
    result = subprocess.run(  # noqa: S603 - argument lists only, never a shell
        [str(arg) for arg in args], cwd=ROOT, env=env, capture_output=True, timeout=timeout, check=False
    )
    if check and result.returncode:
        print((result.stdout + result.stderr).decode(errors="replace"), file=sys.stderr)
        result.check_returncode()
    return result


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def version():
    value = tomllib.loads((ROOT / "Cargo.toml").read_text())["package"]["version"]
    if not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?", value):
        raise ValueError("Unsupported Cargo version")
    return value


def bundle_plist(value):
    # Apple bundle versions are numeric even when the Cargo release is a prerelease.
    numeric = value.split("-", 1)[0]
    return {
        "CFBundleName": "MeasureLab",
        "CFBundleDisplayName": "MeasureLab",
        "CFBundleIdentifier": IDENTIFIER,
        "CFBundleExecutable": "measurelab",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": numeric,
        "CFBundleVersion": numeric,
        "CFBundleIconFile": "MeasureLab.icns",
        "LSMinimumSystemVersion": MINIMUM_MACOS,
        "NSHighResolutionCapable": True,
        "NSMicrophoneUsageDescription": "オーディオ入力を測定し、波形と周波数スペクトルを表示するためにマイクへのアクセスを使用します。",
    }


def inventory(bundle):
    files = {}
    for path in sorted(bundle.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Unexpected bundle symlink: {path}")
        relative = path.relative_to(bundle).as_posix()
        if path.is_file():
            files[relative] = digest(path)
    return files


def audit_binary(binary, target):
    if run(["lipo", "-archs", binary]).stdout.decode().strip() != TARGETS[target]:
        raise ValueError("Unexpected Mach-O architecture")
    load_commands = run(["xcrun", "vtool", "-show-build", binary]).stdout.decode()
    minimum = re.search(r"^\s*(?:minos|version)\s+(\d+\.\d+(?:\.\d+)?)\s*$", load_commands, re.MULTILINE)
    if not minimum or minimum[1] not in {MINIMUM_MACOS, f"{MINIMUM_MACOS}.0"}:
        raise ValueError("Mach-O deployment target differs from the package baseline")
    libraries = [
        line.strip().split(" (", 1)[0] for line in run(["otool", "-L", binary]).stdout.decode().splitlines()[1:]
    ]
    if not libraries or any(not name.startswith(("/System/Library/", "/usr/lib/")) for name in libraries):
        raise ValueError(f"Unexpected non-system runtime dependencies: {libraries}")
    return {"needed_libraries": libraries}


def check_normal_options(binary):
    help_text = run([binary, "--help"]).stdout.decode()
    if "MeasureLab" not in help_text or "QA options:" in help_text:
        raise ValueError("Not a normal MeasureLab desktop executable")
    for option in ("--demo", "--ui-smoke", "--lockin-smoke", "--physical-lockin-smoke", "--multichannel-smoke"):
        result = run([binary, option], check=False)
        if result.returncode == 0 or b"requires --features qa" not in result.stderr:
            raise ValueError(f"QA-only option was not rejected: {option}")


def verify_bundle(bundle, info):
    with (bundle / "Contents/Info.plist").open("rb") as stream:
        if plistlib.load(stream) != bundle_plist(info["version"]):
            raise ValueError("Bundle metadata or microphone usage description mismatch")
    # Final signed bytes are hashed only in the external manifest to avoid a
    # cycle between the embedded identity, CodeResources and Mach-O signature.
    identity = {key: value for key, value in info.items() if key not in {"payload_sha256", "executable_sha256"}}
    if json.loads((bundle / INFO_PATH).read_text()) != identity:
        raise ValueError("Bundle build identity mismatch")
    if inventory(bundle) != info["payload_sha256"]:
        raise ValueError("Bundle payload hash mismatch")
    binary = bundle / "Contents/MacOS/measurelab"
    if not binary.stat().st_mode & 0o111:
        raise ValueError("Missing executable permission")
    run(["codesign", "--verify", "--deep", "--strict", bundle])
    signature = run(["codesign", "--display", "--verbose=4", bundle]).stderr.decode()
    if "Signature=adhoc" not in signature or "runtime" not in signature:
        raise ValueError("Expected ad-hoc signature with Hardened Runtime")
    signed = run(["codesign", "--display", "--entitlements", ":-", bundle]).stdout
    if plistlib.loads(signed) != ENTITLEMENTS:
        raise ValueError("Signed audio-input entitlement mismatch")
    if audit_binary(binary, info["target"])["needed_libraries"] != info["needed_libraries"]:
        raise ValueError("Packaged runtime dependencies differ from build information")
    check_normal_options(binary)


def create_icon(destination, work):
    iconset = work / "MeasureLab.iconset"
    iconset.mkdir()
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
            run(["sips", "-z", size * scale, size * scale, ROOT / "app_icon.png", "--out", iconset / name])
    run(["iconutil", "-c", "icns", iconset, "-o", destination])


def build_bundle(bundle, target):
    if platform.system() != "Darwin" or platform.machine() != TARGETS[target]:
        raise ValueError("Build macOS packages on a Mac matching the package architecture")
    value = version()
    if os.environ.get("GITHUB_REF_TYPE") == "tag" and os.environ.get("GITHUB_REF_NAME") != f"v{value}":
        raise ValueError("Tag does not match Cargo.toml")
    dirty = bool(run(["git", "status", "--porcelain", "--untracked-files=normal"]).stdout)
    if os.environ.get("GITHUB_ACTIONS") == "true" and dirty:
        raise ValueError("CI distribution builds require a clean checkout")
    env = dict(os.environ, CARGO_INCREMENTAL="0", CARGO_ENCODED_RUSTFLAGS="", MACOSX_DEPLOYMENT_TARGET=MINIMUM_MACOS)
    env.pop("RUSTFLAGS", None)
    if not shutil.which("cargo"):
        env.update(CARGO_HOME=str(ROOT / ".tools/cargo"), RUSTUP_HOME=str(ROOT / ".tools/rustup"))
        env["PATH"] = str(ROOT / ".tools/cargo/bin") + os.pathsep + env["PATH"]
    target_dir = ROOT / "target/distribution-macos"
    print(f"Building normal desktop for {target} (macOS {MINIMUM_MACOS})", flush=True)
    result = run(
        [
            ROOT / "scripts/cargo.sh",
            "build",
            "--release",
            "--locked",
            "--no-default-features",
            "--features",
            "desktop",
            "--bin",
            "measurelab",
            "--target",
            target,
            "--target-dir",
            target_dir,
        ],
        env=env,
        timeout=2400,
    )
    print((result.stdout + result.stderr).decode(), flush=True)
    binary = target_dir / target / "release/measurelab"
    info = {
        "version": value,
        "source_sha": run(["git", "rev-parse", "HEAD"]).stdout.decode().strip(),
        "source_dirty": dirty,
        "target": target,
        "profile": "release",
        "features": ["desktop"],
        "rustc": run(["rustc", "--version"], env=env).stdout.decode().strip(),
        "build_macos": platform.mac_ver()[0],
        "minimum_macos": MINIMUM_MACOS,
        "signature": "adhoc",
        "notarized": False,
        **audit_binary(binary, target),
    }
    # Stage afresh: old resources or signatures must never enter the next bundle.
    bundle.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="macos-bundle-", dir=bundle.parent) as temp:
        work = Path(temp)
        staged = work / "MeasureLab.app"
        resources = staged / "Contents/Resources"
        resources.mkdir(parents=True)
        (staged / "Contents/MacOS").mkdir()
        shutil.copyfile(binary, staged / "Contents/MacOS/measurelab")
        (staged / "Contents/MacOS/measurelab").chmod(0o755)
        with (staged / "Contents/Info.plist").open("wb") as stream:
            plistlib.dump(bundle_plist(value), stream)
        create_icon(resources / "MeasureLab.icns", work)
        shutil.copyfile(ROOT / "LICENSE", resources / "LICENSE")
        shutil.copyfile(ROOT / "packaging/macos/README.txt", resources / "README.txt")
        (staged / INFO_PATH).write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
        run(
            [
                "codesign",
                "--force",
                "--options",
                "runtime",
                "--entitlements",
                ROOT / "packaging/macos/entitlements.plist",
                "--sign",
                "-",
                staged,
            ]
        )
        info["executable_sha256"] = digest(staged / "Contents/MacOS/measurelab")
        info["payload_sha256"] = inventory(staged)
        verify_bundle(staged, info)
        if bundle.is_symlink() or (bundle.exists() and not bundle.is_dir()):
            raise ValueError(f"Refusing to replace a non-directory bundle: {bundle}")
        if bundle.exists():
            shutil.rmtree(bundle)
        shutil.move(staged, bundle)
    print(f"Built {bundle}", flush=True)
    return info


def asset_names(value, target):
    base = f"MeasureLab-v{value}-macos-{TARGETS[target]}"
    return f"{base}.dmg", f"{base}-build-info.json", f"SHA256SUMS-macos-{TARGETS[target]}.txt"


def verify_assets(assets, target, source_sha, require_clean):
    value = version()
    image_name, info_name, checksum_name = asset_names(value, target)
    expected = {image_name, info_name}
    if {path.name for path in assets.iterdir()} != expected | {checksum_name}:
        raise ValueError("Unexpected or incomplete release asset set")
    seen = set()
    for line in (assets / checksum_name).read_text(encoding="ascii").splitlines():
        checksum, name = line.split("  ", 1)
        if name not in expected or name in seen or digest(assets / name) != checksum:
            raise ValueError(f"Invalid checksum entry: {name}")
        seen.add(name)
    if seen != expected:
        raise ValueError("Missing checksum entries")
    info = json.loads((assets / info_name).read_text(encoding="utf-8"))
    if (
        info["version"] != value
        or info["source_sha"] != source_sha
        or info["target"] != target
        or info["profile"] != "release"
        or info["features"] != ["desktop"]
        or info["minimum_macos"] != MINIMUM_MACOS
        or info["signature"] != "adhoc"
        or info["notarized"] is not False
        or (require_clean and info["source_dirty"])
        or info["executable_sha256"] != info["payload_sha256"]["Contents/MacOS/measurelab"]
    ):
        raise ValueError("Unexpected build identity")
    return assets / image_name, info


@contextmanager
def mounted_image(image, mountpoint):
    run(["hdiutil", "attach", "-readonly", "-nobrowse", "-noautoopen", "-mountpoint", mountpoint, image])
    try:
        yield mountpoint
    finally:
        run(["hdiutil", "detach", mountpoint])


def verify(args):
    assets = args.assets.resolve()
    source_sha = args.source_sha or run(["git", "rev-parse", "HEAD"]).stdout.decode().strip()
    image, info = verify_assets(assets, args.target, source_sha, args.require_clean)
    if args.runtime:
        if platform.system() != "Darwin" or platform.machine() != TARGETS[args.target]:
            raise ValueError("Runtime verification requires a macOS host matching the package architecture")
        run(["hdiutil", "verify", image])
        with tempfile.TemporaryDirectory(prefix="MeasureLab 検証 ") as temp:
            work = Path(temp)
            with mounted_image(image, work / "volume") as volume:
                expected = {"MeasureLab.app", "Applications", "README.txt", "LICENSE"}
                # HFS+ can add filesystem metadata, but no extra distribution payload.
                if {p.name for p in volume.iterdir()} - {
                    ".HFS+ Private Directory Data\r",
                    ".fseventsd",
                    ".Trashes",
                } != expected:
                    raise ValueError("Unexpected DMG contents")
                link = volume / "Applications"
                if not link.is_symlink() or os.readlink(link) != "/Applications":
                    raise ValueError("Missing Applications drop link")
                for name, source in (
                    ("README.txt", ROOT / "packaging/macos/README.txt"),
                    ("LICENSE", ROOT / "LICENSE"),
                ):
                    if digest(volume / name) != digest(source):
                        raise ValueError(f"DMG {name} mismatch")
                verify_bundle(volume / "MeasureLab.app", info)
                # Simulate Finder's copy without writing to the user's Applications.
                copied = work / "日本語 Applications" / "MeasureLab.app"
                run(["ditto", volume / "MeasureLab.app", copied])
            verify_bundle(copied, info)
            if args.gpu:
                result = run([copied / "Contents/MacOS/measurelab", "--gpu-smoke"])
                print((result.stdout + result.stderr).decode())
    print(f"Verified macOS {TARGETS[args.target]} assets, source {source_sha}", flush=True)


def create_dmg(stage, image, value):
    for attempt in range(3):
        result = run(
            [
                "hdiutil",
                "create",
                "-volname",
                f"MeasureLab {value}",
                "-srcfolder",
                stage,
                "-fs",
                "HFS+",
                "-format",
                "UDZO",
                "-nospotlight",
                image,
            ],
            check=False,
        )
        if result.returncode == 0:
            return
        output = result.stdout + result.stderr
        print(output.decode(errors="replace"), file=sys.stderr)
        if b"Resource busy" not in output or attempt == 2:
            result.check_returncode()
        # DiskImages can transiently report EBUSY on hosted macOS runners.
        # A failed create may leave an incomplete image that blocks the retry.
        image.unlink(missing_ok=True)
        delay = 2 * (attempt + 1)
        print(f"Retrying busy hdiutil create in {delay}s ({attempt + 2}/3)", file=sys.stderr, flush=True)
        time.sleep(delay)


def build(args):
    (ROOT / "dist").mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f"macos-{TARGETS[args.target]}-", dir=ROOT / "dist"))
    stage, assets = work / "stage", work / "release"
    stage.mkdir()
    assets.mkdir()
    info = build_bundle(stage / "MeasureLab.app", args.target)
    (stage / "Applications").symlink_to("/Applications")
    shutil.copyfile(ROOT / "packaging/macos/README.txt", stage / "README.txt")
    shutil.copyfile(ROOT / "LICENSE", stage / "LICENSE")
    image_name, info_name, checksum_name = asset_names(info["version"], args.target)
    create_dmg(stage, assets / image_name, info["version"])
    (assets / info_name).write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    (assets / checksum_name).write_text(
        "".join(f"{digest(assets / name)}  {name}\n" for name in (image_name, info_name)), encoding="ascii"
    )
    verify(
        argparse.Namespace(
            assets=assets,
            target=args.target,
            source_sha=info["source_sha"],
            require_clean=False,
            runtime=True,
            gpu=False,
        )
    )
    print(f"macOS distribution: {assets}", flush=True)
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(f"release_dir={assets}\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("bundle", "build", "verify"):
        subparser = commands.add_parser(command)
        subparser.add_argument(
            "--target",
            choices=TARGETS,
            default="aarch64-apple-darwin" if platform.machine() == "arm64" else "x86_64-apple-darwin",
        )
        if command == "bundle":
            subparser.add_argument("--output", type=Path, default=ROOT / "dist/MeasureLab.app")
        elif command == "verify":
            subparser.add_argument("assets", type=Path)
            subparser.add_argument("--source-sha")
            subparser.add_argument("--require-clean", action="store_true")
            subparser.add_argument("--runtime", action="store_true")
            subparser.add_argument("--gpu", action="store_true")
    args = parser.parse_args()
    if args.command == "bundle":
        if args.output.name != "MeasureLab.app":
            parser.error("--output must end in MeasureLab.app")
        build_bundle(args.output.absolute(), args.target)
    elif args.command == "build":
        build(args)
    else:
        if args.gpu and not args.runtime:
            parser.error("--gpu requires --runtime")
        verify(args)


if __name__ == "__main__":
    main()
