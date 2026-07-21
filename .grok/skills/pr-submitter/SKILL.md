---
name: pr-submitter
description: >
  After work is done, run full local verification (ruff, mypy, translation keys,
  UI size limits, markdown lint, pytest), then push and open a Pull Request.
  Use when the user asks to submit a PR, open a PR, PR 送付, create pull request,
  or runs /pr-submitter.
metadata:
  short-description: "Verify, push, and open a PR"
---

# PR Submitter

実装完了後にローカル検証を行い、リモートへプッシュして PR を作成する。

## ワークフロー

### 1. main との同期

```bash
git fetch origin main
git merge origin/main
```

コンフリクトがあれば解消してから進む。

### 2. ローカル品質検証 (CI Pre-check)

`./.venv/bin/` のツールを使う。すべてパスするまで PR を作らない。

#### ① Ruff

```bash
./.venv/bin/ruff check .
```

必要なら:

```bash
./.venv/bin/ruff check --fix .
```

#### ② Mypy

```bash
./.venv/bin/mypy src main_gui.py
```

#### ③ 翻訳キー

```bash
./.venv/bin/python scripts/check_trn_keys.py
```

#### ④ UI サイズ制限

MainWindow ≤ 1290×740、モジュールコンテンツ ≤ 1070×690:

```bash
./.venv/bin/python scripts/check_ui_size_limits.py
```

#### ⑤ Markdown lint

```bash
npx markdownlint-cli2 "**/*.md" "#node_modules"
```

#### ⑥ Pytest

```bash
./.venv/bin/pytest
```

### 3. コミットとプッシュ

**コミット・プッシュ前にユーザー確認を取る**（未依頼のコミットを作らない）。

1. 状態確認:

```bash
git status
git diff
git log -5 --oneline
```

2. ステージ・コミット（メッセージは変更目的を明確に）:

```bash
git add <対象ファイル>
git commit -m "$(cat <<'EOF'
feat/fix: [概要]

EOF
)"
```

3. プッシュ（新規ブランチは `-u`）:

```bash
git push -u origin HEAD
```

### 4. Pull Request 作成

**PR 作成前にユーザー確認を取る。**

```bash
gh pr create --title "[PRの簡潔なタイトル]" --base main --body "$(cat <<'EOF'
## Summary
- ...

## Test plan
- [ ] ローカル CI pre-check 全パス
- [ ] ...

EOF
)"
```

関連 Issue があれば `Closes #N` を本文に含める。

### 5. 完了報告

- PR URL
- 検証結果（各チェックの成否）
- 残作業があれば明記

## 関連

- 検証のみ: `ci-prechecker`
- 翻訳漏れ修正: `multilingual-translator`
