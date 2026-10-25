"""Stage native test packages without nesting portable archives in artifact ZIPs."""

import argparse
import json
import os
import shutil
import tempfile
import tomllib
from pathlib import Path

from linux_package import digest

ROOT = Path(__file__).resolve().parents[1]
PLATFORMS = {
    "windows-x64": ("-setup.exe", ".zip", "x86_64-pc-windows-msvc", "windows"),
    "linux-x86_64": (".AppImage", ".tar.gz", "x86_64-unknown-linux-gnu", "linux"),
    "macos-x86_64": (".dmg", None, "x86_64-apple-darwin", "macos"),
    "macos-arm64": (".dmg", None, "aarch64-apple-darwin", "macos"),
}


def prepare(assets, platform, source_sha):
    extension, archive_extension, target, os_name = PLATFORMS[platform]
    version = tomllib.loads((ROOT / "Cargo.toml").read_text())["package"]["version"]
    base = f"MeasureLab-v{version}-{platform}"
    package_name, info_name = base + extension, base + "-build-info.json"
    checksum_name = f"SHA256SUMS-{platform}.txt"
    expected = {package_name, info_name}
    if archive_extension:
        expected.add(base + archive_extension)
    if {path.name for path in assets.iterdir()} != expected | {checksum_name}:
        raise ValueError("Unexpected or incomplete release asset set")
    for name in expected | {checksum_name}:
        path = assets / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"Missing, empty or non-regular asset: {name}")
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
        info["version"] != version
        or info["source_sha"] != source_sha
        or info["source_dirty"] is not False
        or info["target"] != target
        or info["profile"] != "release"
        or info["features"] != ["desktop"]
        or (os_name == "windows" and info["crt_static"] is not True)
    ):
        raise ValueError("Unexpected build identity")
    # An empty, separate directory keeps build intermediates and alternate archives out.
    destination = Path(tempfile.mkdtemp(prefix="test-artifact-", dir=assets.parent))
    for name in (package_name, info_name):
        shutil.copyfile(assets / name, destination / name)
    shutil.copyfile(ROOT / "packaging" / os_name / "README.txt", destination / "README.txt")
    (destination / checksum_name).write_text(
        "".join(f"{digest(path)}  {path.name}\n" for path in sorted(destination.iterdir())),
        encoding="ascii",
    )
    return destination


def summary(platform, url):
    extension, _, _, os_name = PLATFORMS[platform]
    version = tomllib.loads((ROOT / "Cargo.toml").read_text())["package"]["version"]
    package_name = f"MeasureLab-v{version}-{platform}{extension}"
    instructions = {
        "windows": "Run the setup EXE to install for the current user, then start MeasureLab (Rust).",
        "macos": "Open the DMG, copy MeasureLab.app to Applications, eject the DMG, then open the copied app.",
        "linux": (
            f"Run `chmod +x {package_name}`, then `./{package_name}`. "
            "If FUSE is unavailable, add `--appimage-extract-and-run`."
        ),
    }
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as stream:
        stream.write(
            f"## MeasureLab test package: {platform}\n\n"
            f"[Download artifact]({url}) and extract the GitHub ZIP once.\n\n"
            f"Package: `{package_name}`. {instructions[os_name]}\n\n"
            "The ZIP root also contains README.txt, build-info JSON and SHA-256 checksums. "
            "No Rust or Python installation is required. See README.txt for OS requirements and permissions.\n\n"
            f"Source: `{os.environ['GITHUB_SHA']}` (PR merge result when run on a PR). "
            "Retention: 14 days. Development testing only; physical audio/GPU acceptance remains separate.\n"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    stage = commands.add_parser("prepare")
    stage.add_argument("assets", type=Path)
    stage.add_argument("--source-sha", required=True)
    report = commands.add_parser("summary")
    report.add_argument("--url", required=True)
    for subparser in (stage, report):
        subparser.add_argument("--platform", choices=PLATFORMS, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        destination = prepare(args.assets.resolve(), args.platform, args.source_sha)
        if output := os.environ.get("GITHUB_OUTPUT"):
            with Path(output).open("a", encoding="utf-8") as stream:
                stream.write(f"artifact_dir={destination}\n")
        print(f"Test artifact: {destination}")
    else:
        summary(args.platform, args.url)


if __name__ == "__main__":
    main()
