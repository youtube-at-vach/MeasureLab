"""Classify NUL-separated Git paths without skipping required status checks."""

import argparse
import sys


PACKAGE_INPUTS = {
    "windows_package": (
        "packaging/windows/",
        ".github/workflows/build_windows.yml",
        "scripts/build_windows_installer.ps1",
        "scripts/install_inno_setup.ps1",
        "scripts/test_windows_installer.ps1",
        "scripts/windows_shell_link.ps1",
    ),
    "macos_package": (
        "packaging/macos/",
        ".github/workflows/build_macos.yml",
        "scripts/bundle-macos.sh",
        "scripts/macos_package.py",
        "scripts/test_macos_package.py",
    ),
    "linux_package": (
        "packaging/linux/",
        ".github/workflows/build_linux.yml",
        "scripts/linux_package.py",
        "scripts/test_linux_package.py",
    ),
}
CHECKS = ("rust", "msrv", "web", "i18n", "dev_actions", "qa", *PACKAGE_INPUTS)
QA_SCRIPTS = {
    "scripts/profile-stage2.sh",
    "scripts/qa_gui_redesign.py",
    "scripts/qa_spectrogram.py",
    "scripts/test_qa_gui_redesign.py",
    "scripts/test_qa_spectrogram.py",
}
DEV_ACTION_INPUTS = {
    ".codex/environments/environment.toml",
    "Debug-MeasureLab.command",
    "scripts/cargo.ps1",
    "scripts/cargo.sh",
    "scripts/debug.ps1",
    "scripts/debug.sh",
    "scripts/pwsh.cmd",
    "scripts/setup_dev_env.sh",
    "scripts/test_dev_actions.py",
}


def classify(paths: list[str]) -> dict[str, bool]:
    result = dict.fromkeys(CHECKS, False)
    for path in paths:
        package_checks = [
            check
            for check, (directory, *files) in PACKAGE_INPUTS.items()
            if path.startswith(directory) or path in files
        ]
        if package_checks:
            result.update(dict.fromkeys(package_checks, True))
            continue

        if path.startswith(".cargo/") or path in {
            "Cargo.toml",
            "Cargo.lock",
            "rust-toolchain",
            "rust-toolchain.toml",
            "build.rs",
        }:
            result.update(rust=True, msrv=True)
            result.update(dict.fromkeys(PACKAGE_INPUTS, True))
        elif path in {"app_icon.png", "scripts/ci_artifacts.py", "scripts/test_ci_artifacts.py"}:
            result.update(dict.fromkeys(PACKAGE_INPUTS, True))
        elif path in DEV_ACTION_INPUTS:
            result["dev_actions"] = True
        elif path in QA_SCRIPTS:
            result["qa"] = True
        elif path.startswith(("locales/", "i18n/")):
            # Embedded catalogs/metadata need compilation and the dedicated scope checks.
            result.update(rust=True, i18n=True)
        elif path == "requirements-i18n.txt":
            result.update(i18n=True, web=True, qa=True)
        elif path == "scripts/i18n.py":
            result.update(i18n=True, qa=True)
        elif path in {"scripts/test_i18n.py", "scripts/translate.py"}:
            result["i18n"] = True
        elif path.startswith(("src/", "tests/", "benches/")):
            # A new API in source can raise the MSRV without a manifest edit.
            result.update(rust=True, msrv=True, i18n=True)
        elif (
            path.startswith(("docs/", "docs-rust/", "download-site/", "overrides/"))
            or path.startswith("mkdocs")
            or path in {"requirements-docs.txt", "version.json", "rust-release.json", "scripts/build_pages.py"}
        ):
            result["web"] = True
        elif (
            path.endswith(".md")
            or path.startswith((".agents/", ".github/ISSUE_TEMPLATE/", ".github/assets/readme/", "misc/"))
            or path
            in {
                ".gitignore",
                ".gitattributes",
                ".markdownlint-cli2.jsonc",
                ".github/FUNDING.yml",
                ".github/dependabot.yml",
                "ruff.toml",
            }
        ):
            # Markdown, Ruff and workflow lint still run on every change.
            continue
        else:
            # New or unrecognized build inputs must not silently bypass checks.
            return dict.fromkeys(CHECKS, True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--web", action="store_true")
    args = parser.parse_args()
    if args.all:
        result = dict.fromkeys(CHECKS, True)
    else:
        paths = sys.stdin.buffer.read().decode("utf-8", errors="surrogateescape")
        result = classify([path for path in paths.split("\0") if path])
    if args.web:
        result["web"] = True
    for name, changed in result.items():
        print(f"{name}={str(changed).lower()}")


if __name__ == "__main__":
    main()
