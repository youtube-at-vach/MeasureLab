---
name: agent-working-task-implement
description: MeasureLab の Working Issue を正本の計画に沿って実装・検証し、レビュー可能な PR を作成して Project を Review に進める。
---

# Working Issue を実装

## 着手する

1. [GitHub 共通手順](../../workflows/github_project.md)で `Working` の Issue を1件選び、本文・コメントから有効な `実装計画（正本）` を特定する。
2. 計画が参照する設計資料、対象コード・テスト・日英ドキュメントを読み、現在の実装との差を確認する。
3. `codex/<短い目的>` ブランチで作業する。既存変更と衝突する場合は独立した worktree を使うなど、ユーザーの変更を保護する。

正本がない、計画の前提が崩れている、または製品判断が未確定なら、確認した事実と必要な決定を Issue に記録して実装を止める。ファイル移動などの通常の実装差は計画の目的に沿って解決し、変更理由を残す。

## 実装・検証する

Issue の範囲と既存契約を守る。測定系では callback の非ブロック性、単位・校正・有限値・品質情報、異常時と停止／リセット後の挙動を対象に応じて扱う。設計指針の例を理由に、不要な監視や安全機構を追加しない。

変更した挙動と回帰リスクを検証するテストを追加・更新する。GUI の翻訳とレイアウトは [Agent Guide](../../../AGENTS.md)に従う。PR 前に [CI Pre-checker](../ci-prechecker/SKILL.md)を実行し、失敗や未実施を成功扱いしない。

## Review に進める

1. 差分と `git diff --check` を確認し、対象変更だけをコミット・push する。
2. 同じ変更の既存 PR があれば更新し、なければ PR を作成する。本文に問題と変更後の挙動、関連 Issue、検証結果・制限を記載する。
3. PR が Open かつ `isDraft:false` であることを確認する。ユーザーが Draft を指定した場合はその指定を優先し、Ready for review として完了報告しない。
4. レビュー可能な PR と必須検証の成功を確認してから、対象 Issue の Project Status を `Working` → `Review` に変更する。PR 側の別項目を編集しない。

## 完了

Issue・PR URL、検証結果と未確認事項、Project の最終 Status を報告する。PR 作成後に状態更新が失敗した場合は、その PR を維持して状態更新だけを再開する。
