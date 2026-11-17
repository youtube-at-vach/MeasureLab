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
> Reviews involve both humans and AI. Rust development PRs target `main`; passing CI is part of review, and merging is a separate decision.
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
> Rust 開発の PR は `main` に向けます。CI の成功はレビューの確認事項であり、マージは別途判断します。

---

## Development

Read the [current direction and roadmap](guide/CURRENT_DIRECTION.md) before planning or changing Rust behavior. The [Rust guide](guide/rust/README.md) covers current behavior and links to relevant code. The final Python edition is preserved under `v0.9.1` and `archive/python-v0.9.1`. Its public manual retains the existing URLs. The Rust manual under `docs-rust/` is published separately under `/rust/`.

On macOS and Linux, follow the [setup guide](guide/rust/SETUP.md) and use `./scripts/setup_dev_env.sh --install-os-deps`, then `source .tools/env.sh`. For Windows, see the [MSVC setup](guide/rust/WINDOWS.md#msvcでのセットアップ). The default build uses `dev-fast` for everyday development.

## Validation

Use the [validation guide](guide/rust/VALIDATION.md) to select checks for the change. Before a Rust PR, run the shared checks for the headless core, normal desktop and QA configurations. The normal desktop tests check that QA entry points are excluded. For public manuals and site changes, validate the [combined Pages build](guide/rust/VALIDATION.md#サイトと静的チェック). Run Markdown lint for Markdown changes and actionlint for workflow changes.

The required CI statuses are `lint-and-test`, `docs-lint` and `actionlint`. CI selects optional native package jobs for affected packaging inputs. You can request test packages for a branch in the [CI workflow](.github/workflows/ci.yml). See [release preparation](guide/rust/RELEASE_PREPARATION.md#ciの運用ポイント) for packaging, signing and publication. Record hardware observations with their conditions and verification limits in the validation guide.

## Pull requests

Create a focused branch from `main`, normally named `codex/<purpose>`, and open the PR with `main` as its base. Explain what changed, why it changed, and which checks passed or could not be run. Submit PRs ready for review unless a draft is explicitly requested.

See [AGENTS.md](AGENTS.md) for working rules, [Rust validation](guide/rust/VALIDATION.md) for tests and hardware QA, and the [Security Policy](SECURITY.md) for vulnerability reporting.
