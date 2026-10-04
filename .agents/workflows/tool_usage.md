---
description: Rust 移行準備中のサイト・文書ツールと検証コマンド
---

# Tool Usage Guide

共通ルールは [AGENTS.md](../../AGENTS.md) を参照する。以下のコマンドはリポジトリのルートで実行する。

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

PDF 生成は必要な場合だけ実行する。WeasyPrint のシステム依存関係は `.github/workflows/pdf_draft.yml` を参照する。

```bash
ENABLE_PDF_EXPORT=1 ./.venv/bin/mkdocs build
```

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

## Rust 実装の取り込み後

Rust 実装と `Cargo.toml` はまだ存在しない。取り込み後に、実際の構成に合わせて起動・ビルド・テストのコマンドを記録する。
