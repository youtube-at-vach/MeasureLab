---
description: Rust アプリ・サイト・文書の起動と検証コマンド
---

# Tool Usage Guide

共通ルールと文書を読む順序は [AGENTS.md](../../AGENTS.md)、測定の完了条件は [Rust PLAN](../../guide/rust/PLAN.md) を参照する。以下のコマンドはリポジトリのルートで実行する。この文書には再実行する手順を置き、実測結果を追記しない。

## 初回セットアップ

macOS／LinuxでRust・サイト・文書用のローカル環境を構築する。OSの事前準備と手動導入は [開発環境のセットアップ](../../guide/rust/SETUP.md) を参照する。

```bash
./scripts/setup_dev_env.sh --install-os-deps --verify
source .tools/env.sh
```

OSライブラリを導入済みなら`--install-os-deps`を省略できる。引数なしでは依存関係の導入・`dev-fast`ビルド・文書用ライブラリの読み込みを確認し、`--verify`で以下の検証を一括実行する。

ネイティブWindowsは [MSVCでのセットアップ](../../guide/rust/WINDOWS.md#msvcでのセットアップ) を使う。以下のBashコマンドはPowerShellへそのまま貼り付けず、Rustは`cargo`、Python／Ruffは`.venv/Scripts/`、npm／npxは`npm.cmd`／`npx.cmd`に置き換える。各検証の終了コードを個別に確認する。

## Rust アプリ

Rust 1.95 以降と OS のビルドツールを使う。`scripts/cargo.sh` は PATH 上の Cargo または `.tools/` にあるローカル環境を使う。

デバッグ時は次のスクリプトで`dev-fast`のビルドと起動をまとめて実行する。引数なしでは実入力を選んだ停止状態で起動する。`--demo`を明示すると`qa`機能を有効にして内部信号を使い、`--full-debug`で完全なデバッガー情報、`--release`で性能確認用のビルドを選ぶ。macOSではルートの`Debug-MeasureLab.command`をダブルクリックしても実入力の画面を起動できる。

```bash
./scripts/debug.sh
./scripts/debug.sh --demo
./scripts/debug.sh --full-debug
./scripts/debug.sh --release
./scripts/debug.sh --ui-smoke
```

`--demo`と`--ui-smoke`は`qa`機能を自動的に有効にする。通常ビルドにデモの生成機能や入力選択肢は含めない。詳細は`./scripts/debug.sh --help`を参照する。

性能評価やrelease固有の挙動を確認する場合の起動:

```bash
./scripts/cargo.sh run --release --locked
./scripts/cargo.sh run --release --locked --features qa -- --demo
```

PR 前の検証:

```bash
./scripts/cargo.sh fmt --all -- --check
./scripts/cargo.sh clippy --locked --all-targets --all-features -- -D warnings
./scripts/cargo.sh test --locked --no-default-features
./scripts/cargo.sh test --locked
./scripts/cargo.sh test --locked --all-targets --all-features
./scripts/cargo.sh test --locked --doc --all-features
```

通常のPRではローカルのreleaseビルドを行わず、配布ビルドはCIに任せる。性能評価、release固有の不具合調査、配布候補の実機受け入れなど、最適化済み実行ファイルが検証に必要な場合だけ、理由を示して次を実行する。同じソース・機能構成で検証済みの成果物があれば再利用する。

```bash
./scripts/cargo.sh build --release --locked
```

全ターゲットのテストではbenchの各条件を1回だけ動かす。通常の数値・回帰テストは省略しない。反復した平均・p95・最大値の性能計測は、必要な変更や評価時に明示的に実行する。

```bash
./scripts/cargo.sh bench --locked --no-default-features
```

CIの必須チェック・任意ビルド・変更ファイルによる実行選択は [公開準備のCI方針](../../guide/rust/RELEASE_PREPARATION.md#ciの運用ポイント) を参照する。120／600秒の実時間評価はPRの自動テストから分離し、以下の専用コマンドで条件を記録する。

GPU が利用できる環境では、読み戻しとテスト信号による画面確認を実行できる。

```bash
./scripts/cargo.sh run --release --locked -- --gpu-smoke
./scripts/cargo.sh run --profile dev-fast --locked --features qa -- --ui-smoke
```

既存プロトタイプとの比較に使うUIフレーム時間・処理別CPU時間・欠落・RSSの連続計測（スクリプト名は`profile-stage2.sh`を継続）:

```bash
./scripts/cargo.sh build --release --locked --features qa
MEASURELAB_PROFILE_SECONDS=600 MEASURELAB_PROFILE_DEVICE="BlackHole 16ch" \
    MEASURELAB_PROFILE_CHANNEL=16 ./scripts/profile-stage2.sh blackhole16-600
MEASURELAB_PROFILE_SECONDS=120 ./scripts/profile-stage2.sh demo-120 --demo
```

ログと1秒ごとのRSSは`dist/stage2-qa/`へ保存する。仮想入力の停止・再開やデバイス切り替えは [機能別QA](../../guide/rust/VALIDATION.md) を参照する。`MEASURELAB_PROFILE_UI_STALL=1`を追加すると、UI停止中の取得・解析継続と表示更新の省略を検証する。停止時間は窓条件に依存する。内部デモ・既存QAの成功だけで、通常ビルドのSoftware Loopbackや物理系の精度を検証済みとしない。Software Loopbackの保存・再起動・再測定QAも同文書を参照する。

macOSのローカルアプリバンドルとDMG。ビルド用Python 3.12以降を使う（配布アプリの実行には不要）。DMGのCPUは実行中Macと一致させる。詳しい署名・マイク権限・配布前の確認は [macOS配布](../../guide/rust/RELEASE_PREPARATION.md#macos配布) を参照する。

```bash
./scripts/bundle-macos.sh
open dist/MeasureLab.app
./.venv/bin/python scripts/macos_package.py build
./.venv/bin/python scripts/macos_package.py verify dist/macos-<CPU>-<id>/release --runtime
./.venv/bin/python -m unittest discover -s scripts -p 'test_macos_package.py'
```

Rust 実装の詳しい操作・計測・前提は [Rust README](../../guide/rust/README.md)、拡張計画は [Rust PLAN](../../guide/rust/PLAN.md) を参照する。

### 開発ビルドと時間計測

| 用途 | 起動 | 出力先 |
| --- | --- | --- |
| 日常のGUI確認・操作修正 | `./scripts/debug.sh` | `target/dev-fast/measurelab` |
| デバッガーで型・変数も調べる | `./scripts/debug.sh --full-debug` | `target/debug/measurelab` |
| 最終性能・欠落・実時間評価 | `./scripts/debug.sh --release` | `target/release/measurelab` |

`dev-fast`はdevを継承し、アプリ最適化レベル1・依存ライブラリ2、インクリメンタルコンパイル、debug assertion・整数overflow検査を保つ。デバッグ情報を`line-tables-only`に絞り、LTOを`off`にする。設定の意味は [Cargo profiles](https://doc.rust-lang.org/cargo/reference/profiles.html) を参照する。`cargo test`・Clippyは従来の設定、配布・性能評価は従来のreleaseを使う。開発用ビルドの応答性をreleaseの受け入れ結果として扱わない。

ビルドだけを行い、[Cargo timings](https://doc.rust-lang.org/cargo/reference/timings.html) でクレート別の時間を調べる場合:

```bash
./scripts/cargo.sh build --locked --profile dev-fast --timings
./scripts/cargo.sh build --locked --profile dev --timings
./scripts/cargo.sh build --locked --release --timings
```

レポートは`target/cargo-timings/`の時刻付きHTMLに残る。各プロファイルを一度ビルドした後、変更なしの再実行と、同じ小さなGUI変更を加えた差分ビルドを区別する。差分は複数回測って中央値を比較し、OS／CPU・Rust版・機能構成・キャッシュ条件を記録する。比較中は別のビルドや実時間QAを動かさない。

依存関係からの初回ビルドは、既存キャッシュを消さず、未使用の出力先を指定して測る。次の出力先を再利用した場合は初回計測ではない。初回の依存関係ダウンロード時間も区別する。

```bash
./scripts/cargo.sh build --locked --release --timings --target-dir target/timing-release-cold
./scripts/cargo.sh build --locked --profile dev-fast --timings --target-dir target/timing-dev-fast-cold
```

プロファイルの初回と通常／`qa`の切り替えには追加のコンパイルが必要。QA画面の反復確認は`--demo`／`--ui-smoke`で同じ機能構成を使い、性能評価はreleaseのQA版を一度ビルドして実行ファイルを直列に再利用する。

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
./.venv/bin/python scripts/build_pages.py
```

Node.jsとサイト依存関係も必要。共通スクリプトで旧Pythonマニュアル、新Rustマニュアル、downloadを`site/`へ統合し、MkDocs strictと公開ルート保持を検証する。PDF自動生成は退役し、WebビルドにWeasyPrint・Pangoは不要。配置と公開条件は [公開準備](../../guide/rust/RELEASE_PREPARATION.md) を参照する。

## 検証

残る Python の文書・リリースノート用ツールを検証する。

```bash
./.venv/bin/ruff check .
./.venv/bin/ruff format --check .
./.venv/bin/python -m unittest discover -s scripts -p 'test_ci_changes.py'
./.venv/bin/python -m unittest discover -s scripts -p 'test_i18n.py'
./.venv/bin/python scripts/i18n.py check
```

Rust GUIの英語カタログ変更・翻訳PRは [開発・翻訳手順](../../guide/rust/I18N.md) に従い、`check --base <基準SHA>`で変更範囲も検査する。検査用依存だけを導入する場合は`./.venv/bin/python -m pip install -r requirements-i18n.txt`を使う。検査・差分・CSV出力はカタログを変更しない。

翻訳タスクでは専用の`scripts/translate.py prepare --locale <言語> --group <グループ>`で対象を準備し、`dist/i18n/answers.json`の`text`だけを編集して`apply`→`verify`を行う。ハッシュは専用ツールが計算する。通常開発・CIから`prepare`／`apply`を呼ばない。

Markdown 変更時は次を実行する。ローカル退避先は設定ファイルで除外している。

```bash
npx markdownlint-cli2 "**/*.md" "#node_modules"
```

GitHub Actions の変更時は、利用できる環境で `actionlint` を実行する。
