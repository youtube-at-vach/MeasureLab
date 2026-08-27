---
name: agent-working-task-implement
description: MeasureLab の GitHub Project で Working の既存 Issue を1件実装し、検証済みの Ready for review PR を作成して Project Status を Review に進めるときに使用します。新規仕様の策定や未承認の製品判断は行いません。
---

# エージェント：Working タスク実装

Working 状態のIssueを正本の実装計画とコードベースに基づいて実装し、アプリケーション変更と運用スキル変更を混在させずに完了させる。ユーザーがこのフローを依頼した場合に限り、Issue、Project、ブランチ、PRを更新する。

## 1. 対象と前提を確認する

リポジトリルートで次を確認する。

- `git status --short --branch`、`AGENTS.md`、`gh auth status`
- `gh repo view --json nameWithOwner,owner,url`
- `gh project list --owner <owner> --format json`
- `gh project item-list <number> --owner <owner> --limit 100 --format json`

`Agents: MeasureLab` の Project を使用し、Status が `Working` の既存 Issue を一覧化する。ユーザーが対象を指定しなければ、Working が1件の場合だけそれを選ぶ。複数ある場合は Priority、Issue の計画コメント、Measurement Integrity への寄与から一意に選べない限り推測せず、対象指定を求める。

対象Issueの本文・コメント・ラベル・担当者・Project item IDを読み、`## 実装計画（正本）` コメントがあることを確認する。計画がない、古い、または仕様判断が未確定なら実装せず、必要な決定事項をIssueコメントへ記録して停止する。

## 2. 設計と実装を照合する

計画が参照する設計資料と対象コードを実際のパスで解決して読む。MeasureLab の主要資料は次のとおり。

- `guide/MEASUREMENT_INSTRUMENT_DESIGN_GUIDELINES.md`
- `guide/PROPOSED_FEATURES.md`
- `guide/CURRENT_DIRECTION.md`
- 対象モジュール、既存テスト、日英ドキュメント、必要な共通契約

計画とコードの差分を確認し、状態所有者・状態遷移、データ契約、品質フラグ、callback／worker／GUI境界、異常時・停止後・リセット後の挙動を維持する。測定系の変更では有限値、安全なクリッピング、境界付き履歴、異常のラッチとリセット、callback 非ブロックを実装・テストへ反映する。GUI文字列は `tr()` で管理し、翻訳キーとUIサイズ上限を確認する。

## 3. 実装と検証

`codex/<短い目的>` ブランチで実装する。既存のユーザー変更を上書きせず、対象Issueの範囲外へ広げない。テストは正常系だけでなく、入力不正、非有限値、I/Oエラー、データ欠落、設定変更、開始失敗、停止後保持、明示的リセットを対象契約に応じて追加する。

変更に応じて、少なくとも次を実行する。

- 対象Pytest、必要なら `QT_QPA_PLATFORM=offscreen ./.venv/bin/pytest -q`
- `./.venv/bin/ruff check .`
- `./.venv/bin/ruff format --check .`
- `./.venv/bin/mypy src main_gui.py`
- `./.venv/bin/python scripts/check_trn_keys.py`
- `npx markdownlint-cli2 "**/*.md" "#node_modules"`
- GUI変更時は `./.venv/bin/python scripts/check_ui_size_limits.py`

失敗は原因を修正して再検証する。検証不能なハードウェア依存は、実行した範囲と未実行理由をPRへ明記する。

## 4. PRとProjectをReviewへ進める

差分、`git diff --check`、ブランチ、Issue番号を確認してコミット・pushする。`gh pr create` には `--draft` を付けず、PR本文にSummary、Validation、関連Issueを記録する。作成後に `isDraft:false` とOpen状態を確認する。

PR作成後、`gh project item-list` でIssueのProject itemを再取得し、`gh project field-list` でStatusフィールドと `Review` の選択肢IDを毎回取得する。`gh project item-edit` で対象Issueを `Working` から `Review` に更新する。PRの自動Project項目が別に作成されても、Issueを指す既存項目を誤って編集しない。

最後に `gh issue view`、`gh pr view`、Project item、`git status --short --branch` を再確認し、対象Issue・PR URL、検証結果、最終Status、変更ファイルを報告する。

## 5. 運用スキル自体を同時に依頼された場合

アプリ実装PRとスキル変更PRは別ブランチ・別PRにする。スキル追加には `skill-creator` の手順を使い、必要最小限の `SKILL.md` と `agents/openai.yaml` を作成する。`quick_validate.py`、Markdown lint、`git diff --check` を実行し、PRはReady for reviewで作成する。スキルPRのProject Statusを変更する場合も、対象項目を再取得してから行う。
