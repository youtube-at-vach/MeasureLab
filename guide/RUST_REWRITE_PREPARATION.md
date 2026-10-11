# Rust rewrite preparation

The repository cleanup and Rust source import are complete. Current development uses egui / eframe / wgpu and the existing Rust measurement core. Read [Current direction](CURRENT_DIRECTION.md), the [Rust plan](rust/PLAN.md), and [publication preparation](rust/RELEASE_PREPARATION.md) for active work.

## Preserved editions and history

| Reference | Purpose |
| --- | --- |
| `v0.9.1`, `archive/python-v0.9.1` | Complete final Python source, tests, dependencies and packaging |
| `docs/`, `mkdocs.yml` | Final Python manual; existing public URLs remain available |
| `docs-rust/`, `mkdocs-rust.yml` | Separate Rust prototype manual, built under `/rust/` |
| `download-site/`, `version.json` | Published Python downloads; version remains `0.9.1` until a separate release decision |
| `tech_docs/`, `.github/deepwiki/` | Historical Python measurement/design references, not Rust feature promises |
| `guide/rust/validation/` | Conditional numerical and runtime evidence; not a current validation certificate |

The Rust prototype was imported from RAS commit `f29be2b08977700116f9119ea6ac08699b5ca1f4`. No further source import is needed. MeasureLab continues **The Unlicense**; the Cargo package and executable are `measurelab`.

`.legacy-python/` is an ignored local backup, not an archive required by new clones. Do not restore its old application or test environment automatically. Python is retained only for documentation and release tooling. Retired workflows and the full preparation inventory remain in [Git history](https://github.com/youtube-at-vach/MeasureLab/blob/cbe84122/guide/RUST_REWRITE_PREPARATION.md).

Development PRs continue to target `rewrite/rust`. Moving to `main`, tagging and publishing are separate actions. The active checklist is [publication preparation](rust/RELEASE_PREPARATION.md); completed cleanup is not a pending implementation milestone.
