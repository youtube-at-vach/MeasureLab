---
description: Instructions for running development tools (pytest, ruff, mypy)
---

# Tool Usage Guide

## Python仮想環境

Pythonと開発ツールは、リポジトリの仮想環境にある実行ファイルを使用します。
システムにインストールされた同名コマンドは使用しません。

- Python: `./.venv/bin/python`
- Pytest: `./.venv/bin/pytest`
- Ruff: `./.venv/bin/ruff`
- Mypy: `./.venv/bin/mypy`

仮想環境がない場合は、Python 3.12以降で作成して依存関係を導入します。

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -U pip
./.venv/bin/python -m pip install -r requirements.txt
```

## 開発時の確認

変更内容に応じて、次のコマンドを使用します。

```bash
./.venv/bin/ruff check .
./.venv/bin/ruff format --check .
./.venv/bin/mypy src main_gui.py
./.venv/bin/python scripts/check_trn_keys.py
./.venv/bin/pytest -q
```

Ruffの`format`は、作業終了時とCI相当の確認では`--check`でフォーマット済みかを確認します。
`./.venv/bin/ruff format .`による全体フォーマットは通常実行しません。チェックに失敗した場合は、今回変更したファイルが原因かを先に確認し、必要なら変更したファイルだけを`ruff format`で整形します。
全体フォーマットが必要な場合は、機能変更と分けた専用PRで実施します。

Markdownを変更した場合は、Markdown lintも実行します。

```bash
npx markdownlint-cli2 "**/*.md" "#node_modules"
```

GUIレイアウトまたは翻訳を変更した場合は、全言語のUIサイズ上限を確認します。

```bash
./.venv/bin/python scripts/check_ui_size_limits.py
```

実装中に英語だけを素早く確認する場合は `--quick` を使用できますが、最終確認では
引数なしのコマンドを実行します。

## PR前のCI相当チェック

PRを作成する前は、`.agents/skills/ci-prechecker/SKILL.md` に記載された順序で
Ruff、Mypy、翻訳キー、Markdown lint、全Pytestを実行します。

ハードウェアテストは通常のPytestではスキップされます。対応機器を使用して明示的に
検証する場合に限り、Pytestへ `--hardware` を指定します。

## バージョン管理

Git操作にはシステムの `git` コマンドを使用します。ユーザーの作業を保護するため、
無関係な変更を上書きせず、破壊的な操作を避けてください。
