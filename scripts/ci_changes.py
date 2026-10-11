"""Classify NUL-separated Git paths without skipping required status checks."""

import argparse
import sys


def classify(paths: list[str]) -> dict[str, bool]:
    result = dict.fromkeys(("rust", "msrv", "web"), False)
    for path in paths:
        if (
            path in {"Cargo.toml", "Cargo.lock", "rust-toolchain", "rust-toolchain.toml"}
            or path.startswith((".cargo/", ".github/workflows/"))
            or path in {"scripts/ci_changes.py", "scripts/test_ci_changes.py"}
        ):
            result.update(rust=True, msrv=True, web=True)
        elif path.startswith(("src/", "tests/", "benches/")):
            # A new API in source can raise the MSRV without a manifest edit.
            result.update(rust=True, msrv=True)
        elif (
            path.startswith(("docs/", "docs-rust/", "download-site/", "overrides/"))
            or path.startswith("mkdocs")
            or path in {"requirements-docs.txt", "version.json", "scripts/build_pages.py"}
        ):
            result["web"] = True
        elif path.startswith("scripts/") and not path.endswith(".md"):
            result["rust"] = True
        elif (
            path.endswith(".md")
            or path.startswith((".agents/", ".github/ISSUE_TEMPLATE/", "misc/"))
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
            result.update(rust=True, msrv=True, web=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--web", action="store_true")
    args = parser.parse_args()
    if args.all:
        result = dict.fromkeys(("rust", "msrv", "web"), True)
    else:
        paths = sys.stdin.buffer.read().decode("utf-8", errors="surrogateescape")
        result = classify([path for path in paths.split("\0") if path])
    if args.web:
        result["web"] = True
    for name, changed in result.items():
        print(f"{name}={str(changed).lower()}")


if __name__ == "__main__":
    main()
