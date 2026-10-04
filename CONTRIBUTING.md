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
> Reviews involve both humans and AI. If CI tests pass successfully, changes will be merged into the `main` branch.
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
> CI などのテストが問題なく通過すれば、main ブランチにマージされます。

---

## Current development stage

This branch is prepared for the Rust rewrite. The Rust source and `Cargo.toml` have not been imported yet. The Python application's source, dependencies, tests, packaging, and development tasks are archived in `v0.9.1` and `archive/python-v0.9.1`.

For the old application environment, use the [Python v0.9.1 development guide](https://github.com/youtube-at-vach/MeasureLab/blob/v0.9.1/docs/development.en.md) from the archived edition.

The published manuals still describe the Python edition. Contributions to the download website, documentation, and measurement/design references remain possible during the rewrite.

## Website and documentation checks

Run commands from the repository root. Validate the download website with Node.js and npm:

```bash
npm --prefix download-site ci
npm --prefix download-site test
npm --prefix download-site run build
```

For manual generation, create a documentation-only environment with Python 3.12 or later:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements-docs.txt ruff
./.venv/bin/mkdocs build
./.venv/bin/ruff check .
./.venv/bin/ruff format --check .
```

After Markdown changes, run:

```bash
npx markdownlint-cli2 "**/*.md" "#node_modules"
```

The `.legacy-python/` directory is a local backup excluded from version control and validation. It is not required by the website or documentation build.

## Pull requests

Use a focused branch, normally named `codex/<purpose>`. Explain what changed, why it changed, and which checks passed or could not be run. Submit PRs ready for review unless a draft is explicitly requested.

See [AGENTS.md](AGENTS.md) for working rules, [Rust rewrite preparation](guide/RUST_REWRITE_PREPARATION.md) for the migration inventory, and the [Security Policy](SECURITY.md) for vulnerability reporting.
