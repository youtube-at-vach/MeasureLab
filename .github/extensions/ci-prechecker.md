# CI Pre-checker Skill

## 概要

CI Pre-checker スキルは、Pull Request を送信する前に、ローカルでコードがCIをパスするか事前確認するために設計されています。
このスキルは `.agent/skills/ci_prechecker/SKILL.md` で定義された仕様に基づいており、プロジェクトレベルで利用可能になりました。

## 使用方法

```bash
/slash-command ci-prechecker
```

または、以下のコマンドを個別に実行：

```bash
.venv/bin/ruff check .
.venv/bin/mypy src main_gui.py
python3 scripts/check_trn_keys.py
npx markdownlint-cli2 "**/*.md" "#node_modules"
.venv/bin/pytest
```

## 実装の場所

- **仕様書**: `.agent/skills/ci_prechecker/SKILL.md`
- **プロジェクト拡張**: `.github/extensions/` (このファイル)

## チェック項目

このスキルが確認する項目：

1. **Ruff (コードリンティング)**
   - Pythonコードのスタイルとエラー
   - 必要に応じて自動修正

2. **Mypy (型チェック)**
   - Pythonの静的型チェック

3. **翻訳キー整合性チェック**
   - 多言語対応の翻訳キーの欠落確認

4. **Markdown Lint**
   - ドキュメントのフォーマット検証

5. **Pytest (ユニットテスト)**
   - すべてのテストの実行と検証

## 前提条件

- Python 3.12+ と仮想環境 (`.venv`) が構成されていること
- 依存パッケージが `requirements.txt` から導入されていること

## 完了条件

すべてのステップでエラーが出ないことが確認できれば、CIをパスする可能性が非常に高いです。
