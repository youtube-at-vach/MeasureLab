---
description: MeasureLab の Rust 開発と公開サイトの共通ルール
---

# Agent Guide

コマンドはリポジトリのルートで実行する。まず `git status --short --branch` と対象ファイルを確認し、ユーザーの変更や無関係な変更を上書きしない。

## 作業前に読む文書

* Rust の計画・設計・実装では [現在の方針](guide/CURRENT_DIRECTION.md) → [Rust PLAN](guide/rust/PLAN.md) の順に読み、目的・不変条件と対象マイルストーンを確認する。操作・コードの入口は [Rust README](guide/rust/README.md) の必要な節を読む。
* 現在は Scope／Spectrum を測定器として仕上げる段階。Audio I/O・測定演算・描画の実行分離、f64 基準、既知入力での精度・再現性を優先する。実装済みの 1〜16ch 基盤を維持し、まず 2ch の測定用途を完成させる。
* 旧 Rust/QML 計画、旧 Python 版 GUI ガイド、`tech_docs/`、`.github/deepwiki/` は必要箇所だけ読む参考資料。旧版の構造・全機能移行・作業手順を現行の要件として適用しない。
* 文書は現在有効な状態を更新する。作業日誌や会話ログを追記せず、実装状態・未解決問題・次の完了条件を正本へ反映する。実測記録は条件付きで分離し、未実施や過去の成功を現在の検証済みとしない。

## 現在の状態

* Rust アプリの表示名は MeasureLab、Cargo パッケージ・実行ファイル名は `measurelab`。Rust 1.95 以降を使う。
* 開発用の PR は作業ブランチから `rewrite/rust` に向ける。main への切り替えは別途依頼された段階で行う。
* Python アプリの最終版は `v0.9.1` タグと `archive/python-v0.9.1` ブランチを参照する。
* `.legacy-python/` はローカル専用の退避先で、Git 管理・通常の検索・検証の対象外。ここから旧実装やテスト環境を自動的に復元しない。
* `docs/` は Python 最終版の公開マニュアル。Rust 版で未実装の機能を実装済みと説明しない。
* Rust ソースの取り込み、main へのマージ、タグ作成、公開は依頼された段階だけ進める。

## 残している構成

| 対象 | 用途 |
| --- | --- |
| `src/`、`Cargo.toml`、`Cargo.lock`、`benches/` | Rust アプリ、依存関係、数値テストとベンチマーク |
| `scripts/`、`guide/rust/`、`LICENSE` | Rust 起動・macOS バンドル、操作・計画資料、The Unlicense |
| `download-site/`、`version.json` | Python 最終リリースのダウンロード案内 |
| `docs/`、`mkdocs.yml`、`requirements-docs.txt` | 公開マニュアルの生成。PDF 自動生成のワークフローは停止中 |
| `guide/`、`tech_docs/`、`.github/deepwiki/` | 製品・測定設計と旧版の参考資料 |
| `misc/extract_changelog.py`、`CHANGELOG.md` | リリースノートの抽出と開発履歴 |
| `.github/` | サイト・マニュアルの検証と公開、Issue、資金援助、レビュー、セキュリティ |

## 実装と検証

* 検証は変更した挙動と回帰リスクに合わせる。コマンドは [Tool Usage Guide](.agents/workflows/tool_usage.md) を参照する。
* Rust の変更時と PR 前には `cargo fmt`、全ターゲット・全機能の Clippy とテスト、デスクトップのビルドを行う。`scripts/cargo.sh` は PATH 上の Cargo またはローカル `.tools/` の Rust 環境を使う。
* 残る Python は文書・リリースノート用のツールのみ。Python 3.12 以降と `.venv/bin/` の実行ファイルを使い、旧アプリの依存関係・Pytest・Mypy・GUI 検証環境は導入しない。
* 作業終了時は `./.venv/bin/ruff check .` と `./.venv/bin/ruff format --check .` を実行する。環境がない場合はその結果を明記する。
* Markdown は見出し・コードブロック前後に空行を置き、行末空白を除く。リストマーカーと番号順を統一し、裸の URL は山括弧で囲む。変更後は Markdown lint を実行する。
* 自動修正・整形は必要なファイルだけに限定する。
* サイト変更時はサイトのテストとビルド、公開マニュアルやその生成設定の変更時は MkDocs ビルドを実行する。
* `version.json` はサイトが配布する版を表す。Rust 移行準備だけでは更新しない。
* 変更点、検証結果、未確認事項を報告する。失敗・未実施を成功扱いしない。

## GitHub と Pull Request

* Issue 作成・Project 更新は依頼された場合だけ行う。[GitHub 共通手順](.agents/workflows/github_project.md) を参照する。
* 新しいブランチ名は指定がなければ `codex/<目的>` とする。
* PR を依頼された場合は、変更に必要な検証を行い、Ready for review で作成して `isDraft:false` を確認する。ユーザーが明示した場合だけ Draft にする。
* PR 作成時は base が `rewrite/rust` であることを確認する。依頼がない限りマージは行わない。
* 移行時の整理方針は [Rust rewrite preparation](guide/RUST_REWRITE_PREPARATION.md) を参照する。
