"""Build and verify the normal Rust Linux AppImage and identical AppDir archive."""

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = "x86_64-unknown-linux-gnu"
CHECKSUMS = "SHA256SUMS-linux-x86_64.txt"
# Versioned upstream releases, including the runtime: no mutable continuous assets.
TOOLS = {
    "appimagetool": (
        "https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage",
        "ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0",
    ),
    "runtime": (
        "https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-x86_64",
        "2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d",
    ),
}
HOST_LIBRARIES = {
    "libasound.so.2",
    "libgcc_s.so.1",
    "libm.so.6",
    "libc.so.6",
    "libdl.so.2",
    "libpthread.so.0",
    "librt.so.1",
    "ld-linux-x86-64.so.2",
}


def run(args, *, cwd=ROOT, env=None, check=True, timeout=120):
    result = subprocess.run(  # noqa: S603 - argument lists only, never a shell
        [str(arg) for arg in args],
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and result.returncode:
        print(result.stdout + result.stderr, file=sys.stderr)
        result.check_returncode()
    return result


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def version_tuple(value):
    return tuple(int(part) for part in value.split("."))


def audit_binary(binary, max_glibc):
    header = run(["readelf", "-h", binary]).stdout
    if "ELF64" not in header or "Advanced Micro Devices X86-64" not in header:
        raise ValueError("The distribution requires a Linux x86_64 ELF executable")
    versions = re.findall(r"\bGLIBC_(\d+(?:\.\d+)+)\b", run(["readelf", "--version-info", binary]).stdout)
    if not versions:
        raise ValueError("No glibc requirements found")
    required = max(versions, key=version_tuple)
    if version_tuple(required) > version_tuple(max_glibc):
        raise ValueError(f"Binary requires glibc {required}; distribution limit is {max_glibc}")
    libraries = sorted(re.findall(r"\(NEEDED\).*\[(.*?)\]", run(["readelf", "-d", binary]).stdout))
    if not libraries or set(libraries) - HOST_LIBRARIES:
        raise ValueError(f"Unexpected runtime dependencies; review packaging: {libraries}")
    if "not found" in run(["ldd", binary]).stdout:
        raise ValueError("A runtime dependency is missing on the build host")
    return {"glibc_required": required, "needed_libraries": libraries}


def inventory(directory):
    files = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Unexpected payload symlink: {path}")
        if path.is_file() and path.name != "build-info.json":
            files[path.relative_to(directory).as_posix()] = digest(path)
    return files


def create_appdir(directory, binary, info):
    (directory / "usr/bin").mkdir(parents=True)
    shutil.copyfile(binary, directory / "usr/bin/measurelab")
    (directory / "usr/bin/measurelab").chmod(0o755)
    for name in ("AppRun", "README.txt", "dev.measurelab.app.desktop"):
        shutil.copyfile(ROOT / "packaging/linux" / name, directory / name)
    (directory / "AppRun").chmod(0o755)
    shutil.copyfile(ROOT / "LICENSE", directory / "LICENSE")
    shutil.copyfile(ROOT / "app_icon.png", directory / "dev.measurelab.app.png")
    shutil.copyfile(ROOT / "app_icon.png", directory / ".DirIcon")
    info["payload_sha256"] = inventory(directory)
    (directory / "build-info.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")


def download_tool(name, directory):
    url, expected = TOOLS[name]
    path = directory / name
    run(["curl", "--fail", "--location", "--retry", "3", url, "--output", path])
    if digest(path) != expected:
        raise ValueError(f"SHA-256 mismatch for {name}")
    path.chmod(0o755)
    return path


def package_appdir(directory, assets, info, tools_dir):
    base = f"MeasureLab-v{info['version']}-linux-x86_64"
    tool = download_tool("appimagetool", tools_dir)
    runtime = download_tool("runtime", tools_dir)
    env = dict(os.environ, ARCH="x86_64", APPIMAGE_EXTRACT_AND_RUN="1")
    env.pop("VERSION", None)
    result = run([tool, "--no-appstream", "--runtime-file", runtime, directory, assets / f"{base}.AppImage"], env=env)
    print(result.stdout + result.stderr)
    if inventory(directory) != info["payload_sha256"]:
        raise ValueError("AppImage tooling changed the staged payload")
    with tarfile.open(assets / f"{base}.tar.gz", "w:gz") as archive:
        archive.add(directory, arcname="MeasureLab")
    shutil.copyfile(directory / "build-info.json", assets / f"{base}-build-info.json")
    (assets / CHECKSUMS).write_text(
        "".join(f"{digest(path)}  {path.name}\n" for path in sorted(assets.iterdir())),
        encoding="ascii",
    )


def build(args):
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise ValueError("Build this package on Linux x86_64")
    version = tomllib.loads((ROOT / "Cargo.toml").read_text())["package"]["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", version):
        raise ValueError("Unsupported Cargo version")
    if os.environ.get("GITHUB_REF_TYPE") == "tag" and os.environ["GITHUB_REF_NAME"] != f"v{version}":
        raise ValueError("Tag does not match Cargo.toml")
    env = dict(os.environ, CARGO_INCREMENTAL="0", CARGO_ENCODED_RUSTFLAGS="")
    if not shutil.which("cargo"):
        env.update(CARGO_HOME=str(ROOT / ".tools/cargo"), RUSTUP_HOME=str(ROOT / ".tools/rustup"))
        env["PATH"] = str(ROOT / ".tools/cargo/bin") + os.pathsep + env["PATH"]
    # Separate target directory and explicit features prevent packaging an earlier QA build.
    target_dir = ROOT / "target/distribution-linux"
    result = run(
        [
            ROOT / "scripts/cargo.sh",
            "build",
            "--release",
            "--locked",
            "--no-default-features",
            "--features",
            "desktop",
            "--target",
            TARGET,
            "--target-dir",
            target_dir,
        ],
        env=env,
        timeout=1800,
    )
    print(result.stdout + result.stderr)
    binary = target_dir / TARGET / "release/measurelab"
    info = {
        "version": version,
        "source_sha": run(["git", "rev-parse", "HEAD"]).stdout.strip(),
        "source_dirty": bool(
            run(
                [
                    "git",
                    "status",
                    "--porcelain",
                    "--",
                    "Cargo.toml",
                    "Cargo.lock",
                    "src",
                    "scripts",
                    "packaging",
                    ".github/workflows",
                    "app_icon.png",
                    "LICENSE",
                ]
            ).stdout
        ),
        "target": TARGET,
        "profile": "release",
        "features": ["desktop"],
        "rustc": run(["rustc", "--version"], env=env).stdout.strip(),
        "build_os": platform.freedesktop_os_release(),
        "executable_sha256": digest(binary),
        **audit_binary(binary, args.max_glibc),
    }
    (ROOT / "dist").mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="linux-", dir=ROOT / "dist"))
    directory, assets, tools_dir = work / "MeasureLab", work / "release", work / "tools"
    assets.mkdir()
    tools_dir.mkdir()
    create_appdir(directory, binary, info)
    run(["desktop-file-validate", directory / "dev.measurelab.app.desktop"])
    package_appdir(directory, assets, info, tools_dir)
    print(f"Linux distribution: {assets}")
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(f"release_dir={assets}\n")


def verify_checksums(assets, expected):
    if {path.name for path in assets.iterdir()} != expected | {CHECKSUMS}:
        raise ValueError("Unexpected or incomplete release asset set")
    seen = set()
    for line in (assets / CHECKSUMS).read_text(encoding="ascii").splitlines():
        checksum, name = line.split("  ", 1)
        if name not in expected or name in seen or digest(assets / name) != checksum:
            raise ValueError(f"Invalid checksum entry: {name}")
        seen.add(name)
    if seen != expected:
        raise ValueError("Missing checksum entries")


def verify_tar(archive_path, info):
    expected = {f"MeasureLab/{name}" for name in info["payload_sha256"]} | {"MeasureLab/build-info.json"}
    with tarfile.open(archive_path) as archive:
        seen = set()
        for member in archive.getmembers():
            if member.isdir() and member.name in {"MeasureLab", "MeasureLab/usr", "MeasureLab/usr/bin"}:
                continue
            if not member.isfile() or member.name not in expected or member.name in seen:
                raise ValueError(f"Unexpected archive member: {member.name}")
            seen.add(member.name)
            with archive.extractfile(member) as stream:
                if member.name == "MeasureLab/build-info.json":
                    if json.load(stream) != info:
                        raise ValueError("Archive build identity mismatch")
                elif hashlib.file_digest(stream, "sha256").hexdigest() != info["payload_sha256"][member.name[11:]]:
                    raise ValueError(f"Archive payload hash mismatch: {member.name}")
            if member.name in {"MeasureLab/AppRun", "MeasureLab/usr/bin/measurelab"} and not member.mode & 0o111:
                raise ValueError(f"Missing executable permission: {member.name}")
        if seen != expected:
            raise ValueError("Incomplete archive payload")


def check_normal_options(command, env):
    result = run([*command, "--help"], env=env)
    if "MeasureLab" not in result.stdout or "QA options:" in result.stdout:
        raise ValueError("Not a normal MeasureLab desktop executable")
    for option in ("--demo", "--ui-smoke", "--lockin-smoke", "--physical-lockin-smoke", "--multichannel-smoke"):
        result = run([*command, option], env=env, check=False)
        if result.returncode == 0 or "requires --features qa" not in result.stderr:
            raise ValueError(f"QA-only option was not rejected: {option}")


def verify(args):
    assets = args.assets.resolve()
    version = tomllib.loads((ROOT / "Cargo.toml").read_text())["package"]["version"]
    base = f"MeasureLab-v{version}-linux-x86_64"
    verify_checksums(assets, {f"{base}.AppImage", f"{base}.tar.gz", f"{base}-build-info.json"})
    info = json.loads((assets / f"{base}-build-info.json").read_text(encoding="utf-8"))
    source_sha = args.source_sha or run(["git", "rev-parse", "HEAD"]).stdout.strip()
    if (
        info["version"] != version
        or info["source_sha"] != source_sha
        or info["target"] != TARGET
        or info["features"] != ["desktop"]
        or info["profile"] != "release"
        or (args.require_clean and info["source_dirty"])
        or version_tuple(info["glibc_required"]) > version_tuple(args.max_glibc)
        or info["executable_sha256"] != info["payload_sha256"]["usr/bin/measurelab"]
    ):
        raise ValueError("Unexpected build identity or glibc requirement")
    archive_path = assets / f"{base}.tar.gz"
    verify_tar(archive_path, info)
    if args.runtime:
        image = assets / f"{base}.AppImage"
        image.chmod(0o755)  # upload/download-artifact does not preserve Unix executable bits.
        with tempfile.TemporaryDirectory(prefix="MeasureLab 検証 ") as temp:
            work = Path(temp)
            env = dict(os.environ, XDG_CONFIG_HOME=str(work / "config"), XDG_CACHE_HOME=str(work / "cache"))
            run([image, "--appimage-extract"], cwd=work)
            extracted = work / "squashfs-root"
            if inventory(extracted) != info["payload_sha256"]:
                raise ValueError("AppImage payload differs from the archive")
            if json.loads((extracted / "build-info.json").read_text(encoding="utf-8")) != info:
                raise ValueError("AppImage build identity mismatch")
            # The tar was inspected before extraction; forbid links and traversal there.
            with tarfile.open(archive_path) as archive:
                archive.extractall(work, filter="data")
            for command in ([image, "--appimage-extract-and-run"], [work / "MeasureLab/AppRun"]):
                check_normal_options(command, env)
            if audit_binary(extracted / "usr/bin/measurelab", args.max_glibc) != {
                key: info[key] for key in ("glibc_required", "needed_libraries")
            }:
                raise ValueError("Packaged ELF requirements differ from build information")
            if args.gpu:
                result = run([extracted / "AppRun", "--gpu-smoke"], env=env)
                print(result.stdout + result.stderr)
    print(f"Verified Linux assets, source {source_sha}, glibc {info['glibc_required']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    builder = commands.add_parser("build")
    builder.add_argument("--max-glibc", default="2.35")
    checker = commands.add_parser("verify")
    checker.add_argument("assets", type=Path)
    checker.add_argument("--source-sha")
    checker.add_argument("--max-glibc", default="2.35")
    checker.add_argument("--require-clean", action="store_true")
    checker.add_argument("--runtime", action="store_true")
    checker.add_argument("--gpu", action="store_true")
    args = parser.parse_args()
    if args.command == "build":
        build(args)
    else:
        if args.gpu and not args.runtime:
            parser.error("--gpu requires --runtime")
        verify(args)


if __name__ == "__main__":
    main()
