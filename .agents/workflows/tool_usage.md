---
description: Rustアプリ・サイト・文書の起動と共通検証
---

# Tool Usage Guide

以下はリポジトリのルートで実行する。機能別のQAは [Rustの検証](../../guide/rust/VALIDATION.md)、配布物の検証は [公開準備](../../guide/rust/RELEASE_PREPARATION.md) を参照する。

## 初回セットアップ

macOS／Linuxは [セットアップ](../../guide/rust/SETUP.md)、ネイティブWindowsは [MSVC手順](../../guide/rust/WINDOWS.md#msvcでのセットアップ) に従う。`scripts/cargo.sh` はPATH上または `.tools/` のRustを使う。

## Rust アプリ

普段は `./scripts/debug.sh` を使う。`--demo` または `--ui-smoke` を指定すると `qa` が有効になる。通常ビルドの起動と回帰は `qa` なしでも確認する。

```bash
./scripts/cargo.sh fmt --all -- --check
./scripts/cargo.sh clippy --locked --all-targets --all-features -- -D warnings
./scripts/cargo.sh test --locked --no-default-features
./scripts/cargo.sh test --locked
./scripts/cargo.sh test --locked --all-targets --all-features
./scripts/cargo.sh test --locked --doc --all-features
```

CIで実行する条件の正本は [ci.yml](../../.github/workflows/ci.yml)。合否・許容差はテストコードを参照する。各ベンチ条件の `cargo test` は1回の動作確認。反復計測は `cargo bench --locked --no-default-features` を明示して実行する。

### 開発ビルドと時間計測

| 用途 | 起動 | 出力 |
| --- | --- | --- |
| 日常のGUI確認 | `./scripts/debug.sh` | `target/dev-fast/measurelab` |
| 型・変数のデバッグ | `./scripts/debug.sh --full-debug` | `target/debug/measurelab` |
| 性能・release固有問題の確認 | `./scripts/debug.sh --release` | `target/release/measurelab` |

時間計測は `./scripts/cargo.sh build --locked --profile dev-fast --timings` を使う。レポートは `target/cargo-timings/`。初回・変更なし・小さな変更後の計測を区別し、初回の比較には未使用の `--target-dir` を指定する。OS・CPU・Rust版・機能構成を揃える。

## ダウンロードサイト

```bash
npm --prefix download-site ci
npm --prefix download-site test
npm --prefix download-site run build
```

## マニュアル生成環境

Python 3.12以降の `.venv` に `requirements-docs.txt` とRuffを導入する。サイトの依存関係も導入した状態で次を実行すると、MkDocsのstrictビルド、新旧マニュアルとサイトの統合、公開URLの確認を行う。

```bash
./.venv/bin/python scripts/build_pages.py
```

## 検証

変更範囲に応じて共通チェックと対象ツールのテストを実行する。

```bash
./.venv/bin/ruff check .
./.venv/bin/ruff format --check .
npx markdownlint-cli2 "**/*.md" "#node_modules"
```

Pythonの回帰テストは `scripts/test_*.py` から選び、`./.venv/bin/python -m unittest discover -s scripts -p 'test_ci_changes.py'` の形式で実行する。GitHub Actionsの変更時は `actionlint` を使う。i18nのPR前チェックは [開発・翻訳手順](../../guide/rust/I18N.md) に従う。
