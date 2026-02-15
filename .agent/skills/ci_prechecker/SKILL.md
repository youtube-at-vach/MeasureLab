---
name: CI Pre-checker
description: PRを送る前に変更がCIを通るかどうかを確認するスキル（Ruff, Mypy, 翻訳キー, Markdown lint, Pytest）
---

# CI Pre-checker Skill

このスキルは、コードの変更がリモートのCI基盤で正常にパスするかどうかを事前にローカルで確認します。

## 事前準備

開発用ツールがプロジェクトの仮想環境にインストールされていることを確認してください。
詳細は [.agent/workflows/tool_usage.md](file:///home/hotstaff/github-vach/MeasureLab/.agent/workflows/tool_usage.md) を参照してください。

## 実行手順

以下のチェックを順番に実行してください。

### 1. コードのリンティング (Ruff)

Pythonコードのスタイルとエラーをチェックします。

```bash
.venv/bin/ruff check .
```

必要に応じて自動修正を行ってください。

```bash
.venv/bin/ruff check --fix .
```

### 2. 型チェック (Mypy)

Pythonの静的型チェックを実行します。

```bash
.venv/bin/mypy src main_gui.py
```

### 3. 翻訳キーの整合性チェック

多言語対応の翻訳キーに不足がないか確認します。

```bash
.venv/bin/python3 scripts/check_trn_keys.py
```

### 4. ドキュメントのリンティング (Markdown lint)

Markdownファイルのフォーマットをチェックします。

```bash
npx markdownlint-cli2 "**/*.md" "#node_modules"
```

### 5. ユニットテストの実行 (Pytest)

すべてのユニットテストを実行し、機能が壊れていないか確認します。

```bash
.venv/bin/pytest
```

---

## 完了条件

すべてのステップでエラーが出ないことが確認できれば、CIをパスする可能性が非常に高いです。
エラーが発生した場合は、修正した後に再度チェックを実行してください。
