# Contributing to MeasureLab

We welcome contributions of all kinds! This document provides guidelines for contributing to MeasureLab, including how to set up your development environment and the workflow for submitting changes.

## AI-Assisted Pull Requests / AI 支援による Pull Request について

> [!IMPORTANT]
> **This project actively welcomes Pull Requests created with the help of AI tools.**
> In fact, development of this project proceeds on the premise of AI-assisted PRs.
>
> Contributions using AI—whether for code, documentation, analysis, or design proposals—are all welcome. We don't mind who wrote it or what tool was used; we focus on whether the content is clear and adds value to the project.
>
> You are encouraged to clone the repository using tools like GitHub Copilot or Antigravity and submit the results of your work with AI as a PR. A brief explanation of "what was done" and "why it was done" in the PR description is sufficient.
>
> Reviews involve both humans and AI. Rust development PRs target `rewrite/rust`; passing CI is part of review, and merging is a separate decision.
>
> ---
>
> **本プロジェクトでは、AI ツールを活用して作成された Pull Request を積極的に歓迎しています。**
> 実際に、このプロジェクトは AI 支援による PR を前提として開発が進んでいます。
>
> コード、ドキュメント、解析、設計案など、AI を使った貢献はすべて歓迎です。
> 誰が書いたかや、どのツールを使ったかはあまり気にしていません。
> 内容が分かりやすく、プロジェクトにとってプラスになりそうかどうかを重視しています。
>
> GitHub Copilot や Antigravity などを使ってリポジトリをクローンし、
> AI と一緒に作業した結果をそのまま PR として送ってもらって構いません。
> PR には「何をしたか」「なぜそうしたか」が軽く分かる説明があれば十分です。
>
> レビューには人間だけでなく AI も関与します。
> Rust 開発の PR は `rewrite/rust` に向けます。CI の成功はレビューの確認事項であり、マージは別途判断します。

---

## Current development stage

This branch contains the Rust prototype of MeasureLab. The Python application's source, dependencies, tests, packaging, and development tasks are archived in `v0.9.1` and `archive/python-v0.9.1`.

For the old application environment, use the [Python v0.9.1 development guide](https://github.com/youtube-at-vach/MeasureLab/blob/v0.9.1/docs/development.en.md) from the archived edition.

The existing public manual describes Python v0.9.1; `docs-rust/` contains the separate Rust manual prepared for `/rust/`. The [Rust guide](guide/rust/README.md) documents the new application's current behavior. Contributions to the download website, documentation, and measurement/design references remain possible during the rewrite.

Before planning or changing Rust behavior, read the [current direction](guide/CURRENT_DIRECTION.md) and [Rust plan](guide/rust/PLAN.md). Build on the existing prototype and finish a small measurement use case with numerical validation before expanding the feature set. The former Rust/QML plan and Python GUI guide are reference material, not current implementation requirements.

Keep working documents focused on current decisions, constraints, unresolved problems, and completion criteria. Update the relevant state instead of appending a work diary; retain detailed measurements separately with their conditions and verification limits.

## Development environment setup

On macOS and Linux, use the [setup guide](guide/rust/SETUP.md) to prepare native prerequisites, then run:

```sh
./scripts/setup_dev_env.sh --install-os-deps --verify
source .tools/env.sh
```

The script installs local Rust, Node.js, documentation Python, and lint tools. Omit `--install-os-deps` when native libraries are already installed. `--verify` runs the checks below and the desktop release build; without it, setup builds the debug application and checks the documentation runtime.

## Rust checks

Use Rust 1.95 or later and your operating system's build tools. Run these commands from the repository root before opening a Rust PR:

```sh
./scripts/cargo.sh fmt --all -- --check
./scripts/cargo.sh clippy --locked --all-targets --all-features -- -D warnings
./scripts/cargo.sh test --locked --no-default-features
./scripts/cargo.sh test --locked
./scripts/cargo.sh test --locked --all-targets --all-features
./scripts/cargo.sh test --locked --doc --all-features
./scripts/cargo.sh build --release --locked
```

`cargo test` exercises each harness-free benchmark case once. Use `./scripts/cargo.sh bench --locked --no-default-features` for repeated performance measurements; real-time 120/600-second profiling is separate from PR checks. Numerical assertions and FFT size/precision coverage remain part of the normal tests.

The required statuses are `lint-and-test`, `docs-lint` and `actionlint`. Rust changes require Linux Clippy, normal/QA/headless tests and the applicable Rust 1.95 check. Three-OS release builds and macOS/Windows tests run separately and do not gate merging. The [CI policy](guide/rust/RELEASE_PREPARATION.md#ciの運用ポイント) describes triggers, caching, selected jobs and release review.

## Website and documentation checks

Run commands from the repository root. Validate the download website with Node.js and npm:

```bash
npm --prefix download-site ci
npm --prefix download-site test
npm --prefix download-site run build
```

For both manuals and the combined Pages output, use Python 3.12 or later and the Node.js environment above. CI helper tests use the standard library (`./.venv/bin/python -m unittest discover -s scripts -p 'test_ci_changes.py'`). PDF generation is retired; Pango/WeasyPrint are not required:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements-docs.txt ruff
./.venv/bin/python scripts/build_pages.py
./.venv/bin/ruff check .
./.venv/bin/ruff format --check .
```

After Markdown changes, run:

```bash
npx markdownlint-cli2 "**/*.md" "#node_modules"
```

The shared build runs both MkDocs configurations with `--strict`, builds the download site and verifies preserved Python routes plus Rust routes in `site/`. The Pages workflow runs on PRs, uploads a preview, and deploys only from `main`. Keep Python v0.9.1 URLs and archive labels when changing documentation; do not describe its features as Rust features.

Rust CI covers Linux/macOS/Windows on stable Rust, plus the declared Rust 1.95 minimum on Linux. Normal-build launch tests must run without `qa`; all-features testing alone cannot check that QA controls are excluded. Shared CI does not validate physical audio, GPU rendering, latency or long-duration performance. Record those conditions separately under `guide/rust/validation/`.

Run `actionlint` after workflow changes. Dependency updates must preserve the locked build and minimum Rust version. See [publication preparation](guide/rust/RELEASE_PREPARATION.md) for packaging, signing, main transition and remaining checks.

The `.legacy-python/` directory is a local backup excluded from version control and validation. It is not required by the website or documentation build.

## Pull requests

Create a focused branch from `rewrite/rust`, normally named `codex/<purpose>`, and open the PR with `rewrite/rust` as its base. Explain what changed, why it changed, and which checks passed or could not be run. Submit PRs ready for review unless a draft is explicitly requested. Moving the Rust edition into `main` is a separate step.

See [AGENTS.md](AGENTS.md) for working rules, [Rust rewrite preparation](guide/RUST_REWRITE_PREPARATION.md) for the migration inventory, and the [Security Policy](SECURITY.md) for vulnerability reporting.
