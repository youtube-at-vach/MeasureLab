---
description: MeasureLab の Rust 開発と公開サイトの共通ルール
---

# Agent Guide

リポジトリのルートで `git status --short --branch` と対象ファイルを確認する。ユーザーの変更や無関係な変更を保護する。

## 開発の入口

Rustの計画・設計・実装では[現在の方針](guide/CURRENT_DIRECTION.md) → [Rust PLAN](guide/rust/PLAN.md)の順に読む。対象に応じて次の文書を開く。

| 知りたいこと | 入口 |
| --- | --- |
| 現行の操作、測定値の意味、コードの位置 | [Rust README](guide/rust/README.md) |
| 環境の構築、起動・ビルド・共通チェック | [セットアップ](guide/rust/SETUP.md)、[ツールの使い方](.agents/workflows/tool_usage.md) |
| 機能別テスト、実機QAの方法と確認範囲 | [Rustの検証](guide/rust/VALIDATION.md) |
| 配布候補、サイト、公開の残作業 | [公開準備](guide/rust/RELEASE_PREPARATION.md) |
| 英語のキーと差分翻訳 | [開発・翻訳手順](guide/rust/I18N.md) |

Rust版は `main` で開発する。表示名はMeasureLab、Cargoパッケージと実行ファイルは `measurelab`。次の版は `v0.10.0`、MSRVはRust 1.95。Audio I/O・測定演算・描画の実行を分離し、f64基準と既知入力での精度・再現性を優先する。1〜16ch基盤を維持し、まず同期2chとGeneratorの測定用途を仕上げる。

Python最終版は `v0.9.1`／`archive/python-v0.9.1`。旧版の資料は[現在の方針の参照先](guide/CURRENT_DIRECTION.md#文書の役割)から必要時に開く。`.legacy-python/` はローカル専用の退避先で、通常の検索・検証から除外し、依存関係や旧実装を自動復元しない。

## 実装と検証

- 測定・出力中のUSB抜去試験は実施しない。接続変更は入出力停止・ストリーム解放後に行う。抜去試験を受け入れ条件へ戻さず、エラー処理は模擬通知で確認する。
- Rustの変更時とPR前はfmt・全ターゲット／全機能のClippyとテスト・GUIなしと通常（qaなし）のテストを[共通手順](.agents/workflows/tool_usage.md#rust-アプリ)で実行する。`cargo test` のベンチは各条件1回の確認とし、反復計測は `cargo bench` で行う。CIの必須チェックはLinuxの静的・数値・回帰検証と関連変更のMSRV確認に集約し、3 OSのreleaseビルドは任意チェックとする。
- 日常の起動確認は `dev-fast`。手元のreleaseビルドは性能評価・release固有の調査・配布候補の実機受け入れで必要な場合に理由を示して行い、同じソースと構成の検証済み成果物は再利用する。通常のPR、文書・CI・インストーラー画面の変更は配布ビルドをCIに任せる。
- 文書・リリースノート・CI用のPythonは3.12以降と `.venv/bin/` を使う。作業終了時は `./.venv/bin/ruff check .` と `./.venv/bin/ruff format --check .` を実行し、環境がなければ報告する。旧アプリの依存関係・Pytest・Mypy・GUI検証環境の導入は行わない。
- Markdown変更後はlintを実行する。見出し・コードブロックの前後に空行を入れ、行末空白を除き、リストの記号と順序を統一する。裸のURLは山括弧で囲む。整形は必要なファイルに限定する。
- `docs/` は既存URLを維持するPython最終版マニュアル、`docs-rust/` は `/rust/` 向けの現行マニュアルで、実装済みの機能だけを記載する。文書・生成設定の変更はMkDocsビルド、`download-site/` の変更はサイトのテストとビルドで確認する。`version.json` はサイトの配布版を更新するときに揃える。Rustの配布状況は `rust-release.json` に持つ。
- 文書には現在の実装・次の完了条件と、コードで代替できない実機確認の要約を置く。テスト条件・許容差・合否はコード、過去の経緯はGitとCHANGELOG、詳細な検証ログ・画像はGit管理外の `dist/` を参照する。変更内容・実施結果・未確認の範囲を報告する。

## Rust GUIの多言語対応

- 通常の機能開発で変更するのは英語キー・英語文言・呼び出しだけ。他言語の同期・自動翻訳・英語による穴埋め・旧訳の削除は翻訳タスクに分ける。`i18n/source-hashes.json` は翻訳PRだけで更新する。
- 翻訳は1タスクにつき1言語・1グループ・基準リビジョンを指定し、[開発・翻訳手順](guide/rust/I18N.md)の定型指示を使う。`scripts/translate.py prepare --locale <言語> --group <グループ>` → `dist/i18n/answers.json` の `text` 編集 → `apply` → `verify` の順。`prepare` と `apply` は明示的な翻訳タスクでだけ使う。
- 回答と詳しいタスクはGit管理外の `dist/i18n/`、基準SHA・対象・内容ハッシュの検証マニフェストは `i18n/translation-task.json` に置く。`scripts/i18n.py check`／`diff`／`export-csv` は検査と出力専用。他言語の欠落・古い訳は警告として扱い、PR前には `check --base <基準SHA>` で範囲を確認する。

## GitHubとPull Request

- Issue・Project操作は依頼がある場合に[GitHub共通手順](.agents/workflows/github_project.md)を参照する。
- 作業ブランチの既定は `codex/<目的>`。依頼されたPRはbaseを `main` とし、検証後にReady for reviewで作成して `isDraft:false` を確認する。Draftは明示された場合だけ使う。
- PR本文は実際の差分・検証結果で構成し、テンプレートの案内や空の節を除き、投稿後に保存内容を確認する。
- PRのマージ、タグ作成、公開は依頼された段階だけ進める。
