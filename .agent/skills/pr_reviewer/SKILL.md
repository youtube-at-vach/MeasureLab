---
name: PR Reviewer
description: Pull Requestのレビュー手順を自動化・標準化するスキル
---

# PR Reviewer Skill

このスキルは、指定されたPull Requestの内容を取得・分析し、コードレビューを行い、結果をGitHubに投稿するまでの一連の流れを自動化します。
「自身のPRの場合は承認できない」というGitHubの制約を回避するロジックや、標準的なチェック項目を含みます。

## Review Checklist

このスキルを実行する際は、以下のチェック項目を `task.md` に追加して作業を進めてください。

- [ ] **リポジトリ情報の取得**: リポジトリ名、オーナーを確認
- [ ] **PR情報の取得**: PR番号、タイトル、説明、作成者、ブランチ名を取得
- [ ] **変更ファイルの確認**: どのようなファイルが変更されたか一覧を取得
- [ ] **Diffの取得と分析**: 実際の変更差分を取得
- [ ] **コードレビューの実施**:
    - [ ] **ロジックの正確性**: バグ、競合状態、エッジケースの考慮
    - [ ] **スタイルと品質**: 命名規則、可読性、複雑度
    - [ ] **テストとドキュメント**: テストの追加・修正、ドキュメントの更新（docstring等）
    - [ ] **CI/安全性**: テストのパス、セキュリティリスクがない
- [ ] **レビュー結果の投稿**: `APPROVE` または `COMMENT` で投稿
    - [ ] **PRが面白いと感じるかを必ず心を込めて感想を入れること**: `COMMENT` で投稿
 
## Workflow

### 1. PR情報の取得

GitHub MCPを使用して、PRの基本情報と変更ファイル一覧を取得します。

- ツール: `mcp_github-mcp-server_pull_request_read` (method='get', method='get_files')

### 2. 変更内容（Diff）の分析

変更の差分を取得し、上記のチェックリストに基づいてコードを分析します。

- ツール: `mcp_github-mcp-server_pull_request_read` (method='get_diff')
- 特に、並行処理（Concurrency）やパフォーマンスへの影響、既存機能への副作用を注意深く確認します。

### 3. レビュー結果の作成と投稿

分析結果に基づき、PRにレビューを投稿します。

**重要: 承認制限の回避**
PR作成者がエージェント自身のアカウント（または実行ユーザー）である場合、GitHubのAPIでは `APPROVE` が拒否されることがあります。
そのため、以下のロジックでイベントタイプを決定します。

- **他者のPRの場合**: 問題なければ `event="APPROVE"` で投稿。
- **自身のPRの場合**: `event="COMMENT"` を使用し、本文に「本来はApproveですが、自身のPRのためコメントとして投稿します」といった旨を記載して投稿。

#### 実行例

```python
# 擬似コード
if pr.user.login == current_user.login:
    submit_review(event="COMMENT", body="LGTM! (Self-approval restriction)")
else:
    submit_review(event="APPROVE", body="LGTM!")
```
