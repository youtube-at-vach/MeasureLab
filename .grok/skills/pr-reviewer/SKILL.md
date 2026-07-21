---
name: pr-reviewer
description: >
  Review a GitHub Pull Request: fetch PR metadata and diff, analyze quality
  and risk, then post a review. Use when the user asks to review a PR, PR
  レビュー, code review on a PR, or runs /pr-reviewer.
metadata:
  short-description: "Review a PR and post findings"
---

# PR Reviewer

指定 PR を取得・分析し、コードレビュー結果を GitHub に投稿する。

## Review Checklist

作業中はこのチェックリストを追う。

- [ ] リポジトリ情報（owner/repo）
- [ ] PR 情報（番号、タイトル、説明、作成者、ブランチ）
- [ ] 変更ファイル一覧
- [ ] Diff の取得と分析
- [ ] コードレビュー
  - [ ] ロジックの正確性（バグ、競合、エッジケース）
  - [ ] スタイルと品質（命名、可読性、複雑度）
  - [ ] テストとドキュメント（追加・更新の妥当性）
  - [ ] CI / 安全性（テスト、セキュリティ）
- [ ] レビュー投稿（`APPROVE` または `COMMENT`）
  - [ ] 心のこもった短い感想を必ず含める

## Workflow

### 1. PR 情報の取得

`gh` を優先して使う（MCP が使える場合は同等の GitHub ツールでも可）。

```bash
gh pr view <PR番号> --json number,title,body,author,headRefName,baseRefName,url,files
gh pr diff <PR番号>
```

PR 番号が不明な場合はユーザーに確認するか、`gh pr list` で候補を示す。

### 2. Diff 分析

チェックリストに沿ってレビューする。特に次を重点確認する。

- 並行処理・タイミング依存
- パフォーマンス影響
- 既存機能への副作用
- 翻訳キー / UI サイズ / 音声 I/O など MeasureLab 固有リスク

### 3. レビュー結果の投稿

**投稿前にユーザー確認を取る**（公開アクションのため）。

#### 承認制限の回避

PR 作成者が実行ユーザー自身の場合、GitHub は `APPROVE` を拒否することがある。

| 状況 | event |
|------|--------|
| 他者の PR で問題なし | `APPROVE` |
| 自身の PR、または問題あり | `COMMENT`（自身の場合は「本来 Approve だが self-approval 制限のため COMMENT」と明記） |

```bash
# 他者 PR・問題なし
gh pr review <PR番号> --approve --body "$(cat <<'EOF'
## Review
...
EOF
)"

# COMMENT（自身の PR または指摘あり）
gh pr review <PR番号> --comment --body "$(cat <<'EOF'
## Review
...
EOF
)"
```

### 4. 完了

投稿したレビューの要約と PR URL をユーザーに報告する。

## 注意

- 破壊的変更・セキュリティ問題は明確に指摘する
- 無関係なリファクタ提案でノイズを増やさない
- Grok 組み込みの `/review`（PR モード）と役割が近い。ユーザーが PR 番号と MeasureLab 向けチェックを求めている場合はこのスキルを優先する
