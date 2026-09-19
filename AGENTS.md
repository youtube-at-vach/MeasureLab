---
description: MeasureLab の共通ルールと作業別スキルの入口
---

# Agent Guide

コマンドはリポジトリのルートで実行する。まず `git status --short --branch` と対象コードを確認し、ユーザーの変更や無関係な変更を上書きしない。

## 作業の選び方

依頼に対応するスキルだけを読む。通常のコード修正に Issue 作成・Project 更新を強制しない。複数段階を依頼された場合は続けて進め、依頼にない次の段階へは自動的に進めない。

| 依頼 | スキル | 完了時の成果 |
| --- | --- | --- |
| 提案から次の候補を選ぶ | [agent-proposal-backlog-issue](.agents/skills/agent-proposal-backlog-issue/SKILL.md) | 候補、登録依頼があれば Backlog Issue |
| 小さな修正を Issue にする | [agent-simple-ready-issue](.agents/skills/agent-simple-ready-issue/SKILL.md) | Ready Issue |
| Ready Issue の実装計画を作る | [agent-ready-task-planner](.agents/skills/agent-ready-task-planner/SKILL.md) | 計画コメントと Working、または理由と Blocked |
| Working Issue を実装する | [agent-working-task-implement](.agents/skills/agent-working-task-implement/SKILL.md) | 検証済み PR と Review |
| 翻訳を調査・修正する | [multilingual-translator](.agents/skills/multilingual-translator/SKILL.md) | 検査結果、必要な翻訳修正 |
| リリースを準備する | [release-manager](.agents/skills/release-manager/SKILL.md) | バージョン・文書の更新と準備 PR |
| PR 前の検証を行う | [ci-prechecker](.agents/skills/ci-prechecker/SKILL.md) | 検証結果と必要な修正 |

## 必要な資料

全資料の一括読み込みを避け、対象に関係する節を読む。既読内容は変更や不足がなければ再取得しない。

| 判断・操作 | 参照先 |
| --- | --- |
| 環境、起動、検証コマンド | [Tool Usage Guide](.agents/workflows/tool_usage.md) |
| Issue・Project の確認と更新 | [GitHub 共通手順](.agents/workflows/github_project.md) |
| 製品の方向性 | [Current Direction](guide/CURRENT_DIRECTION.md)の最新部分 |
| 測定・GUI の設計 | [設計ガイドライン](guide/MEASUREMENT_INSTRUMENT_DESIGN_GUIDELINES.md)の判断優先順位・実装要件の境界と対象の節 |
| UI の認知負荷と操作性 | [UI/UX 原則](guide/UIUX-Cognitive-Principles.md) |
| 開発環境・貢献方法の詳細 | [開発ガイド](docs/development.en.md)、[Contributing](CONTRIBUTING.md) |

## 実装と検証

* Python は3.12以降。Python・Pytest・Ruff・Mypy は `.venv/bin/` の実行ファイルを使う。
* GUI 表示文字列は `tr()` で管理する。翻訳の基準は `src/assets/lang/en.json`、各言語は同じディレクトリの JSON。
* 検証は変更した挙動と回帰リスクに合わせる。作業終了時は毎回 `./.venv/bin/ruff check .` と `./.venv/bin/ruff format --check .` を実行する。
* 自動修正・整形は必要なファイルだけに限定する。全体フォーマットは専用 PR に分ける。
* Markdown は見出し・コードブロック前後に空行を置き、行末空白を除く。リストマーカーと番号順を統一し、裸の URL は山括弧で囲む。変更後は Markdown lint を実行する。
* 変更点、検証結果、未確認事項を報告する。失敗・未実施を成功扱いしない。

### UIサイズの上限

Qt の各プラットフォームの既定フォントで、`minimumSizeHint` を次の上限内に収める。幅には Linux・macOS のフォント差と長い翻訳に備えた約80pxのバッファを含む。

| 対象 | 幅 × 高さ |
| --- | --- |
| MainWindow | 1400 × 740 px |
| 各モジュールのコンテンツWidget | 1180 × 690 px |

レイアウト・翻訳の変更時、新規モジュールのリリース前、CI 相当の最終確認では、[全言語 UI サイズ検証](.agents/workflows/tool_usage.md#uiサイズ検証)を実行する。超過時はスクロール、タブ、折りたたみ、最小サイズ・サイズポリシーの見直しで対応する。

## Pull Request

* ブランチ名は指定がなければ `codex/<目的>` とする。
* PR は Ready for review で作成し、作成後に `isDraft:false` を確認する。ユーザーが明示した場合だけ Draft にする。
* PR 前は [CI Pre-checker](.agents/skills/ci-prechecker/SKILL.md)を実行する。検証に失敗したら原因を調べ、残る問題を明記する。

## コードの入口

| ファイル | 役割 |
| --- | --- |
| `main_gui.py` | 言語設定、スプラッシュ中の事前ロード、GUI 起動 |
| `src/gui/main_window.py` | サイドバー、モジュール切替・遅延ロード |
| `src/core/audio_engine.py` | `sounddevice` による Audio I/O |
| `src/core/config_manager.py` | `config.json` の管理 |
| `src/core/localization.py` | `LocalizationManager` と `tr()` |

共通ルールはこのファイル、コマンドは Tool Usage Guide、GitHub 操作は共通手順、作業固有の判断は各スキルで管理する。更新はコード・設定で確認できた事実に基づく。
