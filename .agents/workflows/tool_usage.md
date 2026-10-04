---
description: Rust アプリ・サイト・文書の起動と検証コマンド
---

# Tool Usage Guide

共通ルールは [AGENTS.md](../../AGENTS.md) を参照する。以下のコマンドはリポジトリのルートで実行する。

## Rust アプリ

Rust 1.95 以降と OS のビルドツールを使う。`scripts/cargo.sh` は PATH 上の Cargo または `.tools/` にあるローカル環境を使う。

```bash
./scripts/cargo.sh run --release --locked
./scripts/cargo.sh run --release --locked -- --demo
```

PR 前の検証:

```bash
./scripts/cargo.sh fmt --all -- --check
./scripts/cargo.sh clippy --locked --all-targets --all-features -- -D warnings
./scripts/cargo.sh test --locked --all-targets --all-features
./scripts/cargo.sh build --release --locked
```

GPU が利用できる環境では、読み戻しとテスト信号による画面確認を実行できる。

```bash
./scripts/cargo.sh run --release --locked -- --gpu-smoke
./scripts/cargo.sh run --locked --features qa -- --ui-smoke
```

macOS のローカルアプリバンドル:

```bash
./scripts/bundle-macos.sh
open dist/MeasureLab.app
```

Rust 実装の詳しい操作・計測・前提は [Rust README](../../guide/rust/README.md)、拡張計画は [Rust PLAN](../../guide/rust/PLAN.md) を参照する。

## ダウンロードサイト

Node.js と npm を使う。

```bash
npm --prefix download-site ci
npm --prefix download-site test
npm --prefix download-site run build
```

## マニュアル生成環境

Python 3.12 以降を使う。これは公開マニュアル用の環境で、旧 Python アプリの依存関係やテスト環境は含めない。

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements-docs.txt ruff
./.venv/bin/mkdocs build
```

PDF 自動生成のワークフローは停止中。公開マニュアルの Web ビルドは継続する。

## 検証

残る Python の文書・リリースノート用ツールを検証する。

```bash
./.venv/bin/ruff check .
./.venv/bin/ruff format --check .
```

Markdown 変更時は次を実行する。ローカル退避先は設定ファイルで除外している。

```bash
npx markdownlint-cli2 "**/*.md" "#node_modules"
```

GitHub Actions の変更時は、利用できる環境で `actionlint` を実行する。
