---
description: MeasureLab の Rust 移行準備中の共通ルール
---

# Agent Guide

コマンドはリポジトリのルートで実行する。まず `git status --short --branch` と対象ファイルを確認し、ユーザーの変更や無関係な変更を上書きしない。

## 現在の状態

* このブランチは Rust 実装の受け入れ準備中。Rust のソースと `Cargo.toml` はまだ取り込んでいない。
* Python アプリの最終版は `v0.9.1` タグと `archive/python-v0.9.1` ブランチを参照する。
* `.legacy-python/` はローカル専用の退避先で、Git 管理・通常の検索・検証の対象外。ここから旧実装やテスト環境を自動的に復元しない。
* `docs/` は Python 最終版の公開マニュアル。Rust 版で未実装の機能を実装済みと説明しない。
* Rust ソースの取り込み、main へのマージ、タグ作成、公開は依頼された段階だけ進める。

## 残している構成

| 対象 | 用途 |
| --- | --- |
| `download-site/`、`version.json` | Python 最終リリースのダウンロード案内 |
| `docs/`、`mkdocs.yml`、`requirements-docs.txt` | 公開マニュアル・PDF の生成 |
| `guide/`、`tech_docs/`、`.github/deepwiki/` | 製品・測定設計と旧版の参考資料 |
| `misc/extract_changelog.py`、`CHANGELOG.md` | リリースノートの抽出と開発履歴 |
| `.github/` | サイト・マニュアルの検証と公開、Issue、資金援助、レビュー、セキュリティ |

## 実装と検証

* 検証は変更した挙動と回帰リスクに合わせる。コマンドは [Tool Usage Guide](.agents/workflows/tool_usage.md) を参照する。
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
* 移行時の整理方針は [Rust rewrite preparation](guide/RUST_REWRITE_PREPARATION.md) を参照する。
