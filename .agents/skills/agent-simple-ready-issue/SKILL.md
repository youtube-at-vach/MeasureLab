---
name: agent-simple-ready-issue
description: "MeasureLab の小規模なバグ修正・表示修正・軽微な改善を、実装せずに GitHub Issue 化して Agents: MeasureLab Project の Ready に登録するときに使用します。大規模な提案選定や Ready Issue の実装計画には使用しません。"
---

# エージェント：簡易修正 Ready Issue 化

小さな修正依頼を、実装者がそのまま着手できる短い GitHub Issue に整理し、MeasureLab の GitHub Project で `Ready` にする。Issue 化と Project 更新までを担当し、コード、テスト、翻訳、ドキュメント、PR は変更しない。

## 適用範囲

- 明確な対象と目的がある小規模なバグ修正、UI 表示修正、軽微な改善を扱う。
- 例: 色、余白、ラベル、表示条件、既存挙動を変えない小さな回帰修正。
- ユーザーが Issue 化や Ready 登録を依頼した場合だけ、GitHub Issue と Project を変更する。
- 新しい測定機能の候補選定や提案からの Backlog 化には `../agent-proposal-backlog-issue/SKILL.md` を使う。
- 既存 Ready Issue のコードベース調査と実装計画には `../agent-ready-task-planner/SKILL.md` を使う。

## 1. 対象を事実確認する

リポジトリルートで次を確認する。

- `git status --short --branch`
- `AGENTS.md`（存在する場合）
- 対象コード、既存テスト、関連ドキュメント
- `gh repo view --json nameWithOwner,owner,url`
- `gh project list --owner <owner> --format json`

MeasureLab では `Agents: MeasureLab` を優先するが、番号を毎回取得する。対象が小規模か判断できない場合は、詳細な提案 Issue 化へ拡張せず、ユーザーに確認する。

実装を推測して Issue の範囲を広げない。現在のコード上の事実、依頼された見た目または挙動、不変にしたい既存機能だけを記録する。

## 2. 重複と Project 状態を確認する

Issue 作成前に、タイトル・対象・目的に関する既存 Issue を `gh issue list --state all` と必要な `gh issue view` で検索する。Project 項目も `gh project item-list <number> --owner <owner> --format json` で確認する。

- 同じ目的の Issue がある場合は新規作成しない。
- 既存 Issue が Project にあり、ユーザーが Ready 化を依頼している場合は、その項目を再利用して Ready にする。
- 同じ目的の Issue が複数あり、どれを正本にするか判断できない場合は作成・更新を止める。
- Project 上の別の Issue を、タイトルが似ているだけで変更しない。

書き込み直前に、対象リポジトリ、Project、重複のないことをもう一度確認する。

## 3. Issue を作成する

タイトルは短い英語で、通常は次の形式にする。

- 不具合・回帰: `[Bug] <修正対象と期待する状態>`
- 軽微な改善: `[Feature] <改善内容>`

既存のラベルを確認し、バグなら `bug`、改善なら `enhancement` を付ける。本文は短くても次を含める。

```markdown
## 背景

現状のコード上の事実と、利用者が困る点。

## 目的

修正後に実現する状態。

## 必要な対応

- 変更対象と維持すべき既存挙動
- 必要なら回帰テストや表示確認

## 範囲と留保

小規模な修正に限定すること、実装方法や細かな受け入れ条件は実装時に決めること。

## 参照

- 対象コード
- 関連テスト
- 関連ドキュメント
```

GUI の Issue では、新規表示文字列が発生する場合の `tr()`、翻訳キー整合、既定フォントでの UI サイズへの配慮を必要に応じて書く。背景色や既存ラベルだけの修正で表示文字列が増えない場合、翻訳変更を要求しない。測定ロジック、データモデル、共通基盤、エクスポートまで勝手に範囲を広げない。

## 4. Project を Ready にする

新規 Issue は Project 追加と Status 更新を分けて実行する。

1. `gh issue create --repo <owner>/<repo> --title ... --body ... --label <label>` で作成する。
2. 返された Issue URL を使い、`gh project item-add <number> --owner <owner> --url <issue-url> --format json` で追加する。
3. `gh project field-list <number> --owner <owner> --format json` で Status フィールド ID と `Ready` オプション ID を毎回取得する。固定 ID を再利用しない。
4. `gh project item-edit --id <item-id> --field-id <status-field-id> --single-select-option-id <ready-option-id> --project-id <project-id>` で Ready に設定する。

Priority はユーザーが指定した場合だけ設定する。指定がない場合は未設定のままにする。

Issue 作成後に Project 追加または Status 更新が失敗した場合、同じ Issue を作り直さない。作成済み Issue URL、取得済み item ID、失敗した操作、再開に必要な Project 情報を報告する。

## 5. 最終確認

次を確認する。

- `gh issue view <number> --repo <owner>/<repo> --json number,title,url,state,labels,body`
- `gh project item-list <number> --owner <owner> --format json` で対象 Issue の Project 名と `Ready` を確認
- `git status --short --branch` で作業ツリーに変更がないことを確認

完了報告には Issue URL、Project 名、Status、Priority、ラベル、コード変更がないことを含める。

## 参照

- [MeasureLab Agent Guide](../../../AGENTS.md)
- [提案 Backlog Issue 化スキル](../agent-proposal-backlog-issue/SKILL.md)
- [Ready タスク計画化スキル](../agent-ready-task-planner/SKILL.md)
