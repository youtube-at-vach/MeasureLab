---
name: agent-simple-ready-issue
description: MeasureLab の小さな不具合・表示修正・改善を GitHub Issue 化し、Project の Ready に登録する。コード実装は行わない。
---

# 小さな修正を Ready に登録

対象と期待する挙動が明確な小規模修正を、短い Issue にする。新しい測定機能の候補選定は [Backlog 登録](../agent-proposal-backlog-issue/SKILL.md)、既存 Issue の計画作成は [Ready 計画](../agent-ready-task-planner/SKILL.md)を使う。

## 内容を確かめる

1. 対象コード・テスト・関連資料を読み、現在の挙動と依頼された変更を区別する。
2. [GitHub 共通手順](../../workflows/github_project.md)で同じ目的の Issue を確認する。既存 Issue があれば再利用し、修正済み・終了済みのものは理由を確認して重複作成や再開を避ける。
3. 測定仕様や製品方針の決定が必要なら、必要な質問を具体化する。小さな修正を独断で機能追加へ広げない。

## 登録する

タイトルは不具合なら `[Bug] ...`、改善なら `[Feature] ...` とし、対応する既存ラベル `bug` または `enhancement` を使う。本文には次を簡潔に記す。

* 現在の問題と、修正後に期待する状態。
* 変更対象、維持する挙動、対象外の範囲。
* 結果を確認する方法と、コード・テスト・資料への参照。

実装方法は固定しない。新規表示文字列には翻訳、レイアウト変更には UI サイズ確認を含めるなど、変更に必要な検証だけを書く。

Issue 作成 → Project 追加 → `Ready` 設定の順に進める。既存 Issue の Ready 化は依頼に含まれる場合だけ行い、`Working`・`Review`・`Blocked` などからの変更はその意図を確認する。Priority は指定された場合だけ変更する。

## 完了

Issue URL、Project の最終状態、ラベル・優先度を確認して報告する。作業ツリーは変更しない。一部失敗した場合は、作成済み Issue を維持して残りの操作を示す。
