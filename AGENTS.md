---
description: MeasureLabで作業するエージェントの共通ルールと参照先
---

# Agent Guide

MeasureLabの作業では、まずこのガイドで共通ルールを確認し、必要な手順だけを参照してください。
コマンドはリポジトリのルートで実行します。

## 作業の進め方と参照先

1. Gitの状態と対象コードを確認し、ユーザーの変更や無関係な変更を上書きしない。
2. 変更に関係する設計資料と、作業に対応するスキルを読む。
3. 実装・文書を更新し、変更に応じた検証を実行する。
4. PR前のチェックを行い、変更内容・検証結果・未確認事項を報告する。

| 確認したいこと | 参照先 |
| --- | --- |
| 環境構築、起動、テスト、UIサイズ検証 | [Tool Usage Guide](.agents/workflows/tool_usage.md) |
| PR前の検証順序 | [CI Pre-checker](.agents/skills/ci-prechecker/SKILL.md) |
| 製品の方向性 | [Current Direction](guide/CURRENT_DIRECTION.md) |
| 計測器としての設計 | [設計ガイドライン](guide/MEASUREMENT_INSTRUMENT_DESIGN_GUIDELINES.md) |
| UIの設計 | [UI/UX原則](guide/UIUX-Cognitive-Principles.md) |
| 一般的な開発・貢献方法 | [開発ガイド](docs/development.en.md)、[Contributing](CONTRIBUTING.md) |

## 作業別スキル

依頼された作業に対応するスキルを参照してください。各スキルの対象範囲と完了条件に従います。

| 作業 | スキル |
| --- | --- |
| 提案をIssue化してBacklogに登録 | [agent-proposal-backlog-issue](.agents/skills/agent-proposal-backlog-issue/SKILL.md) |
| 小規模な改善をIssue化してReadyに登録 | [agent-simple-ready-issue](.agents/skills/agent-simple-ready-issue/SKILL.md) |
| Ready Issueの実装計画を作成 | [agent-ready-task-planner](.agents/skills/agent-ready-task-planner/SKILL.md) |
| Working Issueを実装してPRを作成 | [agent-working-task-implement](.agents/skills/agent-working-task-implement/SKILL.md) |
| 翻訳漏れ・キー不整合を修正 | [multilingual-translator](.agents/skills/multilingual-translator/SKILL.md) |
| リリースを準備 | [release-manager](.agents/skills/release-manager/SKILL.md) |

## 開発時の共通ルール

* Pythonは3.12以降。Python・Pytest・Ruff・Mypyは `.venv/bin/` の実行ファイルを使用する。
* GUI表示文字列は `tr()` で囲む。翻訳は `src/assets/lang/*.json` にあり、`en.json` を基本とする。
* 作業終了時は毎回 `./.venv/bin/ruff check .` と `./.venv/bin/ruff format --check .` を実行する。
* フォーマット確認が失敗したら、今回変更したファイルが原因か確認し、必要なファイルだけを整形する。全体フォーマットは専用PRに分ける。
* Markdownは見出し・コードブロック前後に空行を置き、行末の空白を除く。リストマーカーと番号順を統一し、裸のURLは `<https://example.com>` のように囲む。変更後はMarkdown lintを実行する。

### UIサイズの上限

小さい画面でもコントロールがはみ出さないよう、`minimumSizeHint` を次の上限内に収めます。

| 対象 | 幅 × 高さ |
| --- | --- |
| MainWindow | 1400 × 740 px |
| 各モジュールのコンテンツWidget | 1180 × 690 px |

検証には各プラットフォームのQt既定フォントを使います。幅の上限にはLinuxとmacOSの
フォント差・長い翻訳を考慮した約80pxのバッファを含めています。

レイアウト・翻訳の変更時、新規モジュールのリリース前、CI相当の最終確認では、
[UIサイズ検証](.agents/workflows/tool_usage.md#uiサイズ検証)を全言語で実行してください。
上限を超えた場合は、`QScrollArea`、タブ、折りたたみ可能なグループへの整理や、
最小サイズ・サイズポリシーの見直しで対応します。

## コードを探すときの入口

| ファイル | 役割 |
| --- | --- |
| `main_gui.py` | 言語設定の読み込み、スプラッシュ中の事前ロード、GUI起動 |
| `src/gui/main_window.py` | サイドバー、モジュール切替・遅延ロード |
| `src/core/audio_engine.py` | `sounddevice` を使うAudio I/O |
| `src/core/config_manager.py` | `config.json` の管理 |
| `src/core/localization.py` | `LocalizationManager` と `tr()` |

## Pull Request

* PRはReady for review（`draft=false`）で作成する。ユーザーが明示的に指定した場合だけDraftにする。
* `gh pr create` に通常は `--draft` を付けず、作成後にDraftではないことを確認する。
* 検証が失敗した場合は原因を確認する。未実施・失敗した検証を成功として報告しない。

このガイドと参照先は、コード・設定で確認できた事実に基づいて更新してください。
共通ルールはこのファイル、実行コマンドはTool Usage Guide、作業固有の手順は各スキルに記載します。
