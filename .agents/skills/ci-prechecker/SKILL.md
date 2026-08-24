---
name: ci-prechecker
description: PR送信前にCI相当のローカル検証を行うときに使用します。Ruff、Mypy、翻訳キー、Markdown lint、Pytestを順番に実行し、失敗時は修正して再検証します。
---

# CI Pre-checker Skill

このスキルは、コードの変更がリモートのCI基盤で正常にパスするかどうかを事前にローカルで確認します。

## 事前準備

開発用ツールがプロジェクトの仮想環境にインストールされていることを確認してください。
詳細は [tool usage guide](../../workflows/tool_usage.md) を参照してください。

## 実行手順

以下のチェックを順番に実行してください。

### 1. コードのリンティング (Ruff)

Pythonコードのスタイルとエラーをチェックします。

```bash
./.venv/bin/ruff check .
```

必要に応じてLintの自動修正を行ってください。

```bash
./.venv/bin/ruff check --fix .
```

### 2. フォーマット確認 (Ruff)

フォーマット済みかどうかを確認します。

```bash
./.venv/bin/ruff format --check .
```

失敗した場合は、まず今回変更したファイルが原因か確認してください。必要な場合に限り、変更したファイルだけを対象に`./.venv/bin/ruff format <変更したファイル>`を実行します。`./.venv/bin/ruff format .`による全体フォーマットは自動的に実行しません。

### 3. 型チェック (Mypy)

Pythonの静的型チェックを実行します。

```bash
./.venv/bin/mypy src main_gui.py
```

### 4. 翻訳キーの整合性チェック

多言語対応の翻訳キーに不足がないか確認します。

```bash
./.venv/bin/python scripts/check_trn_keys.py
```

### 5. ドキュメントのリンティング (Markdown lint)

Markdownファイルのフォーマットをチェックします。

```bash
npx markdownlint-cli2 "**/*.md" "#node_modules"
```

### 6. ユニットテストの実行 (Pytest)

すべてのユニットテストを実行し、機能が壊れていないか確認します。

```bash
./.venv/bin/pytest
```

---

## 完了条件

すべてのステップでエラーが出ないことが確認できれば、CIをパスする可能性が非常に高いです。
エラーが発生した場合は、修正した後に再度チェックを実行してください。
