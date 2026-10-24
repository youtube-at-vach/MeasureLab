---
description: MeasureLab の Rust 開発と公開サイトの共通ルール
---

# Agent Guide

コマンドはリポジトリのルートで実行する。まず `git status --short --branch` と対象ファイルを確認し、ユーザーの変更や無関係な変更を上書きしない。

## 作業前に読む文書

* Rust の計画・設計・実装では [現在の方針](guide/CURRENT_DIRECTION.md) → [Rust PLAN](guide/rust/PLAN.md) の順に読み、目的・不変条件と対象マイルストーンを確認する。操作・コードの入口は [Rust README](guide/rust/README.md) の必要な節を読む。
* Rust版はmainへ統合済み。現在はGeneratorと同期2ch比較の統合評価、Rustプロトタイプの配布準備を進める。Audio I/O・測定演算・描画の実行分離、f64 基準、既知入力での精度・再現性を優先する。実装済みの 1〜16ch 基盤を維持し、まず 2ch の測定用途を完成させる。
* 旧 Python 版 GUI ガイド、`tech_docs/`、`.github/deepwiki/` は必要箇所だけ読む参考資料。旧版の構造・全機能移行・作業手順を現行の要件として適用しない。
* 文書は現在有効な状態を更新する。作業日誌や会話ログを追記せず、実装状態・未解決問題・次の完了条件を正本へ反映する。テスト条件・許容差・合否はコードを正本とし、実機確認だけを短く残す。未実施や過去の成功を現在の検証済みとしない。

## 現在の状態

* Rust アプリの表示名は MeasureLab、Cargo パッケージ・実行ファイル名は `measurelab`。次の版は `v0.10.0`、Rust 1.95 以降を使う。
* Rust版は `main` で開発し、開発用の PR は作業ブランチから `main` に向ける。
* Python アプリの最終版は `v0.9.1` タグと `archive/python-v0.9.1` ブランチを参照する。
* `.legacy-python/` はローカル専用の退避先で、Git 管理・通常の検索・検証の対象外。ここから旧実装やテスト環境を自動的に復元しない。
* `docs/` は既存URLを維持する Python 最終版の公開マニュアル、`docs-rust/` は `/rust/` に分ける Rust マニュアル。Rust 版で未実装の機能を実装済みと説明しない。
* PR のマージ、タグ作成、公開は依頼された段階だけ進める。

## 残している構成

| 対象 | 用途 |
| --- | --- |
| `src/`、`Cargo.toml`、`Cargo.lock`、`benches/` | Rust アプリ、依存関係、数値テストとベンチマーク |
| `scripts/`、`guide/rust/`、`LICENSE` | Rust 起動・macOS バンドル、操作・計画資料、The Unlicense |
| `download-site/`、`version.json`、`rust-release.json` | Python 最終版とRustの配布案内。Rust公開前はダウンロード無効 |
| `docs/`、`docs-rust/`、`mkdocs*.yml`、`requirements-docs.txt` | 新旧マニュアルの生成。`scripts/build_pages.py`でサイトを統合。PDF自動生成は退役 |
| `guide/`、`tech_docs/`、`.github/deepwiki/` | 製品・測定設計と旧版の参考資料 |
| `misc/extract_changelog.py`、`CHANGELOG.md` | リリースノートの抽出と開発履歴 |
| `.github/` | サイト・マニュアルの検証と公開、Issue、資金援助、レビュー、セキュリティ |

## 実装と検証

* 物理デバイスの安全上の必須制約として、測定・出力中のUSB抜去試験は実施しない。接続変更は入出力の停止・ストリーム解放後に行う。抜去試験を計画・受け入れ条件へ再導入せず、エラー処理は模擬通知で確認する。
* 検証は変更した挙動と回帰リスクに合わせる。コマンドは [Tool Usage Guide](.agents/workflows/tool_usage.md) を参照する。
* Rust の変更時と PR 前には `cargo fmt`、全ターゲット・全機能の Clippy とテスト、デスクトップのビルドを行う。GUIなしと通常（qaなし）のテストも実行する。`cargo test`のbenchは各条件1回の動作確認とし、反復性能計測は`cargo bench`で明示的に実行する。CIの必須チェックはLinuxの静的・数値・回帰検証と関連変更のMSRV確認に集約し、3 OSのreleaseビルドは任意チェックとする。`scripts/cargo.sh` は PATH 上の Cargo またはローカル `.tools/` の Rust 環境を使う。
* 残る Python は文書・リリースノート・CI用のツールのみ。Python 3.12 以降と `.venv/bin/` の実行ファイルを使い、旧アプリの依存関係・Pytest・Mypy・GUI 検証環境は導入しない。
* 作業終了時は `./.venv/bin/ruff check .` と `./.venv/bin/ruff format --check .` を実行する。環境がない場合はその結果を明記する。
* Markdown は見出し・コードブロック前後に空行を置き、行末空白を除く。リストマーカーと番号順を統一し、裸の URL は山括弧で囲む。変更後は Markdown lint を実行する。
* 自動修正・整形は必要なファイルだけに限定する。
* サイト変更時はサイトのテストとビルド、公開マニュアルやその生成設定の変更時は MkDocs ビルドを実行する。
* `version.json` はサイトが配布する版を表す。Rust 移行準備だけでは更新しない。
* 変更点、検証結果、未確認事項を報告する。失敗・未実施を成功扱いしない。

## Rust GUI の多言語対応

* 通常の機能開発では必要な英語キー・英語文言・呼出箇所だけを変更する。他言語の翻訳・一括同期・英語コピーによる穴埋めは行わず、AIにも全言語の翻訳を指示しない。英語キー削除後の旧訳整理も翻訳タスクへ渡す。
* 翻訳は対象言語・機能グループ・基準リビジョンを指定した独立タスク／PRにする。[開発・翻訳手順](guide/rust/I18N.md) に従い、抽出したキーと翻訳元ハッシュの範囲だけを変更する。`i18n/source-hashes.json`は翻訳PRだけで更新し、機能実装と他言語本文を混在させない。
* 翻訳の標準手順は`scripts/translate.py prepare --locale <言語> --group <グループ>`→`dist/i18n/answers.json`の`text`だけを編集→`apply`→`verify`とする。1タスクは1言語・1グループ。YAML・ハッシュをAIに手計算させず、定型指示は [開発・翻訳手順](guide/rust/I18N.md#翻訳モデルへの定型指示) を使う。`prepare`／`apply`は明示的な翻訳タスクだけで実行し、通常開発・CIから呼ばない。
* 回答・詳細タスクなどの中間生成物はGit管理外の`dist/i18n/`へ置き、コミットしない。`i18n/translation-task.json`には基準SHA・対象・内容ハッシュだけの検証マニフェストを保存する。翻訳担当が既存訳・旧英語・変数を確認する入口は`dist/i18n/translation-task.json`とする。
* `scripts/i18n.py check`／`diff`／`export-csv`は検査・レビュー出力専用で、翻訳生成やカタログの自動修正を行わない。他言語の欠落・古い訳は警告とし、英語変更の機能PRを止めない。PR前には`check --base <基準SHA>`で変更範囲も確認する。

## GitHub と Pull Request

* Issue 作成・Project 更新は依頼された場合だけ行う。[GitHub 共通手順](.agents/workflows/github_project.md) を参照する。
* 新しいブランチ名は指定がなければ `codex/<目的>` とする。
* PR を依頼された場合は、変更に必要な検証を行い、Ready for review で作成して `isDraft:false` を確認する。ユーザーが明示した場合だけ Draft にする。
* PR 本文は実際の差分と検証結果から作成する。テンプレートの案内文・HTMLコメント・空の節を完成した説明として残さず、投稿後に本文が意図どおり保存されたことを確認する。
* PR 作成時は base が `main` であることを確認する。依頼がない限りマージは行わない。
* 配布・サイト運用は [公開準備](guide/rust/RELEASE_PREPARATION.md)、テストコード・実機QAの入口は [Rust の検証](guide/rust/VALIDATION.md) を対象作業時に参照する。
