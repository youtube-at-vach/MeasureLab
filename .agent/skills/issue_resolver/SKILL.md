---
name: Issue Resolver
description: GitHubのIssueを自動的に解決するスキル
---

# Issue Resolver Skill

このスキルは、GitHubのIssueを読み込み、分析し、解決までの一連の流れを自動化します。

## ツール使用に関する注意

`.agent/workflows/tool_usage.md` に従い、以下のツールを使用してください。

- テスト: `.venv/bin/pytest`
- リント: `.venv/bin/ruff`
- 型チェック: `.venv/bin/mypy`

## Workflow

### 1. Issueの読み込み

GitHub MCPを使用して、指定されたIssueを読み込みます。

- ツール: `mcp_github-mcp-server_issue_read`
- 手順: Issueの内容、コメント、ラベルなどを確認します。

### 2. 問題分析と実装可能性の確認

問題を分析し、現在のコードベースで解決可能かどうかを判断します。

- 必要なファイルやコード箇所を特定します。
- 解決策を策定します。

### 3. Issueへのコメント

分析結果に基づいて、Issueにコメントします。

- **解決可能な場合**: 「解決に向けて作業を開始します」という旨のコメントを投稿します。
- **解決不能な場合**: 理由を説明するコメントを投稿し、ここで作業を終了します。
- ツール: `mcp_github-mcp-server_add_issue_comment`

### 4. ブランチ作成と作業開始

適切なブランチを作成し、実装を開始します。

- ツール: `mcp_github-mcp-server_create_branch`
- ブランチ名: `fix/issue-[number]` や `feature/issue-[number]` など、Issue番号を含めます。

### 5. 実装と検証

コードを変更して問題を修正します。

- コード修正後、実装がIssueを解決するものであるかを再検証します。
- 必要に応じてテストコードを追加・修正します。

### 6. リントとCI確認

コードの品質を保証します。`.agent/workflows/tool_usage.md` に記載されたコマンドを使用してください。

```bash
.venv/bin/ruff check --fix
.venv/bin/mypy .
.venv/bin/pytest
```

- CIが通る状態であることをローカルで可能な限り確認します。

### 7. コミットとPR作成

変更をコミットし、Pull Requestを作成します。

- ツール(PR作成): `mcp_github-mcp-server_create_pull_request`
- PRの内容には、解決するIssueへのリンク (`Closes #IssueNumber`) を含めます。

### 8. 完了報告

Issueに対して、PRを提出し検証待ちであることを報告します。

- ツール: `mcp_github-mcp-server_add_issue_comment`
- コメント例: 「PR #[PRNumber] を提出しました。レビューと検証をお願いします。」
