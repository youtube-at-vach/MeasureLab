# Rust rewrite preparation

`rewrite/rust` starts from the final Python release, `v0.9.1`. The `Begin Rust rewrite` commit clears the application paths for the new Rust implementation while keeping the project's website, published manuals, history, and reference material.

## Python archive

The complete Python edition remains available through the `v0.9.1` tag and the `archive/python-v0.9.1` branch.

In the preparation worktree, the original files were first moved into `.legacy-python/`. Files needed by the website and project documentation were then returned to their original paths. Original copies of replaced configuration and root documentation remain in that backup.

`.legacy-python/` is ignored by Git and is a local convenience only. New clones use the tag or archive branch to retrieve the Python edition. Its `.migration-manifest.json` records the original commit and SHA-256 hashes so that the relocated files can be checked for completeness.

## Retained files

| Paths | Purpose |
| --- | --- |
| `download-site/`, `version.json` | Download website and the published Python version |
| `docs/`, `mkdocs.yml`, `requirements-docs.txt` | Existing online manuals, assets, math rendering, and PDF generation |
| `guide/`, `tech_docs/`, `.github/deepwiki/` | Product direction, measurement principles, migration plans, and Python reference documentation |
| `CHANGELOG.md`, `misc/extract_changelog.py` | Historical release notes and their extraction tool |
| `app_icon.png` | Project icon |
| `README.md`, `README.ja.md`, `CONTRIBUTING.md`, `SECURITY.md` | Project information, license statement, contributor credits, and security policy |
| Selected `.github/` files | Issue templates, funding, PR review, website/manual workflows, workflow linting, and security checks |
| `AGENTS.md`, `.agents/workflows/`, lint configuration | Current working rules, GitHub procedures, and validation of retained tools and documentation |

The manuals and technical references describe the Python edition. Their presence does not imply that those features are already available in Rust. `version.json` stays at `0.9.1` until the download website actually offers a new release.

## Retired files

The Python application's `src/`, `main_gui.py`, tests, benchmarks, experiments, runtime dependency files, packaging, PyInstaller settings, ASIO helpers, and application build/release workflows have been removed from the tracked tree. Python-specific agent skills and editor/task settings are also retired.

Python remains a tool for the retained manuals and release-note extraction. The old application dependencies, Pytest, Mypy, Qt UI checks, and translation checks are no longer part of this branch's setup.

## Next stage

The `Begin Rust rewrite` commit did not import Rust source. The subsequent import brings in `/Users/vach/RAS` at commit `f29be2b08977700116f9119ea6ac08699b5ca1f4`, placing `src/`, Cargo files, benchmarks, scripts, and Rust CI in the cleared application paths. The original README, plan, and reference image are retained in `guide/rust/`. At the project owner's request, the Rust edition continues MeasureLab's **The Unlicense**, recorded in `Cargo.toml` and `LICENSE`. The application code, Cargo package, and `ras` executable keep their original names and behavior.

Rust development uses topic branches and pull requests targeting `rewrite/rust`. The download website, Python manual, and `version.json` stay at their published state. Replacing `main` and publishing releases are separate steps.
