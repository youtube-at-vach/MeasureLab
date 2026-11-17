---
description: MeasureLab の Rust 開発と公開サイトの共通ルール
---

# Agent Guide

リポジトリのルートで `git status --short --branch` と対象ファイルを確認する。ユーザーの変更や無関係な変更を保護する。

## 開発の入口

Rustの計画・設計・実装は[現在の方針と計画](guide/CURRENT_DIRECTION.md)を読み、対象の参照先を開く。表示名はMeasureLab、Cargoパッケージと実行ファイルは `measurelab`。版とMSRVは [Cargo.toml](Cargo.toml) が正本。

| 対象 | 参照先 |
| --- | --- |
| 操作・測定値・コードの入口 | [Rust README](guide/rust/README.md) |
| 環境構築 | [セットアップ](guide/rust/SETUP.md) |
| 共通チェック・機能別QA・実機確認 | [Rustの検証](guide/rust/VALIDATION.md) |
| 配布候補・サイト公開 | [公開準備](guide/rust/RELEASE_PREPARATION.md) |
| 多言語対応 | [I18N](guide/rust/I18N.md) |

## 実装と検証

- 測定・出力中のUSB抜去試験は実施しない。入出力の停止・ストリーム解放後に接続を変更し、エラー処理は模擬通知で確認する。
- Rust変更の検証とRust PR前は[共通チェック](guide/rust/VALIDATION.md#rustの共通チェック)を実行する。日常起動は `dev-fast`。実機QAとローカルreleaseは変更に関係する条件を選び、同じソース・構成の検証済み成果物を再利用する。
- Pythonは3.12以降と `.venv/bin/` を使う。作業終了時はRuff、Markdown変更ではMarkdown lintを実行する。公開マニュアル・サイト・生成設定は[Pagesビルド](guide/rust/VALIDATION.md#サイトと静的チェック)で確認する。
- `docs/` はPython v0.9.1の既存URLを維持し、`docs-rust/` はRustの実装済み機能を記載する。配布版のメタデータは `version.json` と `rust-release.json`。`.legacy-python/` は検索と検証から除き、旧アプリの依存関係・テスト環境は復元しない。
- 文書は現行の条件と次の完了条件を更新する。詳細な証拠はGit管理外の `dist/`、テスト条件・許容差・合否はコード、履歴はGitとCHANGELOGに置く。検証結果と未確認の範囲を報告する。

## Rust GUIの多言語対応

- 通常の機能開発で変更するのは英語キー・英語文言・呼び出しだけ。他言語の同期・自動翻訳・英語による穴埋め・旧訳の削除は翻訳タスクに分ける。`i18n/source-hashes.json` は翻訳PRだけで更新する。
- 翻訳は1タスクにつき1言語・1グループ・基準リビジョンを指定し、[開発・翻訳手順](guide/rust/I18N.md)の定型指示を使う。`scripts/translate.py prepare --locale <言語> --group <グループ>` → `dist/i18n/answers.json` の `text` 編集 → `apply` → `verify` の順。`prepare` と `apply` は明示的な翻訳タスクでだけ使う。
- 回答と詳しいタスクはGit管理外の `dist/i18n/`、基準SHA・対象・内容ハッシュの検証マニフェストは `i18n/translation-task.json` に置く。`scripts/i18n.py check`／`diff`／`export-csv` は検査と出力専用。他言語の欠落・古い訳は警告として扱い、PR前には `check --base <基準SHA>` で範囲を確認する。

## GitHubとPull Request

- Issue・Project操作は依頼がある場合に[GitHub共通手順](.agents/workflows/github_project.md)を参照する。
- 作業ブランチの既定は `codex/<目的>`。依頼されたPRはbaseを `main` とし、検証後にReady for reviewで作成して `isDraft:false` を確認する。Draftは明示された場合だけ使う。
- PR本文は実際の差分・検証結果で構成し、テンプレートの案内や空の節を除き、投稿後に保存内容を確認する。
- PRのマージ、タグ作成、公開は依頼された段階だけ進める。
