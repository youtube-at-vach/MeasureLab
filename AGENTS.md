---
description: Instructions for running development tools (pytest, ruff, mypy)
---

# Agent Guide

このリポジトリで作業するエージェント向けのガイドです。
セットアップ、起動、テスト、構成、および開発時の注意点をまとめます。

## 言語 / ローカライズ方針

- GUI 表示文字列は **`tr()` で囲って** 多言語対応を前提に実装してください。
- 翻訳ファイルは `src/assets/lang/*.json` にあります（`en.json` が基本）。
- 翻訳キーの整合チェックは `scripts/check_trn_keys.py` を使えます。

## 実行環境

- OS: Linux
- Python: 3.10+ 想定（README 記載）
- 推奨 Python 実行環境: `./.venv/bin/python`

## セットアップ (venv)

1. venv 作成
   - `python3 -m venv .venv`
   - `./.venv/bin/python -m pip install -U pip`
2. 依存導入
   - `./.venv/bin/python -m pip install -r requirements.txt`

> [!NOTE]
> `PyWavelets` は pip パッケージ名ですが、Python での import 名は `pywt` です。

## ツール利用ガイド (Tool Usage)

ほとんどの開発ツールでは、`.venv/bin/` にある実行ファイルを使用する必要があります。

- `pytest` -> `./.venv/bin/pytest` (テスト実行)
- `ruff`   -> `./.venv/bin/ruff` (リンター/フォーマッター)
- `mypy`   -> `./.venv/bin/mypy` (型チェック)

### VS Code タスク

VS Code から `pytest (venv)` タスクを利用可能です。

### スラッシュコマンド

```bash
/slash-command test
/slash-command lint
/slash-command typecheck
```

## 起動方法

### GUI (MeasureLab 本体)

- `./.venv/bin/python main_gui.py`

起動時の流れ:

- `main_gui.py`: `ConfigManager` で言語設定を読み、スプラッシュ表示中にモジュールを事前ロード。
- `src/gui/main_window.py`: サイドバーでモジュールを切り替え。モジュールは基本的に遅延ロードされます。

## テスト

最小スモークテスト:

- `./.venv/bin/python -m pytest -q tests/functional/test_config.py tests/functional/test_si_formatting.py`

全体テスト:

- `./.venv/bin/python -m pytest -q`

## 主要ディレクトリ / コンポーネント

- `src/gui/main_window.py`: 画面全体（サイドバー・遅延ロード）。
- `src/core/audio_engine.py`: Audio I/O (`sounddevice` ベース)。
- `src/core/config_manager.py`: `config.json` の管理。
- `src/core/localization.py`: `LocalizationManager` と `tr()`。

## Linux オーディオ注意点

README にもある通り、JACK / PipeWire の利用が推奨される場合があります。
`ConfigManager` の `pipewire_jack_resident` 設定を確認してください。

## デバッグ用の環境変数

- `MEASURELAB_DEBUG_WINDOWS=1`: ウィンドウ挙動ログ。
- `MEASURELAB_DEBUG_WINDOWS_TRACE=1`: ウィンドウ出現時のスタックトレース。

## ドキュメント表記ルール (Markdown Lint)

このプロジェクトでは `markdownlint-cli2` を使用しています。

- **空白・改行**: 行末の不要な空白削除、見出しやコードブロック前後の空行。
- **リスト**: マーカーの統一、番号付きリストの順序。
- **URL**: `<https://example.com>` のように `<>` で囲む。

チェックコマンド:

```bash
npx markdownlint-cli2 "**/*.md" "#node_modules"
```

---
このファイルは「確認できた事実」に基づき、常に最新の状態に保つようにしてください。
