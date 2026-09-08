---
description: MeasureLabの環境構築、起動、開発ツールと検証コマンド
---

# Tool Usage Guide

共通ルールと作業別スキルの入口は [AGENTS.md](../../AGENTS.md) を参照してください。
以下はリポジトリのルートで実行するコマンドです。POSIXシェル（Linux・macOS）向けの表記です。

## 環境構築

Python 3.12以降を使用します。仮想環境がない場合は作成し、アプリと開発ツールの依存関係を導入します。
`requirements.txt` だけではRuff・Mypyなどが揃わないため、`dev` extrasもインストールします。

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -U pip
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python -m pip install -c constraints.txt -e '.[dev]'
```

以後はシステムの同名コマンドではなく、次の実行ファイルを使います。

| ツール | 実行ファイル |
| --- | --- |
| Python | `./.venv/bin/python` |
| Pytest | `./.venv/bin/pytest` |
| Ruff | `./.venv/bin/ruff` |
| Mypy | `./.venv/bin/mypy` |

Markdown lintにはNode.jsとnpmが必要です。OSの依存ライブラリなどは
[開発ガイド](../../docs/development.en.md)を参照してください。
`PyWavelets` のPythonでのimport名は `pywt` です。

## 起動とデバッグ

```bash
./.venv/bin/python main_gui.py
```

* Linuxのオーディオ環境では、必要に応じてJACK / PipeWireと `ConfigManager` の `pipewire_jack_resident` 設定を確認します。
* `MEASURELAB_DEBUG_WINDOWS=1` でウィンドウ挙動のログを出力します。
* `MEASURELAB_DEBUG_WINDOWS_TRACE=1` でウィンドウ出現時のスタックトレースを出力します。

## 開発中の検証

作業終了時には、変更の種類にかかわらず両方を実行します。

```bash
./.venv/bin/ruff check .
./.venv/bin/ruff format --check .
```

失敗した場合は今回の変更が原因か確認します。整形が必要なら変更したファイルだけを
`./.venv/bin/ruff format <変更したファイル>` で整形し、全体フォーマットは専用PRに分けます。

型チェックと、CIと同じ厳格な翻訳キーチェック:

```bash
./.venv/bin/mypy src main_gui.py
./.venv/bin/python scripts/check_trn_keys.py --strict
```

Markdown変更時:

```bash
npx markdownlint-cli2 "**/*.md" "#node_modules"
```

### テスト

最小スモークテスト:

```bash
./.venv/bin/python -m pytest -q tests/logic_verification/core/test_config_manager.py tests/logic_verification/core/test_utils.py
```

メインウィンドウ周辺のテスト:

```bash
./.venv/bin/python -m pytest -q tests/logic_verification/gui/test_main_window_activity.py
```

全体テスト:

```bash
./.venv/bin/pytest -q
```

ハードウェアテストは通常スキップされます。対応機器を使用して明示的に検証する場合だけ
`--hardware` を指定してください。このオプションではハードウェア以外のテストがスキップされるため、全体テストの代わりにはなりません。

### UIサイズ検証

レイアウト・翻訳の変更時、新規モジュールのリリース前、CI相当の最終確認では全言語を検証します。
サイズ上限と超過時の対処は [AGENTS.md](../../AGENTS.md#uiサイズの上限) を参照してください。
QApplicationやC拡張の競合を避けるため、Pytestとは独立して実行します。

```bash
./.venv/bin/python scripts/check_ui_size_limits.py
```

成功時は `Verification Passed!` と終了コード `0`、超過時は対象モジュールの詳細と終了コード `1` を返します。
実装中に英語だけを確認する場合は次を使えますが、最終確認は引数なしで実行してください。

```bash
./.venv/bin/python scripts/check_ui_size_limits.py --quick
```

## PR前の検証

[CI Pre-checker](../skills/ci-prechecker/SKILL.md)の順序で、Ruff lint、Ruff format、Mypy、
翻訳キー、Markdown lint、全Pytestを実行します。CIとの照合では翻訳キーに `--strict` を指定し、
UIサイズ検証も全言語で実行してください。
実際のCIの対象・環境は [.github/workflows/ci.yml](../../.github/workflows/ci.yml) で確認できます。

失敗時は原因を確認して修正・再検証し、実行できなかった検証は理由とともに報告します。
Git操作にはシステムの `git` を使用し、PRの作成方法は [AGENTS.md](../../AGENTS.md#pull-request) に従います。
