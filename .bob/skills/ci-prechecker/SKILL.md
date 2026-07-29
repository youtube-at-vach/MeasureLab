---
name: ci-prechecker
description: Use when the user wants to verify changes pass CI before submitting a PR — runs Ruff lint, Mypy type check, translation key check, Markdown lint, and Pytest in sequence.
---

# CI Pre-checker Skill

このスキルは、コードの変更がリモートのCI基盤で正常にパスするかどうかを事前にローカルで確認します。

各チェックを `execute_command` で順番に実行してください。エラーが発生した場合は修正してから次のステップへ進みます。

## 実行手順

### 1. コードのリンティング (Ruff)

Pythonコードのスタイルとエラーをチェックします。

```bash
./.venv/bin/ruff check .
```

違反が出た場合は自動修正を試みます。

```bash
./.venv/bin/ruff check --fix .
```

自動修正できない違反は `apply_diff` または `search_and_replace` で手動修正してください。

### 2. 型チェック (Mypy)

Pythonの静的型チェックを実行します。

```bash
./.venv/bin/mypy src main_gui.py
```

エラーが出た場合は該当ファイルを修正してください。

### 3. 翻訳キーの整合性チェック

多言語対応の翻訳キーに不足がないか確認します。

```bash
./.venv/bin/python scripts/check_trn_keys.py
```

問題がある場合は `multilingual-translator` スキルに従って対処してください。

### 4. ドキュメントのリンティング (Markdown lint)

Markdownファイルのフォーマットをチェックします。

```bash
npx markdownlint-cli2 "**/*.md" "#node_modules"
```

### 5. ユニットテストの実行 (Pytest)

すべてのユニットテストを実行し、機能が壊れていないか確認します。

```bash
./.venv/bin/pytest -q
```

## 完了条件

すべてのステップでエラーがゼロになればCIをパスできる状態です。
エラーが発生した場合は修正後に該当ステップを再実行してください。
