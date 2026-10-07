---
description: Rust アプリ・サイト・文書の起動と検証コマンド
---

# Tool Usage Guide

共通ルールと文書を読む順序は [AGENTS.md](../../AGENTS.md)、測定の完了条件は [Rust PLAN](../../guide/rust/PLAN.md) を参照する。以下のコマンドはリポジトリのルートで実行する。この文書には再実行する手順を置き、実測結果を追記しない。

## Rust アプリ

Rust 1.95 以降と OS のビルドツールを使う。`scripts/cargo.sh` は PATH 上の Cargo または `.tools/` にあるローカル環境を使う。

デバッグ時は次のスクリプトでビルドと起動をまとめて実行する。引数なしでは内部デモ信号を使い、`--audio`で実入力、`--release`で性能確認用のビルドを選ぶ。macOSではルートの`Debug-MeasureLab.command`をダブルクリックしても起動できる。

```bash
./scripts/debug.sh
./scripts/debug.sh --audio
./scripts/debug.sh --release
./scripts/debug.sh --ui-smoke
```

`--ui-smoke`は`qa`機能を自動的に有効にする。詳細は`./scripts/debug.sh --help`を参照する。

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

既存プロトタイプとの比較に使うUIフレーム時間・処理別CPU時間・欠落・RSSの連続計測（スクリプト名は`profile-stage2.sh`を継続）:

```bash
./scripts/cargo.sh build --release --locked --features qa
MEASURELAB_PROFILE_SECONDS=600 MEASURELAB_PROFILE_DEVICE="BlackHole 16ch" \
    MEASURELAB_PROFILE_CHANNEL=16 ./scripts/profile-stage2.sh blackhole16-600
MEASURELAB_PROFILE_SECONDS=120 ./scripts/profile-stage2.sh demo-120 --demo
```

ログと1秒ごとのRSSは`dist/stage2-qa/`へ保存する。仮想入力の停止・再開やデバイス切り替えは [Rust READMEの検証・計測](../../guide/rust/README.md#検証計測) を参照する。`MEASURELAB_PROFILE_UI_STALL=1`を追加すると、UIを1秒止めて取得・解析の継続と表示更新の省略を検証する。内部デモ・既存QAの成功だけで、未実装のSoftware Loopbackや物理系の精度を検証済みとしない。

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
