---
name: agent-ready-task-planner
description: MeasureLab の GitHub Project で Ready の既存 Issue を1件選び、コードベースから実装計画を作成して Issue に正本として記録し、Ready から Working、または判断不能時に Blocked へ更新するときに使用します。コード実装、PR 作成、新規 Issue 作成は行いません。
---

# エージェント：Ready タスク計画化

MeasureLab の GitHub Project で Ready になっている既存 Issue を、実際の資料・コード・テストに基づいて実装計画化する。計画を既存 Issue のコメントへ正本として記録できた場合は Status を Working にし、測定仕様や製品方針を安全に決められない場合はブロック理由を記録して Status を Blocked にする。

## 適用範囲

- ユーザーが現在の Ready タスクを読み込み、実装計画を立て、Issue と Project の状態を更新するよう依頼した場合に使用する。
- 既存 Issue の実装計画を扱う。提案から新規 Issue を作成して Backlog に登録する場合は、`../agent-proposal-backlog-issue/SKILL.md` を使用する。
- コード、翻訳、ドキュメント、PR はこのタスクでは変更しない。作業ツリーを読み取り専用に保つ。
- Issue コメントと Project Status の更新は外部状態の変更であるため、ユーザーがこのフローを依頼した場合だけ実行する。

## 1. 対象と前提を確認する

リポジトリルートを確認し、最初に次を読む。

- `git status --short --branch`
- `AGENTS.md`
- `gh auth status`
- `gh repo view --json nameWithOwner,owner,url`
- `gh project list --owner <owner> --format json`

MeasureLab では `Agents: MeasureLab` を優先するが、毎回存在と番号を確認する。`gh project item-list <number> --owner <owner> --format json` で Status が `Ready` の項目を確認する。

対象の指定がなく Ready が1件ならその Issue を対象にする。Ready が複数ある場合は、ユーザーが指定したものを優先する。指定がなく、Priority と Measurement Integrity への寄与を比較しても一意に決められない場合は、Issue を推測で選ばずブロック理由を記録する。

対象 Issue について、タイトル、本文、コメント、ラベル、担当者、現在の Project item ID と Status を読む。Issue 検索でも同じ目的の Issue がないか確認し、別 Issue を誤って更新しない。

## 2. 設計資料と実装を読む

省略せず読む資料と対象コードを、リポジトリの実際のパスで解決する。

1. 設計指針全文。現在の MeasureLab では `guide/MEASUREMENT_INSTRUMENT_DESIGN_GUIDELINES.md`。
2. `guide/PROPOSED_FEATURES.md` の Overview、Status Legend、Selected Additions、Implemented/Covered、Conditional、On hold or Not Suitable、Deferred Reference Topics。
3. `guide/CURRENT_DIRECTION.md` 全体と、対象モジュールのコード、テスト、日英ドキュメント。
4. 必要に応じて `docs/widget_feature_implementation_matrix.md`、共通データ契約、エクスポート、翻訳、UI サイズ検証の実装。

既存の `agent-proposal-backlog-issue` がルートや `docs/` 配下を参照していても、現在のリポジトリで実体が `guide/` 配下に移動している場合は `rg --files` で解決した実パスを正本として使う。

計画では、少なくとも次をコード上の事実として特定する。

- 現在の状態所有者と状態遷移、開始・停止・キャンセル・リセット後の挙動。
- 既存のデータモデル、単位、校正、品質フラグ、スナップショット、エクスポート形式。
- AudioEngine callback、ワーカー、GUI スレッド、タイマー、ファイル I/O の境界。
- 正常系、入力不正、非有限値、クリッピング、I/O エラー、データ欠落、設定変更、停止後の挙動。
- 既存テストの検証範囲と、追加すべき自動テスト・GUI テスト。

## 3. 計画を確定できるか判定する

実装計画は、ファイル単位の変更候補、データ契約、状態遷移、UI、エクスポート、検証コマンドまで一意に書ける場合だけ確定する。測定系では、callback のリアルタイム性、境界付き履歴、有限値、安全なクリッピング、異常のラッチとリセットを計画へ含める。GUI では `tr()`、全言語の翻訳キー整合、長い翻訳での UI サイズ上限を含める。

次のような判断をコードや設計資料から安全に導けない場合は、実装計画を捏造せず Blocked とする。

- イベント分類、判定閾値、単位、校正、Pass/Fail の製品仕様。
- 入力／出力／ルーティング異常が結果を無効化する条件。
- 必要な fixture、基準経路、ハードウェア前提。
- 停止・キャンセル・部分結果・リセット後に保持すべき状態。
- 既存契約と競合するためユーザーまたはプロダクト判断が必要な仕様。

単に実装が大きい、テストが多い、時間がかかるという理由だけでは Blocked にしない。安全な既定値をコードベースと設計指針から決められるなら、その前提を計画へ明記して進める。

## 4. Issue へ正本を書き込む

書き込み直前に Issue と Project item を再取得し、対象がまだ同じ Issue で Ready であることを確認する。既存 Issue の本文は提案・背景として保持し、計画はコメントへ追加して「このコメントを実装計画の正本とする」と明記する。

計画が確定した場合のコメントは、少なくとも次を含める。

```markdown
## 実装計画（正本）

### 背景と現状の不足
### 選定・実装方針
### 実装範囲
### データモデルと状態遷移
### UI、翻訳、エクスポート
### ファイル単位の変更計画
### 完了条件と検証
### 参照
```

完了条件には、正常系、失敗系、停止後の保持、新規 Run／リセット、既存機能の回帰、callback 非ブロック、有限値、異常履歴、翻訳キー、全言語 UI サイズ、Ruff、Mypy、対象 Pytest、Markdown lint、必要な UI サイズ検証を含める。新規 GUI 文字列は `tr()` 管理を前提にする。

コメント本文は `gh issue comment <number> --repo <owner>/<repo> --body-file <temporary-file>` で追加できる。本文作成の一時ファイルは `apply_patch` で作成し、投稿後に削除して作業ツリーへ残さない。

計画を確定できない場合は、代わりに次の構造でブロック理由をコメントする。

```markdown
## ブロック理由

### コードベースで確認できた事実
### 判断できない仕様
### 計画確定に必要な回答
### 参照
```

ブロック理由には、推測が測定結果の誤認につながる理由と、再開に必要な具体的な決定事項を書く。コード変更や翻訳変更は行わない。

## 5. Project Status を更新する

Issue コメントの投稿が成功した後にだけ Status を変更する。`gh project field-list <number> --owner <owner> --format json` で Status フィールド ID と選択肢 ID を毎回取得し、固定値を使い回さない。

- 計画コメントを投稿できた場合: `Ready` → `Working`
- ブロック理由コメントを投稿した場合: `Ready` → `Blocked`

`gh project item-edit --id <item-id> --field-id <status-field-id> --single-select-option-id <option-id> --project-id <project-id>` を使う。Status 更新に失敗しても同じコメントを再投稿したり、同じ Issue を作成し直したりしない。既存コメント URL と再試行に必要な Project 情報を報告する。

## 6. 最終確認と報告

次を再確認する。

- `gh issue view <number> --repo <owner>/<repo> --json number,title,state,comments,url`
- `gh project item-list <number> --owner <owner> --format json --jq ...`
- `git status --short --branch`

完了報告には、対象 Issue URL、計画コメントまたはブロックコメント URL、Project 名、最終 Status、Priority、ラベル、コード変更がないことを含める。計画が正本として登録されていれば Working、判断不能なら Blocked と明示する。

## 参照

- [提案 Backlog Issue 化スキル](../agent-proposal-backlog-issue/SKILL.md)
- [MeasureLab Agent Guide](../../../AGENTS.md)
