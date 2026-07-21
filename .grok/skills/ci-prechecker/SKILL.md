---
name: ci-prechecker
description: >
  Run local pre-CI checks before opening a PR: Ruff, Mypy, translation keys,
  Markdown lint, and Pytest. Use when the user asks for CI precheck, pre-PR
  checks, 事前チェック, lint+test, or runs /ci-prechecker.
metadata:
  short-description: "Local pre-CI: ruff, mypy, trn, md, pytest"
---

# CI Pre-checker

リモート CI を通す前に、ローカルで同等のチェックを順に実行する。

## 前提

- 作業ディレクトリはリポジトリルート（`MeasureLab/`）
- 開発ツールは必ず `./.venv/bin/` 配下を使う（詳細は `AGENTS.md`）

## 実行手順

各ステップで失敗したら修正してから次へ進む。

### 1. リンティング (Ruff)

```bash
./.venv/bin/ruff check .
```

必要なら自動修正:

```bash
./.venv/bin/ruff check --fix .
```

### 2. 型チェック (Mypy)

```bash
./.venv/bin/mypy src main_gui.py
```

### 3. 翻訳キー整合性

```bash
./.venv/bin/python scripts/check_trn_keys.py
```

### 4. Markdown lint

```bash
npx markdownlint-cli2 "**/*.md" "#node_modules"
```

### 5. ユニットテスト (Pytest)

```bash
./.venv/bin/pytest
```

短時間のスモークだけ必要な場合（ユーザー指示時）:

```bash
./.venv/bin/python -m pytest -q tests/logic_verification/core/test_config_manager.py tests/logic_verification/core/test_utils.py
```

## 完了条件

全ステップがエラーなく通ること。結果をユーザーに要約して報告する。
エラーがあった場合は修正後に再実行する。

## 関連

- 翻訳漏れの修正まで任された場合は `multilingual-translator` スキルを使う
- PR 作成まで含む場合は `pr-submitter` スキルを使う
